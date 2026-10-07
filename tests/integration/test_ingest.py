from datetime import date

import pytest

from app.data_sources.ingest import IngestError, ingest_boundary, ingest_daycare
from app.repositories.catalog_repository import list_datasets
from tests.support import FIXTURES

pytestmark = pytest.mark.integration


def _row(stcode: str, la: float, lo: float) -> dict[str, str]:
    return {
        "STCODE": stcode,
        "CRNAME": f"시설{stcode}",
        "CRTYPENAME": "민간",
        "CRSTATUSNAME": "정상",
        "LA": str(la),
        "LO": str(lo),
        "DATASTDRDT": "2026-10-07",
    }


def test_boundary_ingest_loads_region_and_records_catalog_stats(conn, tmp_path):
    path = tmp_path / "HangJeongDong_ver20260701.geojson"
    path.write_bytes((FIXTURES / "admdongkor_sample.geojson").read_bytes())

    metadata = ingest_boundary(conn, path)

    assert conn.execute("SELECT array_agg(adm_cd ORDER BY adm_cd) FROM datasets.emd_boundary").fetchone()[0] == [
        "1111000100",
        "1114000100",
    ]
    assert metadata.temporal.reference_date == date(2026, 7, 1)
    assert metadata.spatial.feature_count == 2
    assert metadata.spatial.bbox == pytest.approx([126.9, 37.5, 127.1, 37.6])
    assert [d.dataset_id for d in list_datasets(conn)] == ["emd_boundary"]


def test_daycare_ingest_excludes_points_outside_declared_sigungu(conn, tmp_path):
    path = tmp_path / "HangJeongDong_ver20260701.geojson"
    path.write_bytes((FIXTURES / "admdongkor_sample.geojson").read_bytes())
    ingest_boundary(conn, path)
    rows = [
        _row("11110000001", 37.55, 126.95),  # 가가구 안 (신고 자치구 일치)
        _row("11110000002", 37.55, 126.96),
        _row("11110000003", 37.56, 126.97),
        _row("11140000001", 37.55, 127.05),  # 나나구 안
        _row("11140000002", 37.55, 126.99),  # 나나구 신고지만 가가구 안 → 제외
    ]
    rows += [_row(f"1111000001{i}", 37.51 + i / 100, 126.91) for i in range(5)]

    metadata = ingest_daycare(conn, rows)

    [ids] = conn.execute("SELECT array_agg(facility_id ORDER BY facility_id) FROM datasets.daycare_facility").fetchone()
    assert "11140000002" not in ids and len(ids) == 9
    assert metadata.quality_notes == ["좌표가 신고 자치구가 아닌 다른 자치구에 있는 시설 1건 제외"]
    assert metadata.temporal.reference_date == date(2026, 10, 7)
    assert metadata.spatial.feature_count == 9


def test_daycare_ingest_stops_when_most_points_fall_outside(conn, tmp_path):
    path = tmp_path / "HangJeongDong_ver20260701.geojson"
    path.write_bytes((FIXTURES / "admdongkor_sample.geojson").read_bytes())
    ingest_boundary(conn, path)

    with pytest.raises(IngestError, match="자치구 코드 체계나 좌표계"):
        ingest_daycare(conn, [_row("11110000001", 37.55, 126.95), _row("11110000002", 37.45, 126.95)])
