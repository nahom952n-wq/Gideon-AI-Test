"""Public AI Gateway for ScholarMind AI.

Application code should use this gateway instead of importing provider
implementations directly. Provider credentials stay server-side and are
resolved by AIRouter from encrypted admin settings or environment variables.
"""

from __future__ import annotations

from dataclasses import dataclass

from .base import AIResponse
from .router import AIRouter


@dataclass(frozen=True)
class AIRequest:
    prompt: str
    system: str | None = None
    capability: str = "chat"
    provider: str | None = None


class AIGateway:
    """Single entry point for all server-side AI requests."""

    def __init__(self, router: AIRouter | None = None) -> None:
        self.router = router or AIRouter()

    def complete(self, request: AIRequest) -> AIResponse:
        if request.provider:
            # Explicit provider selection still goes through AIRouter so that
            # credentials, availability, prompt validation, and fallbacks stay
            # centralized. Unknown/unconfigured providers are never accepted.
            self.router._init_providers()
            provider = self.router._providers.get(request.provider)
            if provider is None or not provider.is_available():
                return AIResponse(
                    text="",
                    provider=request.provider,
                    model="unknown",
                    success=False,
                    error=f"AI provider '{request.provider}' is not configured.",
                )
            prompt = self.router._validate_prompt(request.prompt)
            return provider.complete(prompt, system=request.system)

        return self.router.route_capability(
            request.capability,
            request.prompt,
            system=request.system,
        )


def get_ai_gateway() -> AIGateway:
    """Return a request-scoped gateway instance."""
    return AIGateway()
