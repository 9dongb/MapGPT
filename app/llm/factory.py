from app.config import Settings
from app.llm.base import LLMError, StructuredLLM
from app.llm.ollama_llm import OllamaChatLLM
from app.llm.openai_llm import OpenAIResponsesLLM


def create_llm(settings: Settings) -> StructuredLLM:
    """LLM_PROVIDER 설정으로 공급자를 고른다 (openai | ollama)."""
    if settings.llm_provider == "openai":
        api_key = settings.openai_api_key.get_secret_value() if settings.openai_api_key else ""
        if not api_key:
            raise LLMError("OPENAI_API_KEY가 설정되지 않았습니다 (.env)")
        return OpenAIResponsesLLM(api_key=api_key, model=settings.openai_model)
    if not settings.ollama_model:
        raise LLMError("OLLAMA_MODEL이 설정되지 않았습니다 (.env)")
    return OllamaChatLLM(
        base_url=settings.ollama_base_url,
        model=settings.ollama_model,
        reasoning_effort=settings.ollama_reasoning_effort,
    )
