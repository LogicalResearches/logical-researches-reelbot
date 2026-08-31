from __future__ import annotations

import argparse
import json
import os
import shutil
import sys
from pathlib import Path

import requests

from .config import load_config
from .instagram import InstagramPublisher
from .models import ReelDraft
from .pipeline import generate_reel
from .render import validate_reel
from .util import load_env_file


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="reelbot", description="Source-grounded research-to-Reel automation")
    parser.add_argument("--config", default="config.yaml", help="Path to config.yaml")
    sub = parser.add_subparsers(dest="command", required=True)

    generate = sub.add_parser("generate", help="Research and generate a new Reel draft")
    generate.add_argument("--output", default="site")
    generate.add_argument("--work-dir", default="work")
    generate.add_argument("--history", default="site/history.json")
    generate.add_argument("--topic-url", default=None)
    generate.add_argument("--offline-visuals", action="store_true")

    demo = sub.add_parser("demo", help="Render a completely offline sample Reel")
    demo.add_argument("--output", default="demo_output")
    demo.add_argument("--work-dir", default="work")

    validate = sub.add_parser("validate", help="Validate an MP4 before publishing")
    validate.add_argument("reel")

    publish = sub.add_parser("publish", help="Publish an already reviewed draft")
    publish.add_argument("--draft", required=True)
    publish.add_argument("--video-url", required=True)
    publish.add_argument("--dry-run", action="store_true")

    current = sub.add_parser("publish-current", help="Publish draft.json from a Pages base URL")
    current.add_argument("--base-url", required=True)
    current.add_argument("--dry-run", action="store_true")

    doctor = sub.add_parser("doctor", help="Check the free-tool and account setup")
    doctor.add_argument("--online", action="store_true", help="Also verify Meta credentials online")
    return parser


def _print(payload: object) -> None:
    print(json.dumps(payload, indent=2, ensure_ascii=False, default=str))


def _publish(draft: ReelDraft, video_url: str, config_path: str, dry_run: bool) -> None:
    if dry_run:
        _print(
            {
                "status": "dry-run",
                "draft_id": draft.draft_id,
                "video_url": video_url,
                "caption_characters": len(draft.caption),
            }
        )
        return
    result = InstagramPublisher(load_config(config_path)).publish(video_url, draft.caption)
    _print(
        {
            "status": "published",
            "draft_id": draft.draft_id,
            "container_id": result.container_id,
            "media_id": result.media_id,
            "permalink": result.permalink,
        }
    )


def main(argv: list[str] | None = None) -> int:
    load_env_file()
    parser = _parser()
    args = parser.parse_args(argv)
    try:
        config = load_config(args.config)
        if args.command in {"generate", "demo"}:
            output = Path(args.output).resolve()
            work = Path(args.work_dir).resolve()
            draft = generate_reel(
                config=config,
                output_dir=output,
                work_root=work,
                history_path=(Path(args.history).resolve() if args.command == "generate" else output / "history.json"),
                topic_url=(args.topic_url if args.command == "generate" else None),
                demo=args.command == "demo",
                offline_visuals=(args.offline_visuals if args.command == "generate" else True),
            )
            _print(
                {
                    "status": "generated",
                    "draft_id": draft.draft_id,
                    "reel": str(output / draft.media_path),
                    "preview": str(output / "index.html"),
                    "source": str(draft.article.url),
                    "duration_seconds": draft.duration_seconds,
                }
            )
        elif args.command == "validate":
            _print(validate_reel(Path(args.reel).resolve()))
        elif args.command == "publish":
            draft = ReelDraft.model_validate_json(Path(args.draft).read_text(encoding="utf-8"))
            _publish(draft, args.video_url, args.config, args.dry_run)
        elif args.command == "publish-current":
            base = args.base_url.rstrip("/") + "/"
            response = requests.get(base + "draft.json", timeout=30)
            response.raise_for_status()
            draft = ReelDraft.model_validate(response.json())
            _publish(draft, base + draft.media_path, args.config, args.dry_run)
        elif args.command == "doctor":
            report = {
                "ffmpeg": shutil.which("ffmpeg") or "missing",
                "ffprobe": shutil.which("ffprobe") or "missing",
                "gemini_key": "configured" if os.getenv("GEMINI_API_KEY") else "missing (offline fallback works)",
                "instagram_user_id": "configured" if os.getenv("INSTAGRAM_USER_ID") else "missing",
                "instagram_access_token": "configured" if os.getenv("INSTAGRAM_ACCESS_TOKEN") else "missing",
                "graph_api_version": config.instagram["graph_api_version"],
            }
            if args.online:
                report["instagram_account"] = InstagramPublisher(config).account_status()
            _print(report)
        return 0
    except Exception as exc:
        print(f"reelbot error: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
