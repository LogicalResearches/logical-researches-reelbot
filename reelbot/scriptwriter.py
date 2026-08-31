from __future__ import annotations

import re
import unicodedata
from difflib import SequenceMatcher

from pydantic import ValidationError

from .ai import AIUnavailable, GeminiClient
from .config import AppConfig
from .models import Article, ClaimEvidence, ReelSegment, ScriptPayload, VisualCredit
from .util import clean_text


SCRIPT_SCHEMA = {
    "type": "object",
    "properties": {
        "headline": {"type": "string"},
        "cover_text": {"type": "string"},
        "segments": {
            "type": "array",
            "minItems": 5,
            "maxItems": 5,
            "items": {
                "type": "object",
                "properties": {
                    "onscreen_text": {"type": "string"},
                    "voiceover": {"type": "string"},
                    "visual_query": {"type": "string"},
                },
                "required": ["onscreen_text", "voiceover", "visual_query"],
                "additionalProperties": False,
            },
        },
        "caption_body": {"type": "string"},
        "hashtags": {"type": "array", "minItems": 3, "maxItems": 12, "items": {"type": "string"}},
        "claims": {
            "type": "array",
            "minItems": 1,
            "maxItems": 8,
            "items": {
                "type": "object",
                "properties": {"claim": {"type": "string"}, "evidence": {"type": "string"}},
                "required": ["claim", "evidence"],
                "additionalProperties": False,
            },
        },
    },
    "required": ["headline", "cover_text", "segments", "caption_body", "hashtags", "claims"],
    "additionalProperties": False,
}


class ScriptValidationError(RuntimeError):
    pass


def _sentences(text: str) -> list[str]:
    return [clean_text(item) for item in re.split(r"(?<=[.!?])\s+", clean_text(text)) if len(item.split()) >= 5]


def _shorten(text: str, words: int) -> str:
    values = text.split()
    result = " ".join(values[:words])
    if result and result[-1] not in ".!?":
        result += "."
    return result


def _visual_topic(title: str) -> str:
    ascii_title = unicodedata.normalize("NFKD", title).encode("ascii", "ignore").decode("ascii")
    tokens = re.findall(r"[A-Za-z0-9]+", ascii_title)
    stop = {
        "a", "an", "and", "are", "at", "can", "dark", "for", "from", "how", "in", "into",
        "is", "it", "launches", "new", "of", "on", "past", "research", "reveals", "science",
        "seeking", "sees", "study", "the", "this", "to", "type", "universe", "with", "your",
        "nasa", "esa", "mit",
    }
    useful = [token for token in tokens if token.lower() not in stop]
    chosen = useful[:6] if len(useful) >= 2 else tokens[:6]
    return " ".join(chosen) or "science discovery"


def fallback_script(article: Article, config: AppConfig) -> ScriptPayload:
    sentences = _sentences(f"{article.summary} {article.body}")
    while len(sentences) < 4:
        sentences.append("The source explains why this research matters and what scientists can study next.")
    topic = _visual_topic(article.title)
    cover_text = " ".join(article.title.split()[:10])
    if len(cover_text) > 70:
        cover_text = cover_text[:70].rsplit(" ", 1)[0].rstrip(" ,:;-")
    segments = [
        ReelSegment(
            onscreen_text="This changes how we see it",
            voiceover=_shorten(f"Here is a discovery worth knowing: {article.title}.", 19),
            visual_query=topic,
        ),
        ReelSegment(
            onscreen_text="What researchers found",
            voiceover=_shorten(sentences[0], 24),
            visual_query=topic + " research",
        ),
        ReelSegment(
            onscreen_text="The key detail",
            voiceover=_shorten(sentences[1], 24),
            visual_query=topic + " science",
        ),
        ReelSegment(
            onscreen_text="Why it matters",
            voiceover=_shorten(sentences[2], 24),
            visual_query=topic + " technology",
        ),
        ReelSegment(
            onscreen_text="Evidence first. Curiosity always.",
            voiceover=_shorten(
                f"The full source is {article.source_name}. {config.page['call_to_action']}", 24
            ),
            visual_query=topic,
        ),
    ]
    return ScriptPayload(
        headline=article.title[:100],
        cover_text=cover_text,
        segments=segments,
        caption_body=(
            f"{article.summary}\n\nThis reel summarizes the linked institutional source; "
            "it does not add claims beyond that source."
        )[:1200],
        hashtags=["#Science", "#Research", "#DidYouKnow", "#Innovation", "#LogicalResearches"],
        claims=[ClaimEvidence(claim=sentences[0][:240], evidence=sentences[0][:400])],
    )


def _number_tokens(text: str) -> set[str]:
    return {item.replace(",", "").lower() for item in re.findall(r"(?<!\w)\d[\d,.]*(?:%|\s?(?:km|m|cm|kg|years?|days?|hours?))?", text.lower())}


