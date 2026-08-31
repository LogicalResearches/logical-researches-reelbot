from __future__ import annotations

from pathlib import Path

from .util import read_json, url_fingerprint, utc_now, write_json


class HistoryStore:
    def __init__(self, path: Path):
        self.path = path
        data = read_json(path, default={"items": []})
        self.items: list[dict[str, str]] = data.get("items", []) if isinstance(data, dict) else []

    def contains(self, url: str) -> bool:
        fingerprint = url_fingerprint(url)
        return any(item.get("fingerprint") == fingerprint for item in self.items)

    def add(self, url: str, title: str) -> None:
        if self.contains(url):
            return
        self.items.append(
            {
                "fingerprint": url_fingerprint(url),
                "url": url,
                "title": title,
                "created_at": utc_now().isoformat(),
            }
        )
        self.items = self.items[-180:]
        write_json(self.path, {"items": self.items})

