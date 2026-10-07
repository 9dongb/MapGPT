from typing import Protocol, TypeVar

from pydantic import BaseModel, ValidationError

T = TypeVar("T", bound=BaseModel)


class LLMError(RuntimeError):
    """LLM 호출 실패 (API 오류, 거절, 잘림)."""


class LLMOutputError(LLMError):
    """LLM 응답이 요청한 스키마를 통과하지 못함. 이 경우 실행하지 않는다."""


class StructuredLLM(Protocol):
    provider: str
    model: str

    def generate(self, *, system: str, user: str, output_type: type[T]) -> T: ...


def parse_output(text: str | None, output_type: type[T]) -> T:
    if not text:
        raise LLMOutputError("LLM 응답이 비어 있습니다")
    try:
        return output_type.model_validate_json(text)
    except ValidationError as error:
        raise LLMOutputError(f"LLM 응답이 {output_type.__name__} 스키마를 통과하지 못했습니다: {error}") from error
