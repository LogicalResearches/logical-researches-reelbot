from __future__ import annotations

import json

from .ai import AIUnavailable, GeminiClient
from .models import FeedCandidate


SELECTION_SCHEMA = {
    "type": "object",
    "properties": {
        "selected_index": {"type": "integer", "minimum": 0},
        "reason": {"type": "string"},
        "risk": {"type": "string", "enum": ["low", "medium", "high"]},
    },
    "required": ["selected_index", "reason", "risk"],
    "additionalProperties": False,
}


def select_candidate(candidates: list[FeedCandidate], ai: GeminiClient) -> FeedCandidate:
    shortlist = candidates[:12]
    if not shortlist:
        raise ValueError("No candidates to select")
    if not ai.available:
        return shortlist[0]

    payload = [
        {
            "index": index,
            "title": item.title,
            "summary": item.summary[:500],
            "source": item.source_name,
            "published_at": item.published_at.isoformat() if item.published_at else None,
            "base_score": item.heuristic_score,
        }
        for index, item in enumerate(shortlist)
    ]
    prompt = f"""
You are the cautious research editor for an Instagram page about science, AI, space,
engineering and surprising evidence-based discoveries. Choose exactly one story that is:
recent, visually explainable, useful or surprising, understandable globally, and supported
by the institution named as its source. Reject administrative announcements, medical advice,
partisan politics, tragedy bait, and claims that sound sensational but lack evidence.

Return the index, a one-sentence reason, and factual-risk level. Prefer low risk. The base score
is only a hint and must not override editorial safety.

CANDIDATES:
{json.dumps(payload, ensure_ascii=False)}
""".strip()
    try:
        result = ai.generate_json(prompt=prompt, schema=SELECTION_SCHEMA, temperature=0.1)
        index = int(result["selected_index"])
        if result.get("risk") == "high" or index < 0 or index >= len(shortlist):
            return shortlist[0]
        return shortlist[index]
    except (AIUnavailable, KeyError, ValueError, TypeError):
        return shortlist[0]

