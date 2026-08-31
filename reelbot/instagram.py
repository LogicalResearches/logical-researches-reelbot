from __future__ import annotations

import os
import time
from dataclasses import dataclass
from urllib.parse import urlsplit

import requests

from .config import AppConfig


class InstagramError(RuntimeError):
    pass


@dataclass
class PublishResult:
    container_id: str
    media_id: str
    permalink: str | None = None


class InstagramPublisher:
    def __init__(self, config: AppConfig, session: requests.Session | None = None):
        self.config = config
        self.user_id = os.getenv("INSTAGRAM_USER_ID", "").strip()
        self.token = os.getenv("INSTAGRAM_ACCESS_TOKEN", "").strip()
        self.session = session or requests.Session()
        version = config.instagram["graph_api_version"].strip("/")
        self.base = f"https://graph.facebook.com/{version}"

    def _require_credentials(self) -> None:
        missing = [
            name
            for name, value in (
                ("INSTAGRAM_USER_ID", self.user_id),
                ("INSTAGRAM_ACCESS_TOKEN", self.token),
            )
            if not value
        ]
        if missing:
            raise InstagramError("Missing secret(s): " + ", ".join(missing))

    @staticmethod
    def _validate_video_url(value: str) -> None:
        parsed = urlsplit(value)
        if parsed.scheme != "https" or not parsed.netloc:
            raise InstagramError("Instagram requires a publicly reachable HTTPS video URL")
        if not parsed.path.lower().endswith(".mp4"):
            raise InstagramError("The public media URL must end in .mp4")

    def _json(self, response: requests.Response) -> dict:
        try:
            payload = response.json()
        except ValueError as exc:
            raise InstagramError(f"Meta returned non-JSON HTTP {response.status_code}") from exc
        if response.status_code >= 400 or "error" in payload:
            error = payload.get("error", {})
            message = error.get("message") or str(payload)
            code = error.get("code")
            raise InstagramError(f"Meta API error {code or response.status_code}: {message}")
        return payload

    def create_reel_container(self, video_url: str, caption: str) -> str:
        self._require_credentials()
        self._validate_video_url(video_url)
        if len(caption) > 2200:
            raise InstagramError("Caption exceeds 2,200 characters")
        response = self.session.post(
            f"{self.base}/{self.user_id}/media",
            data={
                "media_type": "REELS",
                "video_url": video_url,
                "caption": caption,
                "share_to_feed": str(bool(self.config.instagram.get("share_to_feed", True))).lower(),
                "access_token": self.token,
            },
            timeout=40,
        )
        payload = self._json(response)
        container_id = payload.get("id")
        if not container_id:
            raise InstagramError("Meta did not return a Reel container ID")
        return str(container_id)

    def wait_until_ready(self, container_id: str) -> None:
        interval = int(self.config.instagram.get("poll_interval_seconds", 6))
        timeout = int(self.config.instagram.get("publish_timeout_seconds", 300))
        deadline = time.monotonic() + timeout
        last_status = "UNKNOWN"
        while time.monotonic() < deadline:
            response = self.session.get(
                f"{self.base}/{container_id}",
                params={"fields": "status_code,status", "access_token": self.token},
                timeout=30,
            )
            payload = self._json(response)
            last_status = str(payload.get("status_code") or payload.get("status") or "UNKNOWN").upper()
            if last_status == "FINISHED":
                return
            if last_status in {"ERROR", "EXPIRED"}:
                raise InstagramError(f"Meta could not process the Reel container: {last_status}")
            time.sleep(max(2, interval))
        raise InstagramError(f"Timed out waiting for Reel processing; last status: {last_status}")

    def publish_container(self, container_id: str) -> str:
        response = self.session.post(
            f"{self.base}/{self.user_id}/media_publish",
            data={"creation_id": container_id, "access_token": self.token},
            timeout=40,
        )
        payload = self._json(response)
        media_id = payload.get("id")
        if not media_id:
            raise InstagramError("Meta did not return a published media ID")
        return str(media_id)

    def get_permalink(self, media_id: str) -> str | None:
        response = self.session.get(
            f"{self.base}/{media_id}",
            params={"fields": "permalink", "access_token": self.token},
            timeout=30,
        )
        try:
            return self._json(response).get("permalink")
        except InstagramError:
            return None

    def account_status(self) -> dict:
        self._require_credentials()
        response = self.session.get(
            f"{self.base}/{self.user_id}",
            params={
                "fields": "id,username,account_type,media_count",
                "access_token": self.token,
            },
            timeout=30,
        )
        payload = self._json(response)
        return {
            "id": payload.get("id"),
            "username": payload.get("username"),
            "account_type": payload.get("account_type"),
            "media_count": payload.get("media_count"),
        }

    def publish(self, video_url: str, caption: str) -> PublishResult:
        container_id = self.create_reel_container(video_url, caption)
        self.wait_until_ready(container_id)
        media_id = self.publish_container(container_id)
        return PublishResult(
            container_id=container_id,
            media_id=media_id,
            permalink=self.get_permalink(media_id),
        )
