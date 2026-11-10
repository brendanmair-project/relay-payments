"""Ollama client (REL-25, ADR-0005, ADR-0010): one non-streaming `POST /api/generate` with a timeout.

Every failure raises `ModelUnavailable` with the `fallback_reason` stored when the rules explainer takes over:
`model_timeout`, `model_unreachable` (connection error) or `model_error` (any other bad reply).
"""

from typing import Protocol

import httpx

from app.explain.prompt import ANSWER_SCHEMA


class ModelUnavailable(Exception):
    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.reason = reason


class ModelClient(Protocol):
    """What the explainer needs from a model; tests inject a fake."""

    name: str

    def generate(self, prompt: str) -> str: ...


class OllamaClient:
    def __init__(
        self,
        url: str,
        model: str,
        timeout: float,
        transport: httpx.BaseTransport | None = None,
        schema: dict[str, object] | None = None,
    ) -> None:
        self.name = model
        self._url = url.rstrip("/") + "/api/generate"
        self._timeout = timeout
        self._transport = transport
        self._schema = schema if schema is not None else ANSWER_SCHEMA

    def with_schema(self, schema: dict[str, object]) -> "OllamaClient":
        """The same model and timeout answering in another JSON shape (the incident summary, REL-35)."""
        return OllamaClient(self._url.removesuffix("/api/generate"), self.name, self._timeout, self._transport, schema)

    def generate(self, prompt: str) -> str:
        payload = {"model": self.name, "prompt": prompt, "stream": False, "format": self._schema}
        try:
            with httpx.Client(timeout=self._timeout, transport=self._transport) as client:
                response = client.post(self._url, json=payload)
        except httpx.TimeoutException:
            raise ModelUnavailable("model_timeout") from None
        except httpx.TransportError:
            raise ModelUnavailable("model_unreachable") from None
        try:
            response.raise_for_status()
            text = response.json()["response"]
        except (httpx.HTTPStatusError, ValueError, KeyError, TypeError):
            raise ModelUnavailable("model_error") from None
        if not isinstance(text, str):
            raise ModelUnavailable("model_error")
        return text
