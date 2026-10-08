from app.config import Settings
from app.llm.base import LLMError, StructuredLLM
from app.llm.embeddings import Embedder, EmbeddingError, OpenAIEmbedder
from app.llm.ollama_llm import OllamaChatLLM
from app.llm.openai_llm import OpenAIResponsesLLM


def _openai_api_key(settings: Settings) -> str:
    return settings.openai_api_key.get_secret_value() if settings.openai_api_key else ""


def create_llm(settings: Settings) -> StructuredLLM:
    """LLM_PROVIDER 설정으로 공급자를 고른다 (openai | ollama)."""
    if settings.llm_provider == "openai":
        api_key = _openai_api_key(settings)
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


def create_embedder(settings: Settings) -> Embedder:
    """Dataset 후보 검색용 임베딩. LLM_PROVIDER가 ollama여도 OpenAI 키가 필요하다."""
    api_key = _openai_api_key(settings)
    if not api_key:
        raise EmbeddingError("OPENAI_API_KEY가 설정되지 않았습니다 (.env) — Dataset 검색 임베딩에 필요합니다")
    return OpenAIEmbedder(api_key=api_key, model=settings.openai_embedding_model)
