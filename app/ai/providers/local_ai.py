"""
LocalAI provider — communicates with any locally running OpenAI-compatible endpoint.

Compatible with: Ollama, LM Studio, llama.cpp server, vLLM, and any other
server that implements the OpenAI Chat Completions API format.

Configuration (in .env):
    LOCAL_AI_URL   — base URL of the local server (e.g. http://localhost:11434/v1)
    LOCAL_AI_MODEL — model name to request    (e.g. qwen2.5, llama3, mistral)

The application never needs to know which specific model is running — it is
fully abstracted behind this provider.
"""

import json
import logging
import urllib.request
import urllib.error
from ..base import BaseAIProvider, AIResponse

log = logging.getLogger("scholarmind.ai")


class LocalAIProvider(BaseAIProvider):
    """
    OpenAI-compatible local inference provider.

    Uses only the stdlib (urllib) to avoid adding dependencies. Any model
    served via an OpenAI-compatible /chat/completions endpoint is supported.
    """

    name = "local"

    def __init__(self, base_url: str, model: str) -> None:
        self.base_url = base_url.rstrip("/")
        self.model = model

    def is_available(self) -> bool:
        """
        Check if the local server is reachable.

        Performs a lightweight HEAD-like GET to the models endpoint.
        """
        try:
            url = f"{self.base_url}/models"
            req = urllib.request.Request(url, method="GET")
            req.add_header("Accept", "application/json")
            with urllib.request.urlopen(req, timeout=3) as resp:
                return resp.status == 200
        except Exception:
            return False

    def complete(self, prompt: str, system: str | None = None) -> AIResponse:
        if not self.base_url or not self.model:
            return AIResponse(
                text="",
                provider=self.name,
                model=self.model or "unknown",
                success=False,
                error="LocalAI not configured. Set LOCAL_AI_URL and LOCAL_AI_MODEL in .env.",
            )

        messages = []
        if system:
            messages.append({"role": "system", "content": system})
        messages.append({"role": "user", "content": prompt})

        payload = json.dumps({
            "model": self.model,
            "messages": messages,
            "temperature": 0.1,
            "stream": False,
        }).encode("utf-8")

        try:
            req = urllib.request.Request(
                f"{self.base_url}/chat/completions",
                data=payload,
                method="POST",
            )
            req.add_header("Content-Type", "application/json")
            req.add_header("Accept", "application/json")

            with urllib.request.urlopen(req, timeout=60) as resp:
                body = json.loads(resp.read().decode("utf-8"))

            text = body["choices"][0]["message"]["content"] or ""
            usage = body.get("usage", {})
            log.info(
                "LocalAI completion (model=%s, chars=%d, prompt_tokens=%s)",
                self.model,
                len(text),
                usage.get("prompt_tokens", "?"),
            )
            return AIResponse(
                text=text,
                provider=self.name,
                model=self.model,
                prompt_tokens=usage.get("prompt_tokens", 0),
                completion_tokens=usage.get("completion_tokens", 0),
            )

        except urllib.error.URLError as exc:
            msg = f"LocalAI unreachable ({self.base_url}): {exc}"
            log.warning(msg)
            return AIResponse(
                text="", provider=self.name, model=self.model, success=False, error=msg
            )
        except (KeyError, IndexError, json.JSONDecodeError) as exc:
            msg = f"LocalAI response parse error: {exc}"
            log.error(msg)
            return AIResponse(
                text="", provider=self.name, model=self.model, success=False, error=msg
            )
        except Exception as exc:
            log.error("LocalAI completion failed: %s", exc)
            return AIResponse(
                text="", provider=self.name, model=self.model, success=False, error=str(exc)
            )
