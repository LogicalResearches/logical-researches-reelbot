from __future__ import annotations

import hashlib
import html
import re
import unicodedata
from pathlib import Path
from typing import Any

import requests
from bs4 import BeautifulSoup
from PIL import Image, ImageDraw

from .config import AppConfig
from .models import ScriptPayload, VisualAsset, VisualCredit
from .util import USER_AGENT, clean_text


COMMONS_API = "https://commons.wikimedia.org/w/api.php"


def _normalize_query(query: str) -> str:
    value = unicodedata.normalize("NFKD", query).encode("ascii", "ignore").decode("ascii")
    tokens = re.findall(r"[A-Za-z0-9]+", value)
    generic = {"image", "photo", "research", "science", "technology", "visual"}
    useful = [token for token in tokens if token.lower() not in generic]
    return " ".join((useful or tokens)[:7]) or "science discovery"


def _metadata_text(metadata: dict[str, Any], name: str) -> str:
    value = metadata.get(name, {})
    if isinstance(value, dict):
        value = value.get("value", "")
    return clean_text(BeautifulSoup(html.unescape(str(value or "")), "html.parser").get_text(" "))


def _license_allowed(value: str, accepted: list[str]) -> bool:
    normalized = re.sub(r"[_-]+", " ", value.lower())
    if re.search(r"\b(?:nc|nd)\b", normalized):
        return False
    return any(re.sub(r"[_-]+", " ", item.lower()) in normalized for item in accepted)


def _commons_results(query: str) -> list[dict[str, Any]]:
    query = _normalize_query(query)
    response = requests.get(
        COMMONS_API,
        params={
            "action": "query",
            "format": "json",
            "formatversion": "2",
            "generator": "search",
            "gsrsearch": f"{query} filetype:bitmap",
            "gsrnamespace": 6,
            "gsrlimit": 18,
            "prop": "imageinfo",
            "iiprop": "url|mime|extmetadata",
            "iiurlwidth": 1600,
            "origin": "*",
        },
        timeout=30,
        headers={"User-Agent": USER_AGENT},
    )
    response.raise_for_status()
    return response.json().get("query", {}).get("pages", [])


def _download_commons_asset(
    query: str,
    directory: Path,
    accepted: list[str],
    used_pages: set[int],
) -> VisualAsset | None:
    query_words = {word.lower() for word in _normalize_query(query).split() if len(word) > 2}

    def relevance(item: dict[str, Any]) -> tuple[int, int]:
        title = _normalize_query(str(item.get("title", ""))).lower()
        overlap = sum(1 for word in query_words if word in title)
        phrase_bonus = 4 if _normalize_query(query).lower() in title else 0
        return overlap + phrase_bonus, -len(title)

    for item in sorted(_commons_results(query), key=relevance, reverse=True):
        page_id = int(item.get("pageid", 0))
        image_info = (item.get("imageinfo") or [{}])[0]
        mime = image_info.get("mime", "")
        metadata = image_info.get("extmetadata") or {}
        license_name = _metadata_text(metadata, "LicenseShortName") or _metadata_text(metadata, "UsageTerms")
        if page_id in used_pages or mime not in {"image/jpeg", "image/png", "image/webp"}:
            continue
        if not _license_allowed(license_name, accepted):
            continue
        download_url = image_info.get("thumburl") or image_info.get("url")
        if not download_url:
            continue
        try:
            response = requests.get(download_url, timeout=35, headers={"User-Agent": USER_AGENT})
            response.raise_for_status()
            suffix = {"image/png": ".png", "image/webp": ".webp"}.get(mime, ".jpg")
            target = directory / f"commons-{page_id}{suffix}"
            target.write_bytes(response.content)
            with Image.open(target) as image:
                image.verify()
                if image.width < 640 or image.height < 480:
                    target.unlink(missing_ok=True)
                    continue
            used_pages.add(page_id)
            title = item.get("title", f"Wikimedia file {page_id}")
            creator = _metadata_text(metadata, "Artist") or _metadata_text(metadata, "Credit") or "Unknown creator"
            creator = creator[:140]
            page_url = image_info.get("descriptionurl") or f"https://commons.wikimedia.org/?curid={page_id}"
            return VisualAsset(
                path=target,
                query=query,
                credit=VisualCredit(
                    title=title[:160],
                    creator=creator,
                    license=license_name[:80],
                    page_url=page_url,
                ),
            )
        except (requests.RequestException, OSError, ValueError):
            continue
    return None


def _procedural_visual(query: str, directory: Path, index: int) -> VisualAsset:
    digest = hashlib.sha256(query.encode("utf-8")).digest()
    colors = [
        (digest[0] // 3, 22 + digest[1] // 5, 55 + digest[2] // 3),
        (20 + digest[3] // 4, 45 + digest[4] // 4, 80 + digest[5] // 2),
        (15, 125 + digest[6] // 3, 150 + digest[7] // 3),
    ]
    width, height = 1080, 1920
    image = Image.new("RGB", (width, height), colors[0])
    draw = ImageDraw.Draw(image, "RGBA")
    for y in range(height):
        ratio = y / max(1, height - 1)
        color = tuple(int(colors[0][channel] * (1 - ratio) + colors[1][channel] * ratio) for channel in range(3))
        draw.line((0, y, width, y), fill=color + (255,))
    for ring in range(16):
        radius = 90 + ring * 70
        x = (digest[(ring + 8) % len(digest)] / 255) * width
        y = ((ring * 113 + digest[ring % len(digest)] * 3) % height)
        draw.ellipse((x - radius, y - radius, x + radius, y + radius), outline=colors[2] + (35,), width=8)
    target = directory / f"procedural-{index}.jpg"
    image.save(target, quality=92)
    return VisualAsset(path=target, query=query)


def collect_visuals(
    script: ScriptPayload,
    config: AppConfig,
    directory: Path,
    *,
    offline: bool = False,
) -> list[VisualAsset]:
    directory.mkdir(parents=True, exist_ok=True)
    accepted = list(config.visuals.get("accepted_licenses", []))
    max_downloads = int(config.visuals.get("max_downloads", 4))
    unique_queries: list[str] = []
    for segment in script.segments:
        query = _normalize_query(segment.visual_query)
        if query.lower() not in {value.lower() for value in unique_queries}:
            unique_queries.append(query)
    assets: list[VisualAsset] = []
    used_pages: set[int] = set()
    for index, query in enumerate(unique_queries[:max_downloads]):
        asset = None
        if not offline:
            try:
                asset = _download_commons_asset(query, directory, accepted, used_pages)
            except requests.RequestException:
                asset = None
        assets.append(asset or _procedural_visual(query, directory, index))
    if not assets:
        assets.append(_procedural_visual("science discovery", directory, 0))
    return assets