def _evidence_supported(evidence: str, source: str) -> bool:
    evidence_clean = clean_text(evidence).lower()
    source_clean = clean_text(source).lower()
    if evidence_clean in source_clean:
        return True
    words = [word for word in re.findall(r"[a-z]{4,}", evidence_clean) if word not in {"that", "with", "from", "this", "were", "have"}]
    overlap = sum(1 for word in set(words) if word in source_clean)
    ratio = SequenceMatcher(None, evidence_clean[:300], source_clean[:3000]).ratio()
    return overlap >= min(5, max(3, len(set(words)) // 2)) or ratio >= 0.28


def validate_script(script: ScriptPayload, article: Article, config: AppConfig) -> dict[str, object]:
    expected_segments = int(config.content.get("segment_count", 5))
    if len(script.segments) != expected_segments:
        raise ScriptValidationError(f"Expected {expected_segments} segments, got {len(script.segments)}")
    words = len(script.narration.split())
    minimum = int(config.content.get("min_narration_words", 72))
    maximum = int(config.content.get("max_narration_words", 115))
    if not minimum <= words <= maximum:
        raise ScriptValidationError(f"Narration has {words} words; expected {minimum}-{maximum}")

    source_text = f"{article.title} {article.summary} {article.body}"
    unsupported_numbers = sorted(_number_tokens(script.narration) - _number_tokens(source_text))
    if unsupported_numbers:
        raise ScriptValidationError("Numbers absent from source: " + ", ".join(unsupported_numbers))
    unsupported_evidence = [item.evidence for item in script.claims if not _evidence_supported(item.evidence, source_text)]
    if unsupported_evidence:
        raise ScriptValidationError("Claim evidence could not be matched to the source")

    risky_phrases = ("guaranteed", "miracle cure", "scientists are hiding", "100% proven")
    found_risks = [phrase for phrase in risky_phrases if phrase in script.narration.lower()]
    if found_risks:
        raise ScriptValidationError("Risky language: " + ", ".join(found_risks))
    return {
        "status": "passed",
        "narration_words": words,
        "unsupported_numbers": [],
        "claim_count": len(script.claims),
    }


def generate_script(article: Article, config: AppConfig, ai: GeminiClient) -> tuple[ScriptPayload, dict[str, object]]:
    if not ai.available:
        fallback = fallback_script(article, config)
        return fallback, validate_script(fallback, article, config)

    avoid_topics = ", ".join(config.content.get("avoid_topics", []))
    prompt = f"""
Create a factual 5-part Instagram Reel script for @{config.page['handle']}.

NON-NEGOTIABLE RULES
- Use only the SOURCE MATERIAL below. Never add a fact from memory.
- Write 72 to 115 spoken words total and exactly 5 segments.
- Hook quickly, explain the finding, give one key detail, explain why it matters, and end with the page CTA.
- Each onscreen_text has at most 10 words. Each visual_query is concrete, neutral, and 3-8 words.
- Avoid exaggeration, fear, certainty beyond the source, medical advice, and these topics: {avoid_topics}.
- Every factual spoken claim needs an evidence entry. Evidence must be a short exact excerpt or very close paraphrase from the source material.
- Do not invent numbers. If a number is not in the source, omit it.
- Caption body must summarize carefully and say when the finding is preliminary.
- Use global, simple English. No emojis in the spoken script.
- Return JSON only, following the schema.

PAGE CTA: {config.page['call_to_action']}
SOURCE: {article.source_name}
TITLE: {article.title}
URL: {article.url}
SUMMARY: {article.summary}
SOURCE MATERIAL:
{article.body}
""".strip()

    last_error: Exception | None = None
    for attempt in range(2):
        try:
            attempt_prompt = prompt
            if last_error:
                attempt_prompt += f"\n\nYour previous draft failed validation: {last_error}. Correct it."
            result = ai.generate_json(prompt=attempt_prompt, schema=SCRIPT_SCHEMA, temperature=0.25)
            script = ScriptPayload.model_validate(result)
            return script, validate_script(script, article, config)
        except (AIUnavailable, ValidationError, ScriptValidationError, KeyError, TypeError, ValueError) as exc:
            last_error = exc

    if config.ai.get("use_fallback_if_unavailable", True):
        fallback = fallback_script(article, config)
        validation = validate_script(fallback, article, config)
        validation["fallback_reason"] = str(last_error)
        return fallback, validation
    raise ScriptValidationError(str(last_error))


def compose_caption(
    script: ScriptPayload,
    article: Article,
    credits: list[VisualCredit],
    config: AppConfig,
) -> str:
    source_date = article.published_at.date().isoformat() if article.published_at else "date on source page"
    parts = [
        script.caption_body.strip(),
        f"Source: {article.source_name}, {source_date}\n{article.url}",
    ]
    if credits:
        compact = "\n".join(f"• {credit.compact()}" for credit in credits[:4])
        parts.append("Visual credits (Wikimedia Commons):\n" + compact)
    parts.append(" ".join(script.hashtags))
    caption = "\n\n".join(parts)
    if len(caption) > 2200:
        # Keep the actual source and hashtags; trim long visual-credit text first.
        parts = [parts[0][:900], parts[1], "Visuals: Wikimedia Commons; credits saved in draft.json.", parts[-1]]
        caption = "\n\n".join(parts)
    return caption[:2200]
