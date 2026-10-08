"""Dataset 메타데이터·검색어 임베딩 (OpenAI Embeddings API)."""

from typing import Protocol

import openai
from openai import OpenAI

# catalog.dataset_embedding.embedding 컬럼(vector(1536))과 같아야 한다.
EMBEDDING_DIMENSIONS = 1536


class EmbeddingError(RuntimeError):
    pass


class Embedder(Protocol):
    model: str

    def embed(self, texts: list[str]) -> list[list[float]]: ...


class OpenAIEmbedder:
    def __init__(self, *, api_key: str, model: str, client: OpenAI | None = None):
        self.model = model
        self._client = client or OpenAI(api_key=api_key)

    def embed(self, texts: list[str]) -> list[list[float]]:
        try:
            response = self._client.embeddings.create(
                model=self.model, input=texts, dimensions=EMBEDDING_DIMENSIONS, encoding_format="float"
            )
        except openai.APIError as error:
            raise EmbeddingError(f"OpenAI 임베딩 호출 실패: {error}") from error
        vectors = [item.embedding for item in sorted(response.data, key=lambda item: item.index)]
        if len(vectors) != len(texts) or any(len(vector) != EMBEDDING_DIMENSIONS for vector in vectors):
            raise EmbeddingError("임베딩 응답의 개수나 차원이 요청과 다릅니다")
        return vectors
