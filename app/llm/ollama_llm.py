"""Ollama (OpenAI 호환 Chat Completions) + response_format json_schema."""

import json

import openai
from openai import NOT_GIVEN, OpenAI

from app.llm.base import LLMError, T, parse_output
from app.llm.schema import to_llm_json_schema


class OllamaChatLLM:
    provider = "ollama"

    def __init__(self, *, base_url: str, model: str, reasoning_effort: str | None = None, client: OpenAI | None = None):
        self.model = model
        self._reasoning_effort = reasoning_effort
        # Ollama는 API 키를 검사하지 않지만 SDK는 값을 요구한다.
        self._client = client or OpenAI(base_url=base_url, api_key="ollama")

    def generate(self, *, system: str, user: str, output_type: type[T]) -> T:
        schema = to_llm_json_schema(output_type)
        # Ollama 권장사항: 스키마를 프롬프트에도 넣어 응답을 고정한다.
        grounded_system = (
            f"{system}\n\n응답은 다음 JSON Schema를 따르는 JSON 객체 하나여야 한다.\n"
            f"{json.dumps(schema, ensure_ascii=False)}"
        )
        try:
            completion = self._client.chat.completions.create(
                model=self.model,
                messages=[{"role": "system", "content": grounded_system}, {"role": "user", "content": user}],
                response_format={
                    "type": "json_schema",
                    "json_schema": {"name": output_type.__name__, "schema": schema, "strict": True},
                },
                temperature=0,
                reasoning_effort=self._reasoning_effort or NOT_GIVEN,
            )
        except openai.APIError as error:
            raise LLMError(f"Ollama 호출 실패: {error}") from error

        choice = completion.choices[0]
        if choice.finish_reason == "length":
            raise LLMError("Ollama 응답이 길이 제한으로 잘렸습니다")
        return parse_output(choice.message.content, output_type)
