from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field, HttpUrl, field_validator


class FeedCandidate(BaseModel):
    title: str
    url: HttpUrl
    summary: str = ""
    published_at: datetime | None = None
    source_name: str
    trust_weight: float = 1.0
    heuristic_score: float = 0.0


class Article(BaseModel):
    title: str
    url: HttpUrl
    source_name: str
    published_at: datetime | None = None
    summary: str = ""
    body: str
    author: str = ""


class ClaimEvidence(BaseModel):
    claim: str = Field(min_length=5, max_length=240)
    evidence: str = Field(min_length=5, max_length=400)


class ReelSegment(BaseModel):
    onscreen_text: str = Field(min_length=2, max_length=90)
    voiceover: str = Field(min_length=3, max_length=480)
    visual_query: str = Field(min_length=2, max_length=100)

    @field_validator("onscreen_text")
    @classmethod
    def concise_onscreen_text(cls, value: str) -> str:
        if len(value.split()) > 14:
            raise ValueError("onscreen_text must contain at most 14 words")
        return value.strip()


class ScriptPayload(BaseModel):
    headline: str = Field(min_length=4, max_length=100)
    cover_text: str = Field(min_length=4, max_length=70)
    segments: list[ReelSegment]
    caption_body: str = Field(min_length=20, max_length=1200)
    hashtags: list[str] = Field(min_length=3, max_length=12)
    claims: list[ClaimEvidence] = Field(min_length=1, max_length=8)

    @field_validator("cover_text")
    @classmethod
    def concise_cover(cls, value: str) -> str:
        if len(value.split()) > 10:
            raise ValueError("cover_text must contain at most 10 words")
        return value.strip()

    @field_validator("hashtags")
    @classmethod
    def normalize_hashtags(cls, values: list[str]) -> list[str]:
        cleaned: list[str] = []
        for value in values:
            tag = "#" + "".join(ch for ch in value.lstrip("#") if ch.isalnum() or ch == "_")
            if len(tag) > 1 and tag.lower() not in {item.lower() for item in cleaned}:
                cleaned.append(tag)
        return cleaned[:12]

    @property
    def narration(self) -> str:
        return " ".join(segment.voiceover.strip() for segment in self.segments)


class VisualCredit(BaseModel):
    title: str
    creator: str = "Unknown creator"
    license: str
    page_url: str

    def compact(self) -> str:
        creator = " ".join(self.creator.split())
        title = " ".join(self.title.replace("File:", "").split())
        return f"{title} — {creator} ({self.license}) {self.page_url}"


class VisualAsset(BaseModel):
    path: Path
    query: str
    credit: VisualCredit | None = None


class ReelDraft(BaseModel):
    draft_id: str
    created_at: datetime
    article: Article
    script: ScriptPayload
    caption: str
    media_path: str
    cover_path: str
    duration_seconds: float
    width: int
    height: int
    visual_credits: list[VisualCredit] = Field(default_factory=list)
    validation: dict[str, Any] = Field(default_factory=dict)
