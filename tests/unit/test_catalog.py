from app.catalog.catalog import dataset_document
from app.catalog.definitions import TRUSTED_DATASETS


def test_dataset_document_describes_meaning_and_columns():
    document = dataset_document(TRUSTED_DATASETS["daycare_facility"])

    assert document.startswith("제목: 서울특별시 어린이집 위치\n설명: 서울특별시에서 운영 중")
    assert "태그: 어린이집, 보육시설, 영유아, 시설, 공급, point\n지역: 서울특별시\n컬럼:" in document
    assert "\n- latitude: 위도 (WGS84) (latitude)\n" in document


def test_load_statistics_do_not_change_the_document():
    metadata = TRUSTED_DATASETS["emd_boundary"]
    loaded = metadata.model_copy(update={"spatial": metadata.spatial.model_copy(update={"feature_count": 427})})

    assert dataset_document(loaded) == dataset_document(metadata)
