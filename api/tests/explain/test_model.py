"""REL-25.3: the Ollama client calls POST /api/generate with a timeout and names why it could not answer."""

import json

import httpx
import pytest

from app.config import Settings
from app.explain.model import ModelUnavailable, OllamaClient


def client_with(transport: httpx.MockTransport) -> OllamaClient:
    return OllamaClient("http://ollama.test:11434", "granite3.3:2b", 2.5, transport=transport)


def test_posts_a_non_streaming_json_request_and_returns_the_response_text() -> None:
    seen: list[httpx.Request] = []

    def handle(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(200, json={"response": '{"text": "ok"}', "done": True})

    result = client_with(httpx.MockTransport(handle)).generate("the prompt")
    assert result == '{"text": "ok"}'
    request = seen[0]
    assert request.method == "POST"
    assert str(request.url) == "http://ollama.test:11434/api/generate"
    body = json.loads(request.content)
    assert body["model"] == "granite3.3:2b"
    assert body["prompt"] == "the prompt"
    assert body["stream"] is False
    assert isinstance(body["format"], dict)


def test_name_is_the_model() -> None:
    assert client_with(httpx.MockTransport(lambda r: httpx.Response(200, json={}))).name == "granite3.3:2b"


def test_timeout_is_model_timeout() -> None:
    def handle(request: httpx.Request) -> httpx.Response:
        raise httpx.ReadTimeout("slow", request=request)

    with pytest.raises(ModelUnavailable) as caught:
        client_with(httpx.MockTransport(handle)).generate("p")
    assert caught.value.reason == "model_timeout"


def test_connection_error_is_model_unreachable() -> None:
    def handle(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("refused", request=request)

    with pytest.raises(ModelUnavailable) as caught:
        client_with(httpx.MockTransport(handle)).generate("p")
    assert caught.value.reason == "model_unreachable"


@pytest.mark.parametrize(
    "response",
    [httpx.Response(500, text="boom"), httpx.Response(200, text="not json"), httpx.Response(200, json={"x": 1})],
)
def test_bad_replies_are_model_errors(response: httpx.Response) -> None:
    with pytest.raises(ModelUnavailable) as caught:
        client_with(httpx.MockTransport(lambda r: response)).generate("p")
    assert caught.value.reason == "model_error"


def test_settings_default_to_the_host_ollama_and_granite() -> None:
    settings = Settings(relay_api_key="relay-test-sentinel", database_url="postgresql://x", redis_url="redis://x")
    assert settings.ollama_url == "http://host.docker.internal:11434"
    assert settings.ollama_model == "granite3.3:2b"
    assert 0 < settings.explain_timeout_seconds <= 30


def test_request_carries_the_structured_output_schema() -> None:
    from app.explain.prompt import ANSWER_SCHEMA
    from app.explain.rules import PATTERNS

    seen: list[httpx.Request] = []

    def handle(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(200, json={"response": "{}"})

    client_with(httpx.MockTransport(handle)).generate("p")
    schema = json.loads(seen[0].content)["format"]
    assert schema == ANSWER_SCHEMA
    assert schema["type"] == "object"
    assert set(schema["required"]) == {"cause", "text", "cited_event_seqs"}
    assert schema["properties"]["cause"] == {"type": "string", "enum": list(PATTERNS)}
    assert schema["properties"]["text"] == {"type": "string"}
    assert schema["properties"]["cited_event_seqs"] == {"type": "array", "items": {"type": "integer"}, "minItems": 1}
