import pytest

from app.catalog.catalog import CatalogIndexError, DatasetCatalog, sync_catalog_embeddings
from tests.fakes import FakeEmbedder

pytestmark = pytest.mark.integration

ALL_DATASETS = ["daycare_facility", "emd_boundary", "population_by_age"]


@pytest.mark.parametrize(
    ("query", "expected"),
    [
        ("어린이집 위치", "daycare_facility"),
        ("연령별 주민등록 인구", "population_by_age"),
        ("행정동 경계 polygon", "emd_boundary"),
    ],
)
def test_search_returns_most_similar_dataset_first(pool, catalog, query, expected):
    hits = DatasetCatalog(pool, FakeEmbedder()).search(query)

    assert hits[0].metadata.dataset_id == expected
    assert sorted(hit.metadata.dataset_id for hit in hits) == ALL_DATASETS
    assert [hit.similarity for hit in hits] == sorted((hit.similarity for hit in hits), reverse=True)


def test_search_returns_at_most_limit_candidates(pool, catalog):
    hits = DatasetCatalog(pool, FakeEmbedder()).search("어린이집 위치", limit=1)

    assert [hit.metadata.dataset_id for hit in hits] == ["daycare_facility"]


def test_sync_reembeds_only_datasets_whose_document_changed(conn, catalog):
    embedder = FakeEmbedder()
    assert sync_catalog_embeddings(conn, embedder) == [] and embedder.calls == []

    conn.execute(
        "UPDATE catalog.dataset SET metadata = jsonb_set(metadata, '{spatial,feature_count}', '50') "
        "WHERE dataset_id = 'emd_boundary'"
    )
    conn.execute(
        "UPDATE catalog.dataset SET metadata = jsonb_set(metadata, '{description}', '\"새 설명\"') "
        "WHERE dataset_id = 'daycare_facility'"
    )
    conn.commit()

    assert sync_catalog_embeddings(conn, embedder) == ["daycare_facility"]
    [[document]] = embedder.calls
    assert "설명: 새 설명" in document
    stored = conn.execute(
        "SELECT source_text FROM catalog.dataset_embedding WHERE dataset_id = 'daycare_facility'"
    ).fetchone()
    assert stored == (document,)


def test_sync_reembeds_everything_for_another_model_or_refresh(conn, catalog):
    assert sync_catalog_embeddings(conn, FakeEmbedder(model="other-model")) == ALL_DATASETS
    assert sync_catalog_embeddings(conn, FakeEmbedder(model="other-model")) == []
    assert sync_catalog_embeddings(conn, FakeEmbedder(model="other-model"), refresh=True) == ALL_DATASETS
    assert conn.execute("SELECT DISTINCT model FROM catalog.dataset_embedding").fetchall() == [("other-model",)]


def test_search_refuses_missing_or_outdated_embeddings(pool, conn, catalog):
    conn.execute("DELETE FROM catalog.dataset_embedding WHERE dataset_id = 'population_by_age'")
    conn.commit()
    embedder = FakeEmbedder()

    with pytest.raises(CatalogIndexError, match="population_by_age\\. python -m app.cli embed-catalog"):
        DatasetCatalog(pool, embedder).search("0~5세 인구")
    with pytest.raises(CatalogIndexError, match="daycare_facility, emd_boundary, population_by_age"):
        DatasetCatalog(pool, FakeEmbedder(model="other-model")).search("0~5세 인구")
    assert embedder.calls == []  # 검색어 임베딩 전에 멈춘다
