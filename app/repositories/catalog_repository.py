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
