"""Dataset 후보 검색 계층. Planner는 search()만 사용한다.

pgvector가 관련 Dataset 후보를 찾고, 최종 선택은 LLM이, 사용 가능 여부는 Plan Validator가 판단한다.
"""

from dataclasses import dataclass

import psycopg
from psycopg_pool import ConnectionPool

from app.domain.catalog import DatasetMetadata
from app.llm.embeddings import Embedder
from app.repositories.catalog_repository import (
    embedding_sources,
    list_datasets,
    nearest_datasets,
    upsert_embedding,
)

SEARCH_LIMIT = 10


class CatalogIndexError(RuntimeError):
    """임베딩이 없거나 메타데이터보다 오래되어 검색 결과에서 Dataset이 빠질 수 있음."""


@dataclass(frozen=True)
class ScoredDataset:
    metadata: DatasetMetadata
    similarity: float  # 코사인 유사도


def dataset_document(metadata: DatasetMetadata) -> str:
    """임베딩할 Dataset 문서: 제목·설명·태그·컬럼 설명·컬럼 의미 유형(전달 문서 34번)과 범위 지역."""
    lines = [
        f"제목: {metadata.title}",
        f"설명: {metadata.description}",
        f"분류: {metadata.category}",
        f"태그: {', '.join(metadata.semantic_tags)}",
    ]
    if metadata.spatial.coverage:
        lines.append(f"지역: {metadata.spatial.coverage.name}")
    lines.append("컬럼:")
    lines.extend(f"- {column.name}: {column.description} ({column.semantic_type})" for column in metadata.columns)
    return "\n".join(lines)


def stale_datasets(conn: psycopg.Connection, model: str, refresh: bool = False) -> list[tuple[str, str]]:
    """임베딩이 없거나, 다른 모델이거나, 임베딩한 문서가 현재 메타데이터의 문서와 다른 Dataset의 (id, 현재 문서)."""
    stale = []
    for metadata, embedded_model, source_text in embedding_sources(conn):
        document = dataset_document(metadata)
        if refresh or embedded_model != model or source_text != document:
            stale.append((metadata.dataset_id, document))
    return stale


def sync_catalog_embeddings(conn: psycopg.Connection, embedder: Embedder, refresh: bool = False) -> list[str]:
    """임베딩이 없거나 오래된 Dataset만 다시 임베딩하고, 갱신한 dataset_id를 반환한다."""
    with conn.transaction():
        targets = stale_datasets(conn, embedder.model, refresh)
    if not targets:
        return []
    vectors = embedder.embed([document for _, document in targets])
    with conn.transaction():
        for (dataset_id, document), vector in zip(targets, vectors, strict=True):
            upsert_embedding(conn, dataset_id, embedder.model, document, vector)
    return [dataset_id for dataset_id, _ in targets]


class DatasetCatalog:
    def __init__(self, pool: ConnectionPool, embedder: Embedder):
        self._pool = pool
        self._embedder = embedder

    @property
    def embedding_model(self) -> str:
        return self._embedder.model

    def list_all(self) -> list[DatasetMetadata]:
        with self._pool.connection() as conn:
            return list_datasets(conn)

    def search(self, query: str, limit: int = SEARCH_LIMIT) -> list[ScoredDataset]:
        """검색어 임베딩과 코사인 유사도가 높은 순서로 Dataset 후보를 반환한다 (pgvector)."""
        with self._pool.connection() as conn:
            stale = stale_datasets(conn, self._embedder.model)
        if stale:
            ids = ", ".join(dataset_id for dataset_id, _ in stale)
            raise CatalogIndexError(
                f"임베딩이 없거나 메타데이터보다 오래된 Dataset이 있습니다: {ids}. "
                "python -m app.cli embed-catalog 를 실행하세요"
            )
        [vector] = self._embedder.embed([query])
        with self._pool.connection() as conn:
            return [
                ScoredDataset(metadata, similarity) for metadata, similarity in nearest_datasets(conn, vector, limit)
            ]
