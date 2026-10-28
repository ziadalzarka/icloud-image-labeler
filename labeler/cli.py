"""Argparse CLI with run, daemon, config, and metrics subcommands."""

import argparse
import gc
import json
import logging
import sys
from importlib.metadata import version

from labeler import config, daemon, metrics, migrate
from labeler.checks import check_dependencies
from labeler.discovery import (
    get_unprocessed_media,
    get_untranscribed_videos,
    is_unlabeled,
    load_photos_db,
)
from labeler.init import run_init
from labeler.llm import Server, ServerPool, video_settings_tag
from labeler.processor import process_batch
from labeler.shutdown import install_handlers as install_signal_handlers
from labeler.shutdown import is_shutting_down
from labeler.shutdown import wait as shutdown_wait
from labeler.transcriber import INSTALL_HINT, Whisper, parse_languages
from labeler.transcriber import is_available as transcription_available

logger = logging.getLogger("labeler")

DEFAULT_REFRESH_INTERVAL = 21600  # seconds (6 hours)
DEFAULT_DATASETTE_PORT = 8001
OUTDATED_VIDEOS_PER_CYCLE = 20
UNTRANSCRIBED_VIDEOS_PER_CYCLE = 500
PRE_BATCHING_VIDEO_FRAMES = 5


def _setup_logging(verbose: bool = False):
    logging.basicConfig(
        level=logging.DEBUG if verbose else logging.INFO,
        format="%(asctime)s %(levelname)-7s [%(name)s] %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )
    # Keep third-party loggers at INFO to avoid dumping base64/HTTP bodies
    for name in ("httpx", "openai", "httpcore"):
        logging.getLogger(name).setLevel(logging.INFO)


def _video_labeling_changed(video_frames: int, video_frame_batch: int) -> bool:
    one_request = video_frame_batch <= 0 or video_frame_batch >= video_frames
    return not (video_frames == PRE_BATCHING_VIDEO_FRAMES and one_request)


def _resolve_servers(args, cfg) -> list[Server]:
    """Build the list of Server backends from CLI flags and config.

    Thread counts come from (in order): the per-server spec/config field, the
    CLI ``--threads`` flag (applied as the default for every server lacking
    its own value), then the legacy global ``threads`` config key, then 1.
    """
    default_threads = (
        args.threads if args.threads is not None else cfg.get("threads", 1)
    )

    # 1. CLI --server wins entirely if provided (one spec per flag).
    if args.server:
        specs = [config._parse_server_spec(s) for s in args.server]
        return [
            Server(
                base_url=s["base_url"],
                model=s["model"],
                api_key=s.get("api_key", ""),
                threads=s.get("threads", default_threads),
            )
            for s in specs
        ]

    # 2. Legacy single-server CLI flags --base-url/--model/--api-key override
    #    the config's first server (or its legacy base_url/model).
    cfg_servers = config.resolve_servers(cfg)
    if args.base_url or args.model or args.api_key:
        first = cfg_servers[0] if cfg_servers else {}
        return [
            Server(
                base_url=args.base_url or first.get("base_url", ""),
                model=args.model or first.get("model", ""),
                api_key=args.api_key or first.get("api_key", ""),
                threads=first.get("threads", default_threads),
            )
        ]

    # 3. Otherwise take whatever the config says.
    return [
        Server(
            base_url=s.get("base_url", ""),
            model=s.get("model", ""),
            api_key=s.get("api_key", ""),
            threads=s.get("threads", default_threads),
        )
        for s in cfg_servers
    ]


def _resolve_config(args, cfg):
    """Merge CLI flags with config file values, CLI taking precedence."""
    servers = _resolve_servers(args, cfg)
    resolved = {
        "servers": servers,
        "limit": args.limit if args.limit is not None else cfg["limit_per_cycle"],
        "days": args.days if args.days is not None else cfg["days"],
        "to_days": args.to_days if args.to_days is not None else cfg["to_days"],
        "video_frames": (
            args.video_frames if args.video_frames is not None else cfg["video_frames"]
        ),
        "video_frame_batch": (
            args.video_frame_batch
            if args.video_frame_batch is not None
            else cfg["video_frame_batch"]
        ),
        "photo": args.photo if args.photo is not None else cfg["photo"],
        "video": args.video if args.video is not None else cfg["video"],
        "transcribe": (
            args.transcribe if args.transcribe is not None else cfg["transcribe"]
        ),
        "whisper_model": args.whisper_model or cfg["whisper_model"],
        "whisper_languages": (
            args.whisper_languages
            if args.whisper_languages is not None
            else cfg["whisper_languages"]
        ),
    }

    resolved["write"] = cfg["write"]
    if args.write is True:
        resolved["write"] = True
    elif args.dry_run is True:
        resolved["write"] = False

    resolved["loop"] = args.loop
    resolved["reindex"] = bool(args.reindex)
    resolved["poll_interval"] = cfg["poll_interval"]
    resolved["max_dimension"] = cfg["max_dimension"]
    return resolved


def _whisper(rc) -> Whisper | None:
    if not rc["transcribe"]:
        return None
    if not rc["video"]:
        logger.warning("Transcription runs as part of video labeling, which is off.")
        return None
    if not transcription_available():
        logger.error(
            "Transcription needs mlx-whisper, which runs on Apple Silicon only. "
            f"Install it with: {INSTALL_HINT}"
        )
        return None
    return Whisper(rc["whisper_model"], parse_languages(rc["whisper_languages"]))


def _untranscribed_limit(limit: int) -> int:
    if limit > 0:
        return min(limit, UNTRANSCRIBED_VIDEOS_PER_CYCLE)
    return UNTRANSCRIBED_VIDEOS_PER_CYCLE


def _run(args, cfg):
    """One-shot or loop processing."""
    rc = _resolve_config(args, cfg)
    if not rc["photo"] and not rc["video"]:
        logger.error("Nothing to process: photo and video labeling are off.")
        return
    if not rc["servers"]:
        logger.error("No LLM servers configured. Run 'icloud-image-labeler init'.")
        return

    pool = ServerPool(rc["servers"])
    for s in pool.servers():
        logger.info(f"Server: {s.base_url} ({s.model}, threads={s.threads})")
    whisper = _whisper(rc)
    if whisper:
        languages = ", ".join(whisper.languages) or "any"
        logger.info(f"Transcription: {whisper.model} (languages: {languages})")
    expected_tags = pool.model_tags() if rc["reindex"] else None
    expected_video_tag = (
        video_settings_tag(rc["video_frames"], rc["video_frame_batch"])
        if _video_labeling_changed(rc["video_frames"], rc["video_frame_batch"])
        else None
    )
    if rc["reindex"]:
        logger.info(
            f"Reindex mode: accepting model tags {sorted(expected_tags)}, "
            f"video tag {expected_video_tag}"
        )

    def discover():
        photosdb = load_photos_db()
        items = get_unprocessed_media(
            photosdb,
            limit=rc["limit"],
            days_back=rc["days"],
            to_days=rc["to_days"],
            photo=rc["photo"],
            video=rc["video"],
            reindex=rc["reindex"],
            expected_model_tags=expected_tags,
            expected_video_tag=expected_video_tag,
            outdated_video_limit=OUTDATED_VIDEOS_PER_CYCLE,
        )
        untranscribed = (
            get_untranscribed_videos(
                photosdb,
                days_back=rc["days"],
                to_days=rc["to_days"],
                exclude_uuids={p.uuid for p in items},
                limit=_untranscribed_limit(rc["limit"]),
            )
            if whisper
            else []
        )
        return items, untranscribed

    try:
        _label_loop(args, rc, pool, whisper, discover)
    except KeyboardInterrupt:
        logger.info("Interrupted, exiting.")


def _label_loop(args, rc, pool, whisper, discover):
    while not is_shutting_down():
        keep_running, more_backlog = _process_one_cycle(
            args, rc, pool, whisper, discover
        )
        gc.collect()

        if not keep_running or not rc["loop"] or is_shutting_down():
            break
        if more_backlog:
            logger.info(
                "More videos to relabel or transcribe remain; "
                "starting the next cycle now"
            )
            continue
        logger.info(f"Sleeping {rc['poll_interval']}s until next cycle...")
        if shutdown_wait(rc["poll_interval"]):
            break


def _process_one_cycle(args, rc, pool, whisper, discover) -> tuple[bool, bool]:
    if args.uuid:
        photosdb = load_photos_db()
        items = [p for u in args.uuid for p in photosdb.photos(uuid=[u])]
        untranscribed = []
        if not items:
            logger.error(f"No photos found for UUIDs: {args.uuid}")
            return False, False
        logger.info(f"Processing {len(items)} item(s) by UUID")
    else:
        items, untranscribed = discover()

    if not items and not untranscribed:
        logger.info("No unprocessed media found.")
        return True, False

    videos_ok = process_batch(
        items,
        server_pool=pool,
        video_frames=rc["video_frames"],
        video_frame_batch=rc["video_frame_batch"],
        max_dimension=rc["max_dimension"],
        write=rc["write"],
        discover_fn=lambda: discover()[0],
        refresh_interval=DEFAULT_REFRESH_INTERVAL,
        whisper=whisper,
        untranscribed=untranscribed,
    )
    outdated = sum(1 for p in items if not p.isphoto and not is_unlabeled(p))
    backlog = (
        outdated >= OUTDATED_VIDEOS_PER_CYCLE
        or len(untranscribed) >= UNTRANSCRIBED_VIDEOS_PER_CYCLE
    )
    return True, backlog and videos_ok > 0


def _config_cmd(args, cfg):
    action = args.config_action

    if action == "show":
        print(json.dumps(cfg, indent=2))
    elif action == "set":
        if not args.key or not args.value:
            print("Usage: labeler config set <key> <value>")
            sys.exit(1)
        try:
            config.set_value(args.key, args.value)
            print(f"Set {args.key} = {args.value}")
        except ValueError as e:
            print(str(e))
            sys.exit(1)
    elif action == "reset":
        config.reset_config()
        print("Config reset to defaults.")
    elif action == "path":
        print(config.CONFIG_PATH)
    else:
        print(f"Unknown config action: {action}")
        sys.exit(1)


def _daemon_cmd(args):
    action = args.daemon_action
    if action == "start":
        daemon.start()
    elif action == "stop":
        daemon.stop()
    elif action == "restart":
        daemon.restart()
    elif action == "status":
        daemon.status()
    else:
        print(f"Unknown daemon action: {action}")
        sys.exit(1)


def _migrate_cmd(args):
    install_signal_handlers()
    run_migration = (
        migrate.remove_transcripts
        if args.migration == "redo-transcripts"
        else migrate.normalize_library_keywords
    )
    try:
        run_migration(write=not args.dry_run, limit=args.limit or 0)
    except KeyboardInterrupt:
        logger.info("Interrupted, exiting.")


def _pricing_cmd(args):
    action = args.pricing_action

    if action == "list":
        rows = metrics.list_pricing()
        if not rows:
            print("No pricing configured.")
            return
        print(f"{'Model':<40} {'Input $/1M':>12} {'Output $/1M':>13}  Updated")
        for r in rows:
            print(
                f"{r['model']:<40} {r['input_per_1m']:>12.4f}"
                f" {r['output_per_1m']:>13.4f}  {r['updated_at']}"
            )
    elif action == "set":
        if not args.model or args.input is None or args.output is None:
            print("Usage: icloud-image-labeler pricing set <model> --input <$> --output <$>")
            sys.exit(1)
        metrics.set_pricing(args.model, args.input, args.output)
        print(
            f"Set pricing for {args.model}: "
            f"input ${args.input}/1M, output ${args.output}/1M"
        )
    elif action == "delete":
        if not args.model:
            print("Usage: icloud-image-labeler pricing delete <model>")
            sys.exit(1)
        n = metrics.delete_pricing(args.model)
        if n:
            print(f"Deleted pricing for {args.model}")
        else:
            print(f"No pricing entry found for {args.model}")
            sys.exit(1)


def _metrics_cmd(args):
    action = args.metrics_action

    if action == "path":
        print(metrics.DB_PATH)
    elif action == "serve":
        import subprocess as sp
        from importlib.resources import as_file, files

        port = args.port or DEFAULT_DATASETTE_PORT
        dashboard_resource = files("labeler").joinpath("dashboard.yaml")
        with as_file(dashboard_resource) as dashboard_path:
            print(f"Starting Datasette on http://localhost:{port}")
            print(f"Dashboard:  http://localhost:{port}/-/dashboards/labeler")
            print(f"Database:   {metrics.DB_PATH}")
            sp.run(
                [
                    "datasette",
                    "serve",
                    metrics.DB_PATH,
                    "-p",
                    str(port),
                    "-m",
                    str(dashboard_path),
                ]
            )


def _build_run_parser(subparsers):
    """Create and configure the 'run' subparser."""
    run_parser = subparsers.add_parser("run", help="Process unprocessed media")
    run_parser.add_argument("--limit", type=int, default=None)
    run_parser.add_argument("--days", type=int, default=None)
    run_parser.add_argument("--to-days", type=int, default=None)
    run_parser.add_argument("--photo", action="store_true", default=None)
    run_parser.add_argument("--no-photo", dest="photo", action="store_false")
    run_parser.add_argument("--video", action="store_true", default=None)
    run_parser.add_argument("--no-video", dest="video", action="store_false")
    run_parser.add_argument(
        "--transcribe",
        action="store_true",
        default=None,
        help=(
            "Transcribe speech in videos with Whisper before labeling them"
            " (needs mlx-whisper)"
        ),
    )
    run_parser.add_argument("--no-transcribe", dest="transcribe", action="store_false")
    run_parser.add_argument(
        "--whisper-model",
        default=None,
        help="Whisper model for transcription (MLX format, e.g. a Hugging Face repo)",
    )
    run_parser.add_argument(
        "--whisper-languages",
        default=None,
        metavar="CODES",
        help=(
            "Comma-separated languages speech can be in, e.g. ar,en"
            " (empty = any language Whisper knows)"
        ),
    )
    run_parser.add_argument("--write", action="store_true", default=None)
    run_parser.add_argument("--dry-run", action="store_true", default=None)
    run_parser.add_argument("--base-url", default=None)
    run_parser.add_argument("--api-key", default=None)
    run_parser.add_argument("--model", default=None)
    run_parser.add_argument(
        "--server",
        action="append",
        default=None,
        metavar="URL|MODEL[|API_KEY[|THREADS]]",
        help=(
            "LLM backend to use. Repeat to distribute requests across"
            " multiple servers (round-robin). The optional THREADS field"
            " sets per-server concurrency."
        ),
    )
    run_parser.add_argument("--threads", type=int, default=None)
    run_parser.add_argument("--video-frames", type=int, default=None)
    run_parser.add_argument(
        "--video-frame-batch",
        type=int,
        default=None,
        help="Video frames per LLM request (0 = all frames in one request)",
    )
    run_parser.add_argument(
        "--uuid", nargs="+", default=None, help="Process specific photo UUIDs"
    )
    run_parser.add_argument("--loop", action="store_true", default=False)
    run_parser.add_argument(
        "--reindex",
        action="store_true",
        default=False,
        help="Reprocess items whose model tag (m:...) is missing or stale",
    )
    run_parser.add_argument("-v", "--verbose", action="store_true", default=False)
    return run_parser


def _build_parser():
    """Build CLI argument parser, set up logging from pre-parsed verbose flag."""
    # Pre-parse for verbose flag before full parsing
    pre = argparse.ArgumentParser(add_help=False)
    pre.add_argument("-v", "--verbose", action="store_true", default=False)
    known, _ = pre.parse_known_args()
    _setup_logging(verbose=known.verbose)

    parser = argparse.ArgumentParser(
        prog="icloud-image-labeler",
        description="Auto-label iCloud Photos using any OpenAI-compatible LLM",
    )
    parser.add_argument(
        "--version",
        action="version",
        version=f"%(prog)s {version('icloud-image-labeler')}",
    )
    subparsers = parser.add_subparsers(dest="command")

    subparsers.add_parser("init", help="Interactive first-run setup wizard")
    run_parser = _build_run_parser(subparsers)

    daemon_parser = subparsers.add_parser("daemon", help="Manage background daemon")
    daemon_parser.add_argument(
        "daemon_action",
        choices=["start", "stop", "restart", "status"],
    )

    config_parser = subparsers.add_parser("config", help="Manage configuration")
    config_parser.add_argument(
        "config_action",
        choices=["show", "set", "reset", "path"],
    )
    config_parser.add_argument("key", nargs="?", default=None)
    config_parser.add_argument("value", nargs="?", default=None)

    metrics_parser = subparsers.add_parser("metrics", help="View processing metrics")
    metrics_parser.add_argument(
        "metrics_action",
        choices=["path", "serve"],
    )
    metrics_parser.add_argument("--port", type=int, default=None)

    migrate_parser = subparsers.add_parser(
        "migrate", help="Update keywords already in the Photos library"
    )
    migrate_parser.add_argument(
        "migration",
        choices=["normalize-keywords", "lowercase-keywords", "redo-transcripts"],
    )
    migrate_parser.add_argument("--dry-run", action="store_true", default=False)
    migrate_parser.add_argument("--limit", type=int, default=None)

    pricing_parser = subparsers.add_parser(
        "pricing", help="Manage per-model token pricing for cost dashboards"
    )
    pricing_parser.add_argument(
        "pricing_action",
        choices=["list", "set", "delete"],
    )
    pricing_parser.add_argument(
        "model", nargs="?", default=None, help="Model name (e.g. google/gemma-4-e4b)"
    )
    pricing_parser.add_argument(
        "--input", type=float, default=None, help="USD per 1M input tokens"
    )
    pricing_parser.add_argument(
        "--output", type=float, default=None, help="USD per 1M output tokens"
    )

    return parser, run_parser


def main():
    """Parse CLI arguments and dispatch to the appropriate subcommand."""
    parser, run_parser = _build_parser()
    args = parser.parse_args()
    cfg = config.load_config()
    metrics.init_db()

    if args.command == "init":
        run_init()
        return

    if args.command is None or args.command == "run":
        install_signal_handlers()
        if args.command is None:
            args = run_parser.parse_args([])
        if not config.CONFIG_PATH.exists():
            print("No config found. Running setup wizard...\n")
            run_init()
            cfg = config.load_config()
        check_dependencies()
        _run(args, cfg)
    elif args.command == "daemon":
        _daemon_cmd(args)
    elif args.command == "config":
        _config_cmd(args, cfg)
    elif args.command == "metrics":
        _metrics_cmd(args)
    elif args.command == "migrate":
        _migrate_cmd(args)
    elif args.command == "pricing":
        _pricing_cmd(args)
