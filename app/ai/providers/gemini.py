"""
Google Gemini AI provider.

Wraps the google-generativeai SDK behind the BaseAIProvider interface so
all Gemini-specific code stays isolated here. To add another provider,
create a new file in this directory and register it in router.py.
"""

import logging
from ...config import DEFAULT_GEMINI_MODEL, DEPRECATED_GEMINI_MODELS
from ..base import BaseAIProvider, AIResponse

log = logging.getLogger("scholarmind.ai")


class GeminiProvider(BaseAIProvider):
    """Google Gemini via google-generativeai SDK."""

    name = "gemini"

    def __init__(self, api_key: str, model: str = DEFAULT_GEMINI_MODEL) -> None:
        self.api_key = api_key
        self.model = (
            DEFAULT_GEMINI_MODEL if model in DEPRECATED_GEMINI_MODELS else model
        )
        self._client = None
        self._configure()

    def _configure(self) -> None:
        try:
            import google.generativeai as genai

            genai.configure(api_key=self.api_key)
            self._client = genai.GenerativeModel(self.model)
            log.info("Gemini provider configured (model=%s)", self.model)
        except ImportError:
            log.error("google-generativeai not installed. Run: pip install google-generativeai")
            self._client = None
        except Exception as e:
            log.error("Failed to configure Gemini: %s", e)
            self._client = None

    def is_available(self) -> bool:
        return self._client is not None and bool(self.api_key)

    def complete(self, prompt: str, system: str | None = None) -> AIResponse:
        if not self.is_available():
            return AIResponse(
                text="",
                provider=self.name,
                model=self.model,
                success=False,
                error="Gemini provider not available. Check GEMINI_API_KEY.",
            )

        full_prompt = f"{system}\n\n{prompt}" if system else prompt

        try:
            response = self._client.generate_content(full_prompt)
            text = response.text or ""
            log.info(
                "Gemini completion successful (model=%s, chars=%d)",
                self.model,
                len(text),
            )
            return AIResponse(text=text, provider=self.name, model=self.model)
        except Exception as e:
            log.error("Gemini completion failed: %s", e)
            return AIResponse(
                text="",
                provider=self.name,
                model=self.model,
                success=False,
                error=str(e),
            )
