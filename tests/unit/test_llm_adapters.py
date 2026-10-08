import json

import httpx2
import pytest
from openai import OpenAI

from app.config import Settings
from app.domain.state import Explanation
from app.llm.base import LLMError, LLMOutputError
from app.llm.embeddings import EMBEDDING_DIMENSIONS, EmbeddingError, OpenAIEmbedder
from app.llm.factory import create_embedder, create_llm
from app.llm.ollama_llm import OllamaChatLLM
from app.llm.openai_llm import OpenAIResponsesLLM
from app.llm.schema import to_llm_json_schema


class Recorder:
    def __init__(self, body: dict):
        self.body = body
        self.requests: list[httpx2.Request] = []

    def __call__(self, request: httpx2.Request) -> httpx2.Response:
        self.requests.append(request)
        return httpx2.Response(200, json=self.body)

    @property
    def sent(self) -> dict:
        return json.loads(self.requests[-1].content)


def _client(recorder: Recorder, base_url: str = "http://test/v1") -> OpenAI:
    return OpenAI(
        api_key="test-key", base_url=base_url, http_client=httpx2.Client(transport=httpx2.MockTransport(recorder))
    )


def _response(content: list[dict], status: str = "completed", incomplete: dict | None = None) -> dict:
    return {
        "id": "resp_1",
        "object": "response",
        "created_at": 0,
        "status": status,
        "model": "gpt-6.1-sol",
        "incomplete_details": incomplete,
        "output": [{"type": "message", "id": "msg_1", "status": "completed", "role": "assistant", "content": content}],
    }


def _text(text: str) -> dict:
    return {"type": "output_text", "text": text, "annotations": []}


def test_openai_adapter_sends_strict_json_schema_via_responses_api():
    recorder = Recorder(_response([_text('{"summary": "요약"}')]))
    llm = OpenAIResponsesLLM(api_key="unused", model="gpt-6.1-sol", client=_client(recorder))

    result = llm.generate(system="시스템", user="질문", output_type=Explanation)

    assert result == Explanation(summary="요약")
    assert recorder.requests[-1].url.path == "/v1/responses"
    sent = recorder.sent
    assert (sent["model"], sent["instructions"], sent["input"], sent["store"]) == (
        "gpt-6.1-sol",
        "시스템",
        "질문",
        False,
    )
    assert sent["text"]["format"] == {
        "type": "json_schema",
        "name": "Explanation",
        "schema": to_llm_json_schema(Explanation),
        "strict": True,
    }


@pytest.mark.parametrize(
    ("body", "error"),
    [
        (_response([{"type": "refusal", "refusal": "거절"}]), "거절"),
        (
            _response([_text('{"summ')], status="incomplete", incomplete={"reason": "max_output_tokens"}),
            "max_output_tokens",
        ),
    ],
)
def test_openai_adapter_raises_on_refusal_or_incomplete_response(body, error):
    llm = OpenAIResponsesLLM(api_key="unused", model="m", client=_client(Recorder(body)))

    with pytest.raises(LLMError, match=error):
        llm.generate(system="s", user="u", output_type=Explanation)


def test_schema_mismatch_is_an_output_error():
    llm = OpenAIResponsesLLM(api_key="unused", model="m", client=_client(Recorder(_response([_text('{"text": 1}')]))))

    with pytest.raises(LLMOutputError, match="Explanation"):
        llm.generate(system="s", user="u", output_type=Explanation)


def _completion(content: str, finish_reason: str = "stop") -> dict:
    return {
        "id": "c1",
        "object": "chat.completion",
        "created": 0,
        "model": "granite4.1:8b",
        "choices": [{"index": 0, "finish_reason": finish_reason, "message": {"role": "assistant", "content": content}}],
    }


def test_ollama_adapter_sends_json_schema_response_format_and_grounds_prompt():
    recorder = Recorder(_completion('{"summary": "요약"}'))
    llm = OllamaChatLLM(base_url="http://localhost:11434/v1", model="granite4.1:8b", client=_client(recorder))

    result = llm.generate(system="시스템", user="질문", output_type=Explanation)

    assert result == Explanation(summary="요약")
    assert recorder.requests[-1].url.path == "/v1/chat/completions"
    sent = recorder.sent
    assert sent["temperature"] == 0
    assert sent["response_format"]["type"] == "json_schema"
    assert sent["response_format"]["json_schema"]["schema"] == to_llm_json_schema(Explanation)
    system, user = sent["messages"]
    assert system["role"] == "system" and system["content"].startswith("시스템") and '"summary"' in system["content"]
    assert user == {"role": "user", "content": "질문"}


