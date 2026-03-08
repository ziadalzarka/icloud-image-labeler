import argparse
import json
import logging
import sys
import time

from labeler import config, daemon, metrics
from labeler.discovery import get_unprocessed_media
from labeler.processor import process_batch

logger = logging.getLogger("labeler")


def _setup_logging(verbose: bool = False):
    logging.basicConfig(
        level=logging.DEBUG if verbose else logging.INFO,
        format="%(asctime)s %(levelname)-7s [%(name)s] %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )
    # Keep third-party loggers at INFO to avoid dumping base64/HTTP bodies
    for name in ("httpx", "openai", "httpcore"):
        logging.getLogger(name).setLevel(logging.INFO)


def _run(args, cfg):
    """One-shot or loop processing."""
    # CLI flags override config
    base_url = args.base_url or cfg["base_url"]
    model = args.model or cfg["model"]
    limit = args.limit if args.limit is not None else cfg["limit_per_cycle"]
    days = args.days if args.days is not None else cfg["days"]
    to_days = args.to_days if args.to_days is not None else cfg["to_days"]
    threads = args.threads if args.threads is not None else cfg["threads"]
    video_frames = args.video_frames if args.video_frames is not None else cfg["video_frames"]
    photo = args.photo if args.photo is not None else cfg["photo"]
    video = args.video if args.video is not None else cfg["video"]
    write = cfg["write"]
    if args.write is True:
        write = True
    elif args.dry_run is True:
        write = False

    loop = args.loop
    poll_interval = cfg["poll_interval"]

    while True:
        items = get_unprocessed_media(
            limit=limit, days_back=days, to_days=to_days,
            photo=photo, video=video,
        )
        if items:
            process_batch(
                items, base_url=base_url, model=model,
                threads=threads, video_frames=video_frames,
                max_dimension=cfg["max_dimension"], write=write,
            )
        else:
            logger.info("No unprocessed media found.")

        if not loop:
            break
        logger.info(f"Sleeping {poll_interval}s until next cycle...")
        time.sleep(poll_interval)


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


def _metrics_cmd(args):
    action = args.metrics_action

    if action == "path":
        print(metrics.DB_PATH)
    elif action == "serve":
        import subprocess as sp
        port = args.port or 8001
        print(f"Starting Datasette on http://localhost:{port}")
        print(f"Database: {metrics.DB_PATH}")
        sp.run(["datasette", "serve", metrics.DB_PATH, "-p", str(port)])


def main():
    # Pre-parse for verbose flag before full parsing
    pre = argparse.ArgumentParser(add_help=False)
    pre.add_argument("-v", "--verbose", action="store_true", default=False)
    known, _ = pre.parse_known_args()
    _setup_logging(verbose=known.verbose)

    parser = argparse.ArgumentParser(
        prog="labeler",
        description="Auto-label iCloud Photos with a local LLM",
    )
    subparsers = parser.add_subparsers(dest="command")

    # run subcommand
    run_parser = subparsers.add_parser("run", help="Process unprocessed media")
    run_parser.add_argument("--limit", type=int, default=None)
    run_parser.add_argument("--days", type=int, default=None)
    run_parser.add_argument("--to-days", type=int, default=None)
    run_parser.add_argument("--photo", action="store_true", default=None)
    run_parser.add_argument("--no-photo", dest="photo", action="store_false")
    run_parser.add_argument("--video", action="store_true", default=None)
    run_parser.add_argument("--no-video", dest="video", action="store_false")
    run_parser.add_argument("--write", action="store_true", default=None)
    run_parser.add_argument("--dry-run", action="store_true", default=None)
    run_parser.add_argument("--base-url", default=None)
    run_parser.add_argument("--model", default=None)
    run_parser.add_argument("--threads", type=int, default=None)
    run_parser.add_argument("--video-frames", type=int, default=None)
    run_parser.add_argument("--loop", action="store_true", default=False)
    run_parser.add_argument("-v", "--verbose", action="store_true", default=False)

    # daemon subcommand
    daemon_parser = subparsers.add_parser("daemon", help="Manage background daemon")
    daemon_parser.add_argument(
        "daemon_action", choices=["start", "stop", "restart", "status"],
    )

    # config subcommand
    config_parser = subparsers.add_parser("config", help="Manage configuration")
    config_parser.add_argument(
        "config_action", choices=["show", "set", "reset", "path"],
    )
    config_parser.add_argument("key", nargs="?", default=None)
    config_parser.add_argument("value", nargs="?", default=None)

    # metrics subcommand
    metrics_parser = subparsers.add_parser("metrics", help="View processing metrics")
    metrics_parser.add_argument(
        "metrics_action", choices=["path", "serve"],
    )
    metrics_parser.add_argument("--port", type=int, default=None)

    args = parser.parse_args()
    cfg = config.load_config()
    metrics.init_db()

    if args.command is None or args.command == "run":
        if args.command is None:
            # Default to run with default args
            args = run_parser.parse_args([])
        _run(args, cfg)
    elif args.command == "daemon":
        _daemon_cmd(args)
    elif args.command == "config":
        _config_cmd(args, cfg)
    elif args.command == "metrics":
        _metrics_cmd(args)
