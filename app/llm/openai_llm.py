"""OpenAI Responses API + Structured Outputs (json_schema, strict)."""

import openai
from openai import OpenAI

from app.llm.base import LLMError, T, parse_output
from app.llm.schema import to_llm_json_schema


class OpenAIResponsesLLM:
    provider = "openai"

    def __init__(self, *, api_key: str, model: str, client: OpenAI | None = None):
        self.model = model
        self._client = client or OpenAI(api_key=api_key)

    def generate(self, *, system: str, user: str, output_type: type[T]) -> T:
        try:
            response = self._client.responses.create(
                model=self.model,
                instructions=system,
                input=user,
                text={
                    "format": {
                        "type": "json_schema",
                        "name": output_type.__name__,
                        "schema": to_llm_json_schema(output_type),
                        "strict": True,
                    }
                },
                store=False,
            )
        except openai.APIError as error:
            raise LLMError(f"OpenAI 호출 실패: {error}") from error

        if response.status != "completed":
            reason = response.incomplete_details.reason if response.incomplete_details else response.status
            raise LLMError(f"OpenAI 응답이 완료되지 않았습니다: {reason}")
        for item in response.output:
            for part in getattr(item, "content", None) or []:
                if part.type == "refusal":
                    raise LLMError(f"OpenAI가 응답을 거절했습니다: {part.refusal}")
        return parse_output(response.output_text, output_type)
