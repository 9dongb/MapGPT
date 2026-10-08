import psycopg
from psycopg.types.json import Jsonb

from app.domain.catalog import DatasetMetadata


def upsert_dataset(conn: psycopg.Connection, metadata: DatasetMetadata) -> None:
    conn.execute(
        """
        INSERT INTO catalog.dataset (dataset_id, metadata, loaded_at)
        VALUES (%s, %s, now())
        ON CONFLICT (dataset_id) DO UPDATE SET metadata = EXCLUDED.metadata, loaded_at = EXCLUDED.loaded_at
        """,
        (metadata.dataset_id, Jsonb(metadata.model_dump(mode="json"))),
    )


def list_datasets(conn: psycopg.Connection) -> list[DatasetMetadata]:
    rows = conn.execute("SELECT metadata FROM catalog.dataset ORDER BY dataset_id").fetchall()
    return [DatasetMetadata.model_validate(row[0]) for row in rows]


def embedding_sources(conn: psycopg.Connection) -> list[tuple[DatasetMetadata, str | None, str | None]]:
    """모든 Dataset과, 저장된 임베딩의 모델·원문 (임베딩이 없으면 None)."""
    rows = conn.execute(
        """
        SELECT d.metadata, e.model, e.source_text
        FROM catalog.dataset d LEFT JOIN catalog.dataset_embedding e USING (dataset_id)
        ORDER BY d.dataset_id
        """
    ).fetchall()
    return [(DatasetMetadata.model_validate(metadata), model, source_text) for metadata, model, source_text in rows]


def upsert_embedding(
    conn: psycopg.Connection, dataset_id: str, model: str, source_text: str, embedding: list[float]
) -> None:
    conn.execute(
        """
        INSERT INTO catalog.dataset_embedding (dataset_id, model, source_text, embedding, embedded_at)
        VALUES (%s, %s, %s, %s::vector, now())
        ON CONFLICT (dataset_id) DO UPDATE SET
            model = EXCLUDED.model, source_text = EXCLUDED.source_text,
            embedding = EXCLUDED.embedding, embedded_at = EXCLUDED.embedded_at
        """,
        (dataset_id, model, source_text, _vector(embedding)),
    )


def nearest_datasets(
    conn: psycopg.Connection, embedding: list[float], limit: int
) -> list[tuple[DatasetMetadata, float]]:
    """코사인 거리(<=>)가 가까운 순서로 Dataset과 유사도(1 - 거리)를 반환한다."""
    rows = conn.execute(
        """
        SELECT d.metadata, 1 - (e.embedding <=> %(query)s::vector)
        FROM catalog.dataset_embedding e JOIN catalog.dataset d USING (dataset_id)
        ORDER BY e.embedding <=> %(query)s::vector
        LIMIT %(limit)s
        """,
        {"query": _vector(embedding), "limit": limit},
    ).fetchall()
    return [(DatasetMetadata.model_validate(metadata), float(similarity)) for metadata, similarity in rows]


def _vector(values: list[float]) -> str:
    return "[" + ",".join(str(value) for value in values) + "]"