def test_ollama_adapter_sends_reasoning_effort_only_when_configured():
    default, tuned = Recorder(_completion('{"summary": "x"}')), Recorder(_completion('{"summary": "x"}'))
    OllamaChatLLM(base_url="http://x/v1", model="m", client=_client(default)).generate(
        system="s", user="u", output_type=Explanation
    )
    OllamaChatLLM(base_url="http://x/v1", model="m", reasoning_effort="none", client=_client(tuned)).generate(
        system="s", user="u", output_type=Explanation
    )

    assert "reasoning_effort" not in default.sent
    assert tuned.sent["reasoning_effort"] == "none"


def test_ollama_adapter_raises_on_truncated_output():
    llm = OllamaChatLLM(base_url="http://x/v1", model="m", client=_client(Recorder(_completion('{"su', "length"))))

    with pytest.raises(LLMError, match="길이"):
        llm.generate(system="s", user="u", output_type=Explanation)


def test_factory_switches_provider_by_settings():
    openai_llm = create_llm(Settings(llm_provider="openai", openai_api_key="sk-test", openai_model="gpt-6.1-sol"))
    ollama_llm = create_llm(Settings(llm_provider="ollama", ollama_model="granite4.1:8b"))

    assert (openai_llm.provider, openai_llm.model) == ("openai", "gpt-6.1-sol")
    assert (ollama_llm.provider, ollama_llm.model) == ("ollama", "granite4.1:8b")


@pytest.mark.parametrize(
    ("settings", "message"),
    [
        (Settings(llm_provider="openai", openai_api_key=None), "OPENAI_API_KEY"),
        (Settings(llm_provider="openai", openai_api_key=""), "OPENAI_API_KEY"),
        (Settings(llm_provider="ollama", ollama_model=None), "OLLAMA_MODEL"),
    ],
)
def test_factory_fails_explicitly_without_configuration(settings, message):
    with pytest.raises(LLMError, match=message):
        create_llm(settings)


def _embeddings(*vectors: list[float]) -> dict:
    data = [{"object": "embedding", "index": index, "embedding": vector} for index, vector in enumerate(vectors)]
    return {
        "object": "list",
        "data": data[::-1],  # 응답 순서가 아니라 index로 입력과 맞춘다
        "model": "text-embedding-3-small",
        "usage": {"prompt_tokens": 1, "total_tokens": 1},
    }


def test_openai_embedder_requests_fixed_dimensions_and_keeps_input_order():
    first, second = [0.1] * EMBEDDING_DIMENSIONS, [0.2] * EMBEDDING_DIMENSIONS
    recorder = Recorder(_embeddings(first, second))
    embedder = OpenAIEmbedder(api_key="unused", model="text-embedding-3-small", client=_client(recorder))

    vectors = embedder.embed(["어린이집 위치", "0~5세 인구"])

    assert vectors == [first, second]
    assert recorder.requests[-1].url.path == "/v1/embeddings"
    assert recorder.sent == {
        "model": "text-embedding-3-small",
        "input": ["어린이집 위치", "0~5세 인구"],
        "dimensions": EMBEDDING_DIMENSIONS,
        "encoding_format": "float",
    }


def test_openai_embedder_rejects_vectors_that_do_not_fit_the_index():
    embedder = OpenAIEmbedder(api_key="unused", model="m", client=_client(Recorder(_embeddings([0.1, 0.2]))))

    with pytest.raises(EmbeddingError, match="차원"):
        embedder.embed(["어린이집"])


def test_openai_embedder_wraps_api_errors():
    def unauthorized(request: httpx2.Request) -> httpx2.Response:
        return httpx2.Response(401, json={"error": {"message": "invalid api key", "type": "invalid_request_error"}})

    embedder = OpenAIEmbedder(api_key="unused", model="m", client=_client(unauthorized))

    with pytest.raises(EmbeddingError, match="OpenAI 임베딩 호출 실패"):
        embedder.embed(["어린이집"])


def test_embedder_is_openai_even_when_llm_provider_is_ollama():
    embedder = create_embedder(
        Settings(llm_provider="ollama", openai_api_key="sk-test", openai_embedding_model="text-embedding-3-large")
    )

    assert isinstance(embedder, OpenAIEmbedder) and embedder.model == "text-embedding-3-large"


@pytest.mark.parametrize("api_key", [None, ""])
def test_embedder_fails_explicitly_without_openai_api_key(api_key):
    with pytest.raises(EmbeddingError, match="OPENAI_API_KEY"):
        create_embedder(Settings(llm_provider="ollama", openai_api_key=api_key))
