"""OllamaClient error-path tests."""

import pytest

from backend.services.ocr_client import OllamaClient, OllamaError


def _response(status: int = 200, body: dict | None = None, raise_json: bool = False):
    from requests import HTTPError

    class _Resp:
        def raise_for_status(self):
            if status >= 400:
                raise HTTPError(f"HTTP {status}")

        def json(self):
            if raise_json:
                raise ValueError("no json")
            return body or {}

    return _Resp()


def test_generate_success(monkeypatch):
    import backend.services.ocr_client as mod

    def fake_post(url, json=None, timeout=None):
        return _response(body={"response": "hello world"})

    monkeypatch.setattr(mod, "requests", type("Fake", (), {"post": staticmethod(fake_post)}))
    client = OllamaClient("http://localhost:11434")
    assert client.generate("m", "p", "b64") == "hello world"


def test_generate_request_failure_raises_ollama_error(monkeypatch):
    import backend.services.ocr_client as mod

    class _Boom:
        class RequestException(Exception):
            pass

        @staticmethod
        def post(*a, **k):
            raise _Boom.RequestException("connection refused")

    monkeypatch.setattr(mod, "requests", _Boom)
    client = OllamaClient("http://localhost:11434")
    with pytest.raises(OllamaError, match="connection refused"):
        client.generate("m", "p", "b64")


def test_generate_http_error_raises_ollama_error(monkeypatch):
    import backend.services.ocr_client as mod
    from requests import RequestException

    class _FakeRequests:
        @staticmethod
        def post(*a, **k):
            return _response(status=500)

    _FakeRequests.RequestException = RequestException
    monkeypatch.setattr(mod, "requests", _FakeRequests)
    client = OllamaClient("http://localhost:11434")
    with pytest.raises(OllamaError, match="Ollama request failed"):
        client.generate("m", "p", "b64")


def test_generate_non_json_response_raises_ollama_error(monkeypatch):
    import backend.services.ocr_client as mod
    from requests import RequestException

    class _FakeRequests:
        @staticmethod
        def post(*a, **k):
            return _response(body=None, raise_json=True)

    _FakeRequests.RequestException = RequestException
    monkeypatch.setattr(mod, "requests", _FakeRequests)
    client = OllamaClient("http://localhost:11434")
    with pytest.raises(OllamaError, match="non-JSON"):
        client.generate("m", "p", "b64")


def test_generate_missing_response_field_yields_empty(monkeypatch):
    import backend.services.ocr_client as mod

    def fake_post(url, json=None, timeout=None):
        return _response(body={"something_else": "x"})

    monkeypatch.setattr(mod.requests, "post", fake_post, raising=False)
    client = OllamaClient("http://localhost:11434")
    assert client.generate("m", "p", "b64") == ""
