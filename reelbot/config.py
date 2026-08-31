from __future__ import annotations

import os
from pathlib import Path
from typing import Any

import yaml


class ConfigError(RuntimeError):
    pass


class AppConfig:
    def __init__(self, data: dict[str, Any], path: Path):
        self.data = data
        self.path = path

    def section(self, name: str) -> dict[str, Any]:
        value = self.data.get(name)
        if not isinstance(value, dict):
            raise ConfigError(f"Missing or invalid '{name}' section in {self.path}")
        return value

    @property
    def page(self) -> dict[str, Any]:
        return self.section("page")

    @property
    def content(self) -> dict[str, Any]:
        return self.section("content")

    @property
    def visuals(self) -> dict[str, Any]:
        return self.section("visuals")

    @property
    def style(self) -> dict[str, Any]:
        return self.section("style")

    @property
    def ai(self) -> dict[str, Any]:
        values = dict(self.section("ai"))
        values["text_model"] = os.getenv("GEMINI_TEXT_MODEL", values.get("text_model"))
        values["tts_model"] = os.getenv("GEMINI_TTS_MODEL", values.get("tts_model"))
        values["voice"] = os.getenv("GEMINI_TTS_VOICE", values.get("voice", "Charon"))
        return values

    @property
    def instagram(self) -> dict[str, Any]:
        values = dict(self.section("instagram"))
        values["graph_api_version"] = os.getenv(
            "GRAPH_API_VERSION", values.get("graph_api_version", "v25.0")
        )
        return values

    @property
    def sources(self) -> list[dict[str, Any]]:
        values = self.data.get("sources", [])
        if not isinstance(values, list) or not values:
            raise ConfigError("At least one source is required")
        return values


def load_config(path: str | Path = "config.yaml") -> AppConfig:
    resolved = Path(path).expanduser().resolve()
    if not resolved.exists():
        raise ConfigError(f"Config not found: {resolved}")
    with resolved.open("r", encoding="utf-8") as handle:
        data = yaml.safe_load(handle)
    if not isinstance(data, dict):
        raise ConfigError(f"Invalid YAML object in {resolved}")
    return AppConfig(data, resolved)

