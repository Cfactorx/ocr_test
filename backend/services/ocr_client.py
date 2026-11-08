"""Synchronous Ollama HTTP client, isolated so OCRService stays testable.

All blocking I/O lives in this class; OCRService runs it via
``asyncio.to_thread``.
"""

from __future__ import annotations

import requests


class OllamaError(RuntimeError):
    """Raised when the Ollama endpoint is unreachable or returns no text."""


class OllamaClient:
    def __init__(self, url: str, timeout: int = 120) -> None:
        self.url = url
        self.timeout = timeout

    def generate(self, model: str, prompt: str, image_b64: str) -> str:
        payload = {
            "model": model,
            "prompt": prompt,
            "images": [image_b64],
            "stream": False,
        }
        try:
            response = requests.post(self.url, json=payload, timeout=self.timeout)
            response.raise_for_status()
        except requests.RequestException as exc:
            raise OllamaError(f"Ollama request failed (model={model}): {exc}") from exc
        try:
            data = response.json()
        except ValueError as exc:
            raise OllamaError(f"Ollama returned a non-JSON response (model={model})") from exc
        return str(data.get("response", "")).strip()
