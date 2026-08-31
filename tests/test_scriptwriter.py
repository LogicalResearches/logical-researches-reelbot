from pathlib import Path

import pytest

from reelbot.config import load_config
from reelbot.models import ReelSegment
from reelbot.scriptwriter import ScriptValidationError, fallback_script, validate_script
from reelbot.sources import demo_article


ROOT = Path(__file__).resolve().parents[1]


def test_fallback_script_is_valid_and_source_grounded():
    config = load_config(ROOT / "config.yaml")
    article = demo_article()
    script = fallback_script(article, config)
    result = validate_script(script, article, config)
    assert result["status"] == "passed"
    assert len(script.segments) == 5
    assert "logical_researches" in script.narration


def test_validator_rejects_number_not_in_source():
    config = load_config(ROOT / "config.yaml")
    article = demo_article()
    script = fallback_script(article, config)
    first = script.segments[0]
    script.segments[0] = ReelSegment(
        onscreen_text=first.onscreen_text,
        voiceover=first.voiceover + " It happened 999 times.",
        visual_query=first.visual_query,
    )
    with pytest.raises(ScriptValidationError, match="Numbers absent"):
        validate_script(script, article, config)

