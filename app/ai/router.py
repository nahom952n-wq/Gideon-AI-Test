"""
AI Router — dispatches tasks to the correct provider.

Two routing modes (both backward-compatible):

  route(task, prompt)
      Legacy task-based routing kept for backward compatibility.
      task ∈ {"extraction", "reasoning", "chat"}

  route_capability(capability, prompt)
      Capability-based routing with local-first / cloud-fallback logic.
      capability ∈ {"summarization", "structured_extraction", "reasoning",
                    "translation", "classification", "vision_analysis",
                    "chat", "ocr", ...}

Routing rules:
  1. Look up the capability → provider in CAPABILITY_MAP (from config).
  2. If the designated provider is "local", attempt local inference first.
  3. Evaluate confidence in the local response.
  4. If confidence ≥ LOCAL_AI_CONFIDENCE_THRESHOLD, return the local result.
  5. Otherwise route to the cloud provider for this capability (fallback).

Provider names ("local", "gemini", "openai") are never hardcoded in business
logic — only here and in config.
"""

import json
import logging
from flask import current_app
from ..config import DEFAULT_GEMINI_MODEL
from .base import BaseAIProvider, AIResponse
from .providers.gemini import GeminiProvider
from .providers.openai_provider import OpenAIProvider
from .providers.local_ai import LocalAIProvider
from .providers.anthropic_provider import AnthropicProvider
from .providers.grok_provider import GrokProvider

log = logging.getLogger("scholarmind.ai")


