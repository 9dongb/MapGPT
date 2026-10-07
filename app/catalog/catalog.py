from psycopg_pool import ConnectionPool

from app.domain.catalog import DatasetMetadata
from app.repositories.catalog_repository import list_datasets


class DatasetCatalog:
    """Dataset 후보 검색 계층. Planner는 이 인터페이스만 사용한다."""

    def __init__(self, pool: ConnectionPool):
        self._pool = pool

    def search(self, query: str, limit: int = 10) -> list[DatasetMetadata]:
        """MVP: 등록된 Dataset 전체를 반환한다 (query 미사용).

        Dataset이 많아지면 이 메서드 내부만 pgvector 유사도 검색(Top-K)으로 교체한다.
        """
        return self.list_all()[:limit]

    def list_all(self) -> list[DatasetMetadata]:
        with self._pool.connection() as conn:
            return list_datasets(conn)
