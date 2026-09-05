"""Anthropic Claude provider using the HTTP API."""

from __future__ import annotations

import json
import urllib.error
import urllib.request

from ..base import AIResponse, BaseAIProvider


class AnthropicProvider(BaseAIProvider):
    name = "anthropic"

    def __init__(self, api_key: str, model: str = "claude-3-5-sonnet-20241022") -> None:
        self.api_key = api_key
        self.model = model

    def is_available(self) -> bool:
        return bool(self.api_key)

    def complete(self, prompt: str, system: str | None = None) -> AIResponse:
        if not self.is_available():
            return AIResponse("", self.name, self.model, success=False, error="Anthropic API key is missing.")

        payload = {"model": self.model, "max_tokens": 2048, "messages": [{"role": "user", "content": prompt}]}
        if system:
            payload["system"] = system
        request = urllib.request.Request(
            "https://api.anthropic.com/v1/messages",
            data=json.dumps(payload).encode(),
            headers={
                "content-type": "application/json",
                "x-api-key": self.api_key,
                "anthropic-version": "2023-06-01",
            },
            method="POST",
        )
        try:
            with urllib.request.urlopen(request, timeout=60) as response:
                body = json.loads(response.read().decode())
            text = "".join(part.get("text", "") for part in body.get("content", []))
            return AIResponse(text, self.name, self.model)
        except Exception as exc:
            return AIResponse("", self.name, self.model, success=False, error=str(exc))