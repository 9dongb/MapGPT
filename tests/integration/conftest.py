from datetime import date

import pytest
from psycopg_pool import ConnectionPool

from app.catalog.catalog import sync_catalog_embeddings
from app.catalog.definitions import TRUSTED_DATASETS
from app.repositories.catalog_repository import upsert_dataset
from tests.fakes import FakeEmbedder
from tests.integration.synthetic import SEOUL_BBOX, UNITS, load_synthetic

REFERENCE_DATES = {
    "emd_boundary": date(2026, 7, 1),
    "population_by_age": date(2026, 9, 30),
    "daycare_facility": date(2026, 10, 7),
}


@pytest.fixture
def pool(database_url):
    with ConnectionPool(database_url, min_size=1, max_size=3) as pool:
        yield pool


@pytest.fixture
def catalog(conn):
    """합성 데이터와, 적재 시 계산되는 통계(기준일·bbox·feature 수)를 채운 카탈로그·검색 임베딩을 등록한다."""
    load_synthetic(conn)
    seoul_units = sum(1 for unit in UNITS if unit[2] == "11")
    for metadata in TRUSTED_DATASETS.values():
        temporal = metadata.temporal.model_copy(update={"reference_date": REFERENCE_DATES[metadata.dataset_id]})
        metadata = metadata.model_copy(update={"temporal": temporal})
        if metadata.dataset_id == "emd_boundary":
            spatial = metadata.spatial.model_copy(update={"feature_count": seoul_units, "bbox": SEOUL_BBOX})
            metadata = metadata.model_copy(update={"spatial": spatial})
        upsert_dataset(conn, metadata)
    conn.commit()
    sync_catalog_embeddings(conn, FakeEmbedder())