class AIRouter:
    """Routes AI tasks/capabilities to the appropriate provider."""

    # Legacy task constants — kept for backward compatibility
    TASK_EXTRACTION = "extraction"
    TASK_REASONING = "reasoning"
    TASK_CHAT = "chat"

    def __init__(self) -> None:
        self._providers: dict[str, BaseAIProvider] = {}
        self._task_map: dict[str, str] = {}

    # ------------------------------------------------------------------
    # Provider initialisation
    # ------------------------------------------------------------------

    def _init_providers(self) -> None:
        """Initialise providers from the database first, then environment config.

        The router is reused by long-lived services, so rebuild the lightweight
        provider objects on each request. This makes changes from Settings take
        effect without restarting Gideon and avoids retaining stale API keys.
        """
        cfg = current_app.config
        active = cfg.get("ACTIVE_AI_PROVIDER", "gemini")
        self._providers = {}
        try:
            from ..models.api_key import ApiKeySetting
        except Exception:
            ApiKeySetting = None

        def stored(provider: str, key_name: str, env_name: str, default=None):
            value = ApiKeySetting.get(provider, key_name) if ApiKeySetting else None
            return value or cfg.get(env_name, default)

        gemini_key = stored("gemini", "api_key", "GEMINI_API_KEY")
        gemini_model = stored("gemini", "model", "GEMINI_MODEL", DEFAULT_GEMINI_MODEL)
        if "gemini" not in self._providers and gemini_key:
            self._providers["gemini"] = GeminiProvider(
                api_key=gemini_key,
                model=gemini_model,
            )

        openai_key = stored("openai", "api_key", "OPENAI_API_KEY")
        openai_model = stored("openai", "model", "OPENAI_MODEL", "gpt-4o-mini")
        if "openai" not in self._providers and openai_key:
            self._providers["openai"] = OpenAIProvider(
                api_key=openai_key,
                model=openai_model,
            )

        local_url = stored("local_ai", "api_key", "LOCAL_AI_URL")
        local_model = stored("local_ai", "model", "LOCAL_AI_MODEL", "qwen2.5")
        if "local" not in self._providers and local_url:
            self._providers["local"] = LocalAIProvider(
                base_url=local_url,
                model=local_model,
            )

        anthropic_key = stored("anthropic", "api_key", "ANTHROPIC_API_KEY")
        anthropic_model = stored(
            "anthropic", "model", "ANTHROPIC_MODEL", "claude-3-5-sonnet-20241022"
        )
        if "anthropic" not in self._providers and anthropic_key:
            self._providers["anthropic"] = AnthropicProvider(
                api_key=anthropic_key, model=anthropic_model
            )

        grok_key = stored("grok", "api_key", "GROK_API_KEY")
        grok_model = stored("grok", "model", "GROK_MODEL", "grok-2")
        if "grok" not in self._providers and grok_key:
            self._providers["grok"] = GrokProvider(api_key=grok_key, model=grok_model)

        # Legacy task map — maps the three old task names to the active provider
        self._task_map = {
            self.TASK_EXTRACTION: active,
            self.TASK_REASONING: active,
            self.TASK_CHAT: active,
        }

    # ------------------------------------------------------------------
    # Legacy route() — unchanged API, full backward compatibility
    # ------------------------------------------------------------------

    def route(
        self,
        task: str,
        prompt: str,
        system: str | None = None,
    ) -> AIResponse:
        """
        Route a task to its designated provider (legacy interface).

        Args:
            task: One of TASK_EXTRACTION, TASK_REASONING, TASK_CHAT.
            prompt: The prompt to send.
            system: Optional system instruction.

        Returns:
            AIResponse from whichever provider handled the task.
        """
        self._init_providers()

        provider_name = self._task_map.get(task, "gemini")
        provider = self._providers.get(provider_name)

        if not provider or not provider.is_available():
            log.warning(
                "Provider '%s' unavailable for task '%s'. Trying fallbacks.",
                provider_name,
                task,
            )
            for fallback_name, fallback in self._providers.items():
                if fallback.is_available():
                    log.info("Falling back to provider '%s'", fallback_name)
                    provider = fallback
                    break
            else:
                return AIResponse(
                    text="",
                    provider="none",
                    model="none",
                    success=False,
                    error=(
                        "No AI providers are available. Add one in Settings → "
                        "AI Providers & API Keys or configure .env."
                    ),
                )

        log.info("Routing task '%s' to provider '%s'", task, provider.name)
        return provider.complete(prompt, system=system)

    # ------------------------------------------------------------------
    # Capability-based routing — local-first with cloud fallback
    # ------------------------------------------------------------------

    def route_capability(
        self,
        capability: str,
        prompt: str,
        system: str | None = None,
    ) -> AIResponse:
        """
        Route a request by capability with local-first, cloud-fallback logic.

        Algorithm:
          1. Look up capability in CAPABILITY_MAP to get the designated provider.
          2. If provider is "local": try local first, evaluate confidence.
             - If confidence ≥ threshold → return local result.
             - Otherwise → fall through to cloud provider for this capability.
          3. Try cloud provider for this capability.
          4. If cloud also fails → try any remaining available provider.

        Args:
            capability: Capability key (e.g. "structured_extraction", "reasoning").
            prompt: The prompt text.
            system: Optional system instruction.

        Returns:
            AIResponse — annotated with which provider actually ran it.
        """
        self._init_providers()
        cfg = current_app.config
        capability_map: dict = dict(cfg.get("CAPABILITY_MAP", {}))
        threshold: float = cfg.get("LOCAL_AI_CONFIDENCE_THRESHOLD", 0.60)

        # Settings stores routing overrides in the same encrypted settings table.
        # Invalid JSON or unknown providers are ignored safely and fall back to
        # the environment/default capability map.
        try:
            from ..models.api_key import ApiKeySetting
            saved_map = ApiKeySetting.get("__routing__", "capability_map")
            if saved_map:
                decoded = json.loads(saved_map)
                if isinstance(decoded, dict):
                    capability_map.update(decoded)
        except Exception as exc:
            log.warning("Could not load saved capability routing: %s", exc)

        valid_provider_names = set(self._providers)
        designated = capability_map.get(capability, "gemini")
        if designated not in valid_provider_names:
            log.warning("Unknown provider '%s' for capability '%s'; using fallback", designated, capability)
            designated = "gemini"
        log.info("Capability '%s' designated to provider '%s'", capability, designated)

        # --- Step 1: Try local if designated or if local is primary ---
        if designated == "local":
            local_provider = self._providers.get("local")
            if local_provider and local_provider.is_available():
                local_resp = local_provider.complete(prompt, system=system)
                confidence = self._evaluate_confidence(local_resp, capability)
                log.info(
                    "LocalAI response for capability='%s': success=%s confidence=%.2f",
                    capability, local_resp.success, confidence,
                )
                if local_resp.success and confidence >= threshold:
                    return local_resp
                log.info(
                    "LocalAI confidence %.2f < threshold %.2f — routing to cloud fallback",
                    confidence, threshold,
                )
            else:
                log.info("LocalAI not available — routing directly to cloud for '%s'", capability)

        # --- Step 2: Use designated cloud provider ---
        cloud_provider = self._providers.get(designated) if designated != "local" else None
        if not cloud_provider:
            # Pick the best cloud provider as fallback
            for name in ("gemini", "openai"):
                p = self._providers.get(name)
                if p and p.is_available():
                    cloud_provider = p
                    log.info("Using cloud fallback provider '%s' for capability '%s'", name, capability)
                    break

        if cloud_provider and cloud_provider.is_available():
            response = cloud_provider.complete(prompt, system=system)
            if response.success:
                return response
            log.warning("Provider '%s' failed for capability '%s'; trying fallbacks", cloud_provider.name, capability)

        # --- Step 3: Last resort — any available provider ---
        for _name, provider in self._providers.items():
            if provider.is_available():
                log.warning(
                    "Last-resort routing for capability '%s' to provider '%s'",
                    capability, provider.name,
                )
                response = provider.complete(prompt, system=system)
                if response.success:
                    return response

        return AIResponse(
            text="",
            provider="none",
            model="none",
            success=False,
            error=(
                f"No providers available for capability '{capability}'. "
                "Add a provider in Settings → AI Providers & API Keys or configure .env."
            ),
        )

    # ------------------------------------------------------------------
    # Confidence evaluation
    # ------------------------------------------------------------------

    def _evaluate_confidence(self, response: AIResponse, capability: str) -> float:
        """
        Estimate how confident we are in a provider's response.

        Returns:
            Float 0.0–1.0. Higher = more confident.

        Strategy:
          - Failed / empty responses → 0.0
          - For structured_extraction: parse JSON and read the "confidence" field.
          - For other capabilities: heuristic based on response length and absence of
            error/refusal phrases.
        """
        if not response.success or not response.text:
            return 0.0

        text = response.text.strip()

        if capability == "structured_extraction":
            # Try to read the model's own confidence field from the JSON
            try:
                cleaned = text
                if cleaned.startswith("```"):
                    lines = cleaned.splitlines()
                    cleaned = "\n".join(lines[1:-1] if lines[-1] == "```" else lines[1:])
                data = json.loads(cleaned)
                declared = float(data.get("confidence", 0.0))
                return min(1.0, max(0.0, declared))
            except (json.JSONDecodeError, TypeError, ValueError):
                # Could not parse → low confidence, let cloud handle it
                return 0.3

        # Generic heuristic for other capabilities
        refusal_phrases = [
            "i cannot", "i can't", "i'm unable", "i don't know",
            "as an ai", "i apologize", "i'm sorry",
        ]
        lower = text.lower()
        if any(phrase in lower for phrase in refusal_phrases):
            return 0.2

        # Length-based proxy: longer substantive answers → higher confidence
        if len(text) > 500:
            return 0.85
        if len(text) > 100:
            return 0.75
        if len(text) > 20:
            return 0.60
        return 0.35
