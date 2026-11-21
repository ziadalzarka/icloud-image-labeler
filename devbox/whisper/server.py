import contextlib
import hmac
import json
import logging
import multiprocessing
import os
import signal
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

MODEL = os.environ.get("WHISPER_MODEL", "large-v3")
PORT = int(os.environ.get("PORT", "8178"))
IDLE_UNLOAD_SECONDS = float(os.environ.get("IDLE_UNLOAD_SECONDS", "300"))
API_KEY_FILE = os.environ.get("API_KEY_FILE", "/run/secrets/api-key")
SAMPLE_RATE = 16000
WINDOW_SAMPLES = 30 * SAMPLE_RATE
PCM_SCALE = 32768.0
MAX_BODY_BYTES = 512 * 1024 * 1024
IDLE_CHECK_SECONDS = 5
STOP_TIMEOUT_SECONDS = 10

logger = logging.getLogger("labeler-whisper")


class BadRequest(Exception):
    pass


def window_languages(model, audio) -> dict:
    windows = []
    for start in range(0, len(audio), WINDOW_SAMPLES):
        _, _, probabilities = model.detect_language(
            audio=audio[start : start + WINDOW_SAMPLES]
        )
        windows.append({code: float(p) for code, p in probabilities})
    return {"windows": windows}


def transcribe(model, audio, language, clip_timestamps) -> dict:
    segments, info = model.transcribe(
        audio,
        language=language,
        clip_timestamps=clip_timestamps or "0",
        condition_on_previous_text=False,
    )
    return {
        "language": info.language,
        "segments": [
            {
                "start": s.start,
                "end": s.end,
                "text": s.text,
                "avg_logprob": s.avg_logprob,
                "compression_ratio": s.compression_ratio,
                "no_speech_prob": s.no_speech_prob,
            }
            for s in segments
        ],
    }


def handle_model_request(model, language_codes, kind, pcm, options):
    import numpy as np

    language = options.get("language")
    if language and language not in language_codes:
        raise BadRequest(f"Unknown language: {language}")
    audio = np.frombuffer(pcm, dtype="<i2").astype(np.float32) / PCM_SCALE
    if kind == "languages":
        return window_languages(model, audio)
    return transcribe(model, audio, language, options.get("clip_timestamps"))


def run_model_process(connection, model_name):
    from faster_whisper import WhisperModel
    from faster_whisper.tokenizer import _LANGUAGE_CODES

    try:
        model = WhisperModel(
            model_name, device="cuda", compute_type="float16", local_files_only=True
        )
    except Exception as error:
        connection.send(("error", f"Couldn't load {model_name}: {error}"))
        return
    connection.send(("ready", None))
    while True:
        try:
            request = connection.recv()
        except EOFError:
            return
        if request is None:
            return
        try:
            result = handle_model_request(model, _LANGUAGE_CODES, *request)
            connection.send(("ok", result))
        except BadRequest as error:
            connection.send(("bad_request", str(error)))
        except Exception as error:
            connection.send(("error", f"{type(error).__name__}: {error}"))


class ModelProcess:
    def __init__(self, model_name: str, idle_unload_seconds: float):
        self.model_name = model_name
        self.idle_unload_seconds = idle_unload_seconds
        self.lock = threading.Lock()
        self.process = None
        self.connection = None
        self.last_used = time.monotonic()

    @property
    def loaded(self) -> bool:
        return self.process is not None and self.process.is_alive()

    def run(self, kind: str, pcm: bytes, options: dict) -> dict:
        with self.lock:
            if not self.loaded:
                self._stop()
                self._start()
            try:
                self.connection.send((kind, pcm, options))
                status, result = self.connection.recv()
            except (EOFError, OSError) as error:
                self._stop()
                raise RuntimeError(f"The model process stopped: {error}") from error
            finally:
                self.last_used = time.monotonic()
        if status == "bad_request":
            raise BadRequest(result)
        if status == "error":
            raise RuntimeError(result)
        return result

    def stop(self):
        with self.lock:
            self._stop()

    def unload_when_idle(self):
        while True:
            time.sleep(IDLE_CHECK_SECONDS)
            if not self.lock.acquire(blocking=False):
                continue
            try:
                idle = time.monotonic() - self.last_used
                if self.process is not None and (
                    not self.loaded or idle >= self.idle_unload_seconds
                ):
                    self._stop()
                    logger.info(f"Unloaded {self.model_name} after {idle:.0f}s idle")
            finally:
                self.lock.release()

    def _start(self):
        started = time.monotonic()
        context = multiprocessing.get_context("spawn")
        connection, child_connection = context.Pipe()
        process = context.Process(
            target=run_model_process,
            args=(child_connection, self.model_name),
            daemon=True,
        )
        process.start()
        child_connection.close()
        try:
            status, message = connection.recv()
        except EOFError:
            process.join(STOP_TIMEOUT_SECONDS)
            status = "error"
            message = f"The model process exited with code {process.exitcode}"
        if status != "ready":
            process.join(STOP_TIMEOUT_SECONDS)
            connection.close()
            raise RuntimeError(message)
        self.process, self.connection = process, connection
        logger.info(f"Loaded {self.model_name} in {time.monotonic() - started:.1f}s")

    def _stop(self):
        if self.process is None:
            return
        with contextlib.suppress(OSError):
            self.connection.send(None)
        self.process.join(STOP_TIMEOUT_SECONDS)
        if self.process.is_alive():
            self.process.kill()
            self.process.join()
        self.connection.close()
        self.process = self.connection = None


