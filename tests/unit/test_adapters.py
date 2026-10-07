import csv
import io
from datetime import date
from pathlib import Path

import pytest

from app.data_sources.adapters import admdongkor, mois_population, seoul_childcare
from app.data_sources.ingest import IngestError, screen_facilities
from tests.support import FIXTURES


def test_boundary_adapter_keeps_region_and_normalizes_codes():
    records = admdongkor.read_boundaries(FIXTURES / "admdongkor_sample.geojson", sido_code="11")

    assert [(r.adm_cd, r.adm_nm, r.sigungu_cd, r.sigungu_nm) for r in records] == [
        ("1111000100", "가동", "11110", "가가구"),
        ("1114000100", "나동", "11140", "나나구"),
    ]
    assert records[0].geometry["type"] == "MultiPolygon"


def test_boundary_reference_date_comes_from_version():
    assert admdongkor.reference_date_from_name(Path("HangJeongDong_ver20260701.geojson")) == date(2026, 7, 1)


def _population_csv(rows: list[dict[str, object]]) -> bytes:
    ages = [f"{a}세" for a in range(110)] + ["110세이상 "]
    header = ["행정기관코드", "기준연월", "시도명", "시군구명", "읍면동명", "계", "남자", "여자"]
    header += [f"{a}남자" for a in ages] + [f"{a}여자" for a in ages]
    buffer = io.StringIO()
    writer = csv.writer(buffer)
    writer.writerow(header)
    for row in rows:
        male, female = row["male"], row["female"]
        total = row.get("total", sum(male.values()) + sum(female.values()))
        values = [
            row["code"],
            "2026-09-30",
            "서울특별시",
            "가가구",
            "가동",
            total,
            sum(male.values()),
            sum(female.values()),
        ]
        values += [male.get(a, 0) for a in range(111)] + [female.get(a, 0) for a in range(111)]
        writer.writerow(values)
    return buffer.getvalue().encode("cp949")


def test_population_adapter_melts_wide_csv_and_sums_sexes(tmp_path):
    path = tmp_path / "pop.csv"
    path.write_bytes(
        _population_csv(
            [
                {"code": "1111000100", "male": {0: 3, 5: 1, 110: 2}, "female": {0: 4, 6: 7}},
                {"code": "2611000100", "male": {0: 9}, "female": {}},
            ]
        )
    )

    records = mois_population.read_population(path, sido_code="11")

    by_age = {r.age: r.population for r in records}
    assert len(records) == 111
    assert {r.adm_cd for r in records} == {"1111000100"}
    assert (by_age[0], by_age[5], by_age[6], by_age[110], by_age[50]) == (7, 1, 7, 2, 0)
    assert records[0].reference_date == date(2026, 9, 30)


def test_population_adapter_rejects_inconsistent_totals(tmp_path):
    path = tmp_path / "pop.csv"
    path.write_bytes(_population_csv([{"code": "1111000100", "male": {0: 3}, "female": {}, "total": 4}]))

    with pytest.raises(ValueError, match="계"):
        mois_population.read_population(path, sido_code="11")


def _row(stcode: str, status: str = "정상", la: str = "37.55", lo: str = "126.95") -> dict[str, str]:
    return {
        "STCODE": stcode,
        "CRNAME": f"시설{stcode} ",
        "CRTYPENAME": "국공립",
        "CRSTATUSNAME": status,
        "LA": la,
        "LO": lo,
        "DATASTDRDT": "2026-10-07",
    }


def test_childcare_adapter_parses_provider_fields():
    [record] = seoul_childcare.parse_facilities([_row("11110000001", la="", lo="0")])

    assert record.facility_id == "11110000001"
    assert record.name == "시설11110000001"
    assert record.declared_sigungu_cd == "11110"
    assert (record.latitude, record.longitude) == (None, None)
    assert record.reference_date == date(2026, 10, 7)


def test_screen_facilities_applies_status_coordinate_and_placeholder_rules():
    rows = [
        _row("11110000001"),  # 정상
        _row("11110000002", status="폐지"),
        _row("11110000003", status="휴지"),
        _row("11110000006", status=""),
        _row("11110000007", status="재개", la="37.56"),  # 운영 재개 → 유지
        _row("11110000004", la=""),  # 좌표 없음
        _row("11110000005", la="10.0"),  # 국내 범위 밖
        _row("11260000001", la="37.566470", lo="126.977963"),  # 서로 다른 자치구가 같은 좌표 → 기본값
        _row("11530000001", la="37.566470", lo="126.977963"),
        _row("11650000001", la="37.48", lo="126.98"),  # 같은 자치구 두 시설이 같은 좌표 → 유지
        _row("11650000002", la="37.48", lo="126.98"),
    ]

    kept, notes = screen_facilities(seoul_childcare.parse_facilities(rows))

    assert [f.facility_id for f in kept] == ["11110000001", "11110000007", "11650000001", "11650000002"]
    assert notes == [
        "운영 중(정상·재개)이 아닌 시설 3건 제외 (폐지 1, 휴지 1, 미기재 1)",
        "좌표가 없거나 국내 범위를 벗어난 시설 2건 제외",
        "서로 다른 자치구 시설이 같은 좌표를 공유하는 지점 1곳(좌표 기본값으로 판단)의 시설 2건 제외",
    ]


def test_screen_facilities_rejects_duplicate_ids():
    with pytest.raises(IngestError, match="중복"):
        screen_facilities(seoul_childcare.parse_facilities([_row("11110000001"), _row("11110000001")]))
