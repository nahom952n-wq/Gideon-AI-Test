"""OpenAI provider through the OpenAI-compatible HTTP API."""

from __future__ import annotations

import json
import urllib.request

from ..base import BaseAIProvider, AIResponse


class OpenAIProvider(BaseAIProvider):
    """OpenAI chat completions without requiring an SDK-specific dependency."""

    name = "openai"

    def __init__(self, api_key: str, model: str = "gpt-4o-mini") -> None:
        self.api_key = api_key
        self.model = model

    def is_available(self) -> bool:
        return bool(self.api_key)

    def complete(self, prompt: str, system: str | None = None) -> AIResponse:
        if not self.is_available():
            return AIResponse("", self.name, self.model, success=False, error="OpenAI API key is missing.")
        messages = []
        if system:
            messages.append({"role": "system", "content": system})
        messages.append({"role": "user", "content": prompt})
        request = urllib.request.Request(
            "https://api.openai.com/v1/chat/completions",
            data=json.dumps({"model": self.model, "messages": messages}).encode(),
            headers={
                "content-type": "application/json",
                "authorization": f"Bearer {self.api_key}",
            },
            method="POST",
        )
        try:
            with urllib.request.urlopen(request, timeout=60) as response:
                body = json.loads(response.read().decode())
            text = body["choices"][0]["message"]["content"] or ""
            usage = body.get("usage", {})
            return AIResponse(
                text=text,
                provider=self.name,
                model=self.model,
                prompt_tokens=usage.get("prompt_tokens", 0),
                completion_tokens=usage.get("completion_tokens", 0),
            )
        except Exception as exc:
            return AIResponse("", self.name, self.model, success=False, error=str(exc))
