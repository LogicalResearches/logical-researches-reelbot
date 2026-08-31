from __future__ import annotations

import json
import math
import re
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import UTC, datetime, timedelta
from html import unescape
from urllib.parse import urlsplit

import feedparser
import requests
from bs4 import BeautifulSoup
from dateutil import parser as date_parser

from .config import AppConfig
from .history import HistoryStore
from .models import Article, FeedCandidate
from .util import USER_AGENT, clean_text, domain_matches


class SourceError(RuntimeError):
    pass


def _parse_date(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        parsed = date_parser.parse(value)
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=UTC)
        return parsed.astimezone(UTC)
    except (ValueError, TypeError, OverflowError):
        return None


def _strip_html(value: str) -> str:
    return clean_text(BeautifulSoup(unescape(value or ""), "html.parser").get_text(" "))


def _heuristic_score(
    candidate: FeedCandidate,
    preferred_keywords: list[str],
    now: datetime,
) -> float:
    text = f"{candidate.title} {candidate.summary}".lower()
    keyword_points = sum(1.25 for keyword in preferred_keywords if keyword.lower() in text)
    title_bonus = min(2.0, len(candidate.title.split()) / 10)
    novelty_bonus = 1.2 if any(token in text for token in ("first", "new", "discover", "reveals", "unexpected")) else 0
    admin_penalty = 3.8 if any(
        token in text
        for token in (
            "appoints",
            "director",
            "awards contract",
            "media accreditation",
            "coverage for",
            "launch coverage",
            "burn begins",
            "burn complete",
            "flying on its own",
            "ribbon-cutting",
            "panorama showcasing",
        )
    ) else 0
    if candidate.published_at:
        age_days = max(0.0, (now - candidate.published_at).total_seconds() / 86400)
        recency = max(0.0, 3.5 - math.log2(age_days + 1))
    else:
        recency = 0.5
    return round((keyword_points + title_bonus + novelty_bonus + recency - admin_penalty) * candidate.trust_weight, 3)


def fetch_candidates(config: AppConfig, history: HistoryStore) -> list[FeedCandidate]:
    now = datetime.now(UTC)
    max_age = timedelta(days=int(config.content.get("max_candidate_age_days", 10)))
    per_feed = int(config.content.get("candidate_limit_per_feed", 8))
    preferred = list(config.content.get("preferred_keywords", []))
    def fetch_one(source: dict) -> tuple[list[FeedCandidate], str | None]:
        try:
            response = requests.get(
                source["feed_url"],
                timeout=25,
                headers={"User-Agent": USER_AGENT, "Accept": "application/rss+xml, application/xml, text/xml"},
            )
            response.raise_for_status()
            parsed = feedparser.parse(response.content)
            if parsed.bozo and not parsed.entries:
                raise SourceError(str(parsed.bozo_exception))
            source_candidates: list[FeedCandidate] = []
            count = 0
            for entry in parsed.entries:
                url = clean_text(entry.get("link", ""))
                title = _strip_html(entry.get("title", ""))
                if not url or not title or history.contains(url):
                    continue
                if not domain_matches(urlsplit(url).hostname or "", source.get("allowed_domains", [])):
                    continue
                published = _parse_date(entry.get("published") or entry.get("updated"))
                if published and now - published > max_age:
                    continue
                candidate = FeedCandidate(
                    title=title,
                    url=url,
                    summary=_strip_html(entry.get("summary") or entry.get("description") or "")[:1200],
                    published_at=published,
                    source_name=source["name"],
                    trust_weight=float(source.get("trust_weight", 1.0)),
                )
                candidate.heuristic_score = _heuristic_score(candidate, preferred, now)
                source_candidates.append(candidate)
                count += 1
                if count >= per_feed:
                    break
            return source_candidates, None
        except Exception as exc:  # Continue when one institution temporarily fails.
            return [], f"{source.get('name', 'source')}: {exc}"

    candidates: list[FeedCandidate] = []
    errors: list[str] = []
    with ThreadPoolExecutor(max_workers=min(8, len(config.sources))) as pool:
        futures = [pool.submit(fetch_one, source) for source in config.sources]
        for future in as_completed(futures):
            found, error = future.result()
            candidates.extend(found)
            if error:
                errors.append(error)

    if not candidates:
        joined = "; ".join(errors) or "No recent unused feed entries were found"
        raise SourceError(joined)
    return sorted(candidates, key=lambda item: item.heuristic_score, reverse=True)


