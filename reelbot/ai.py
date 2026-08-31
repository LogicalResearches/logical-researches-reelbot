from __future__ import annotations

import base64
import json
import os
import wave
from pathlib import Path
from typing import Any

from .config import AppConfig


class AIUnavailable(RuntimeError):
    pass


class GeminiClient:
    def __init__(self, config: AppConfig):
        self.config = config
        self.api_key = os.getenv("GEMINI_API_KEY", "").strip()
        self._client: Any = None

    @property
    def available(self) -> bool:
        return bool(self.api_key)

    @property
    def client(self) -> Any:
        if not self.api_key:
            raise AIUnavailable("GEMINI_API_KEY is not set")
        if self._client is None:
            try:
                from google import genai
            except ImportError as exc:
                raise AIUnavailable("google-genai is not installed") from exc
            self._client = genai.Client(api_key=self.api_key)
        return self._client

    def generate_json(
        self,
        *,
        prompt: str,
        schema: dict[str, Any],
        temperature: float = 0.2,
    ) -> dict[str, Any]:
        if not self.available:
            raise AIUnavailable("GEMINI_API_KEY is not set")
        model = self.config.ai["text_model"]
        try:
            interaction = self.client.interactions.create(
                model=model,
                input=prompt,
                response_format={"type": "text", "mime_type": "application/json", "schema": schema},
                generation_config={"temperature": temperature},
            )
            return json.loads(interaction.output_text)
        except Exception as interaction_error:
            # Compatibility path for older google-genai versions.
            try:
                from google.genai import types

                response = self.client.models.generate_content(
                    model=model,
                    contents=prompt,
                    config=types.GenerateContentConfig(
                        temperature=temperature,
                        response_mime_type="application/json",
                        response_json_schema=schema,
                    ),
                )
                return json.loads(response.text)
            except Exception:
                raise interaction_error

    def text_to_speech(self, text: str, output: Path) -> None:
        if not self.available:
            raise AIUnavailable("GEMINI_API_KEY is not set")
        interaction = self.client.interactions.create(
            model=self.config.ai["tts_model"],
            input=(
                "Read the exact script below in an energetic, intelligent documentary style. "
                "Use clear global English, a warm confident tone, natural pauses, and a slightly "
                "fast social-video pace. Do not add or remove words.\n\n" + text
            ),
            response_format={"type": "audio"},
            generation_config={"speech_config": [{"voice": self.config.ai["voice"]}]},
        )
        raw = interaction.output_audio.data
        pcm = base64.b64decode(raw) if isinstance(raw, str) else bytes(raw)
        output.parent.mkdir(parents=True, exist_ok=True)
        with wave.open(str(output), "wb") as handle:
            handle.setnchannels(1)
            handle.setsampwidth(2)
            handle.setframerate(24000)
            handle.writeframes(pcm)
