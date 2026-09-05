"""
Abstract AI provider interface.

Every AI provider (Gemini, OpenAI, Anthropic, etc.) must implement this
protocol. The rest of the application only ever calls AIRouter — it never
imports a provider directly, so swapping providers requires no changes
outside this package.
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass


@dataclass
class AIResponse:
    """Standardised response from any AI provider."""

    text: str
    provider: str
    model: str
    prompt_tokens: int = 0
    completion_tokens: int = 0
    success: bool = True
    error: str | None = None


class BaseAIProvider(ABC):
    """Abstract base class all AI providers must implement."""

    name: str = "base"
    model: str = "unknown"

    @abstractmethod
    def complete(self, prompt: str, system: str | None = None) -> AIResponse:
        """
        Send a prompt and return a structured response.

        Args:
            prompt: The user-facing prompt text.
            system: Optional system/instruction preamble.

        Returns:
            AIResponse with text, provider, model, and token counts.
        """
        ...

    @abstractmethod
    def is_available(self) -> bool:
        """Return True if this provider is configured and reachable."""
        ...
