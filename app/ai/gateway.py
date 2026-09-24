"""Public AI Gateway for ScholarMind AI.

Application code should use this gateway instead of importing provider
implementations directly. Provider credentials stay server-side and are
resolved by AIRouter from encrypted admin settings or environment variables.
"""

from __future__ import annotations

from collections import defaultdict, deque
from dataclasses import dataclass
from threading import Lock
from time import monotonic

from flask import current_app

from .base import AIResponse
from .router import AIRouter


@dataclass(frozen=True)
class AIRequest:
    prompt: str
    system: str | None = None
    capability: str = "chat"
    provider: str | None = None
    user_id: int | None = None


class AIRateLimitError(RuntimeError):
    """Raised when a user exceeds the configured AI request limits."""


class AIGateway:
    """Single entry point for all server-side AI requests."""

    _lock = Lock()
    _requests: dict[int, deque[float]] = defaultdict(deque)
    _daily: dict[int, tuple[int, float]] = {}

    def __init__(self, router: AIRouter | None = None) -> None:
        self.router = router or AIRouter()

    @classmethod
    def _check_limits(cls, user_id: int | None) -> None:
        if user_id is None:
            return

        cfg = current_app.config
        rpm = max(1, int(cfg.get("AI_REQUESTS_PER_MINUTE", 20)))
        daily = max(1, int(cfg.get("AI_REQUESTS_PER_DAY", 200)))
        now = monotonic()

        with cls._lock:
            window = cls._requests[user_id]
            while window and now - window[0] >= 60:
                window.popleft()
            if len(window) >= rpm:
                raise AIRateLimitError("AI request rate limit exceeded. Please try again shortly.")

            day_count, day_started = cls._daily.get(user_id, (0, now))
            if now - day_started >= 86400:
                day_count, day_started = 0, now
            if day_count >= daily:
                raise AIRateLimitError("Daily AI usage limit reached. Please try again tomorrow.")

            window.append(now)
            cls._daily[user_id] = (day_count + 1, day_started)

    def complete(self, request: AIRequest) -> AIResponse:
        try:
            self._check_limits(request.user_id)
        except AIRateLimitError as exc:
            return AIResponse(
                text="",
                provider=request.provider or "gateway",
                model="gateway",
                success=False,
                error=str(exc),
            )

        if request.provider:
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