def _extract_json_ld(soup: BeautifulSoup) -> tuple[str, str]:
    body = ""
    author = ""
    for node in soup.select('script[type="application/ld+json"]'):
        try:
            payload = json.loads(node.string or "{}")
        except (json.JSONDecodeError, TypeError):
            continue
        objects = payload if isinstance(payload, list) else [payload]
        for obj in objects:
            if isinstance(obj, dict) and "@graph" in obj:
                objects.extend(item for item in obj["@graph"] if isinstance(item, dict))
            if not isinstance(obj, dict):
                continue
            if not body and isinstance(obj.get("articleBody"), str):
                body = clean_text(obj["articleBody"])
            raw_author = obj.get("author")
            if not author and isinstance(raw_author, dict):
                author = clean_text(raw_author.get("name", ""))
            elif not author and isinstance(raw_author, list):
                names = [clean_text(item.get("name", "")) for item in raw_author if isinstance(item, dict)]
                author = ", ".join(name for name in names if name)
    return body, author


def extract_article(candidate: FeedCandidate) -> Article:
    response = requests.get(
        str(candidate.url),
        timeout=30,
        headers={"User-Agent": USER_AGENT, "Accept": "text/html,application/xhtml+xml"},
    )
    response.raise_for_status()
    soup = BeautifulSoup(response.text, "html.parser")
    for node in soup.select("script:not([type='application/ld+json']), style, nav, footer, header, aside, form"):
        node.decompose()

    body, author = _extract_json_ld(soup)
    if len(body) < 700:
        selectors = (
            "article p",
            "main p",
            "[itemprop='articleBody'] p",
            ".article-body p",
            ".entry-content p",
        )
        paragraphs: list[str] = []
        for selector in selectors:
            found = [clean_text(node.get_text(" ")) for node in soup.select(selector)]
            found = [text for text in found if len(text) >= 55]
            if sum(len(text) for text in found) > sum(len(text) for text in paragraphs):
                paragraphs = found
        body = "\n\n".join(paragraphs)

    if len(body) < 300:
        body = candidate.summary
    if len(body) < 160:
        raise SourceError(f"Could not extract enough article text from {candidate.url}")

    description_node = soup.select_one('meta[name="description"], meta[property="og:description"]')
    summary = candidate.summary
    if description_node and description_node.get("content"):
        summary = clean_text(description_node.get("content", ""))
    return Article(
        title=candidate.title,
        url=candidate.url,
        source_name=candidate.source_name,
        published_at=candidate.published_at,
        summary=summary[:1500],
        body=body[:24000],
        author=author,
    )


def article_from_url(url: str, source_name: str = "Manual source") -> Article:
    candidate = FeedCandidate(title="Article", url=url, source_name=source_name)
    response = requests.get(url, timeout=30, headers={"User-Agent": USER_AGENT})
    response.raise_for_status()
    soup = BeautifulSoup(response.text, "html.parser")
    title_node = soup.select_one('meta[property="og:title"]')
    title = clean_text(title_node.get("content", "")) if title_node else ""
    if not title and soup.title:
        title = clean_text(soup.title.get_text(" "))
    candidate.title = title or "Research update"
    return extract_article(candidate)


def demo_article() -> Article:
    return Article(
        title="How the James Webb Space Telescope sees the hidden universe",
        url="https://science.nasa.gov/mission/webb/",
        source_name="NASA Science",
        summary=(
            "The James Webb Space Telescope studies the universe mainly in infrared light, "
            "helping astronomers examine distant galaxies, stars, planets, and dusty regions."
        ),
        body=(
            "The James Webb Space Telescope is a large space-based observatory optimized for "
            "infrared wavelengths. Infrared observations let astronomers study light from very "
            "distant galaxies whose wavelengths have been stretched by the expansion of the universe. "
            "They can also look through some clouds of cosmic dust that block visible light. Webb's "
            "science includes studying the early universe, how galaxies evolve, the life cycles of "
            "stars, and the atmospheres of planets beyond our solar system. The observatory uses a "
            "segmented primary mirror and a sunshield to keep its instruments cold. Webb is an "
            "international program led by NASA with ESA and CSA."
        ),
        author="NASA",
    )