def parse_clip_timestamps(value: str) -> list[float]:
    try:
        times = [float(t) for t in value.split(",") if t.strip()]
    except ValueError:
        raise BadRequest(f"Bad clip_timestamps: {value}") from None
    if any(t < 0 for t in times):
        raise BadRequest(f"Bad clip_timestamps: {value}")
    return times


def transcribe_options(query: str) -> dict:
    params = parse_qs(query)
    options = {}
    if params.get("language", [""])[0]:
        options["language"] = params["language"][0].strip().lower()
    if params.get("clip_timestamps", [""])[0]:
        options["clip_timestamps"] = parse_clip_timestamps(params["clip_timestamps"][0])
    return options


def make_handler(api_key: str, model_process: ModelProcess):
    class Handler(BaseHTTPRequestHandler):
        server_version = "labeler-whisper"
        protocol_version = "HTTP/1.1"

        def do_GET(self):
            if urlparse(self.path).path != "/health":
                self.send_json(404, {"error": "Not found"})
                return
            self.send_json(
                200, {"status": "ok", "model": MODEL, "loaded": model_process.loaded}
            )

        def do_POST(self):
            url = urlparse(self.path)
            if url.path not in ("/languages", "/transcribe"):
                self.close_connection = True
                self.send_json(404, {"error": "Not found"})
                return
            length = int(self.headers.get("Content-Length") or 0)
            if length > MAX_BODY_BYTES:
                self.close_connection = True
                self.send_json(413, {"error": "Audio is too large"})
                return
            pcm = self.rfile.read(length)
            if not self.authorized():
                self.send_json(401, {"error": "Unauthorized"})
                return
            try:
                if not pcm or len(pcm) % 2:
                    raise BadRequest("Body must be 16 kHz mono int16 PCM")
                options = (
                    transcribe_options(url.query) if url.path == "/transcribe" else {}
                )
                started = time.monotonic()
                result = model_process.run(url.path.strip("/"), pcm, options)
            except BadRequest as error:
                self.send_json(400, {"error": str(error)})
                return
            except Exception as error:
                logger.exception(f"{url.path} failed")
                self.send_json(500, {"error": str(error)})
                return
            seconds = len(pcm) / 2 / SAMPLE_RATE
            logger.info(
                f"{url.path}: {seconds:.0f}s of audio in "
                f"{time.monotonic() - started:.1f}s"
            )
            self.send_json(200, result)

        def authorized(self) -> bool:
            header = self.headers.get("Authorization", "")
            return hmac.compare_digest(header, f"Bearer {api_key}")

        def send_json(self, status: int, body: dict):
            data = json.dumps(body, ensure_ascii=False).encode()
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

        def log_message(self, format, *args):
            logger.debug(format % args)

    return Handler


def stop_on_sigterm(signum, frame):
    raise KeyboardInterrupt


def main():
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)-7s %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )
    signal.signal(signal.SIGTERM, stop_on_sigterm)
    api_key = Path(API_KEY_FILE).read_text().strip()
    model_process = ModelProcess(MODEL, IDLE_UNLOAD_SECONDS)
    threading.Thread(target=model_process.unload_when_idle, daemon=True).start()
    server = ThreadingHTTPServer(
        ("0.0.0.0", PORT), make_handler(api_key, model_process)
    )
    logger.info(
        f"Serving {MODEL} on port {PORT}, "
        f"unloading after {IDLE_UNLOAD_SECONDS:.0f}s idle"
    )
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
        model_process.stop()


if __name__ == "__main__":
    main()
