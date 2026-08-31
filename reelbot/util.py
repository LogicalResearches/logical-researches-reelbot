from __future__ import annotations

import hashlib
import json
import os
import re
import subprocess
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Iterable
from urllib.parse import urlsplit, urlunsplit


USER_AGENT = "LogicalResearchesReelBot/0.1 (+https://instagram.com/logical_researches)"


def slugify(value: str, max_length: int = 55) -> str:
    value = value.lower().strip()
    value = re.sub(r"[^a-z0-9]+", "-", value).strip("-")
    return (value[:max_length].rstrip("-") or "reel")


def canonical_url(value: str) -> str:
    parsed = urlsplit(value.strip())
    return urlunsplit((parsed.scheme.lower(), parsed.netloc.lower(), parsed.path.rstrip("/"), "", ""))


def url_fingerprint(value: str) -> str:
    return hashlib.sha256(canonical_url(value).encode("utf-8")).hexdigest()[:20]


def utc_now() -> datetime:
    return datetime.now(UTC)


def write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if hasattr(payload, "model_dump"):
        payload = payload.model_dump(mode="json")
    with path.open("w", encoding="utf-8") as handle:
        json.dump(payload, handle, indent=2, ensure_ascii=False)
        handle.write("\n")


def read_json(path: Path, default: Any = None) -> Any:
    if not path.exists():
        return default
    with path.open("r", encoding="utf-8") as handle:
        return json.load(handle)


def run(command: list[str], *, cwd: Path | None = None) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        command,
        cwd=cwd,
        check=True,
        text=True,
        capture_output=True,
    )


def domain_matches(host: str, allowed_domains: Iterable[str]) -> bool:
    host = host.lower().split(":", 1)[0]
    return any(host == item.lower() or host.endswith("." + item.lower()) for item in allowed_domains)


def clean_text(value: str) -> str:
    return re.sub(r"\s+", " ", value or "").strip()


def load_env_file(path: Path = Path(".env")) -> None:
    """Load a small KEY=VALUE file without overwriting real environment variables."""
    if not path.exists():
        return
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        if re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", key):
            os.environ.setdefault(key, value)

