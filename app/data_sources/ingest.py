"""외부 원본 → Provider Adapter → 내부 표준 Dataset 적재 → 카탈로그 메타데이터 갱신."""

import json
import urllib.request
from collections import Counter, defaultdict
from datetime import date
from pathlib import Path
from typing import Any

import psycopg
from psycopg import sql

from app.catalog.definitions import DAYCARE_FACILITY, EMD_BOUNDARY, POPULATION_BY_AGE, SEOUL
from app.data_sources.adapters import admdongkor, mois_population, seoul_childcare
from app.data_sources.adapters.seoul_childcare import FacilityRecord
from app.domain.catalog import DatasetMetadata
from app.repositories.catalog_repository import upsert_dataset

OPERATING_STATUSES = ("정상", "재개")  # 재개: 휴지 후 운영을 다시 시작한 시설
_KOREA_BBOX = (124.0, 33.0, 132.0, 39.0)  # lon/lat 범위 (minx, miny, maxx, maxy)
MAX_EXCLUDED_RATIO = 0.2  # 위치 규칙으로 이보다 많이 제외되면 데이터/코드 체계 문제로 보고 중단


class IngestError(RuntimeError):
    pass


def download(url: str, destination: Path) -> Path:
    destination.parent.mkdir(parents=True, exist_ok=True)
    request = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(request, timeout=300) as response:
        destination.write_bytes(response.read())
    return destination


def ingest_boundary(conn: psycopg.Connection, path: Path) -> DatasetMetadata:
    records = admdongkor.read_boundaries(path, SEOUL.code)
    if not records:
        raise IngestError(f"{SEOUL.name} 행정동 경계가 없습니다: {path.name}")

    with conn.transaction():
        conn.execute(
            "CREATE TEMP TABLE stage_boundary (adm_cd text, adm_nm text, sido_cd text, sido_nm text, "
            "sigungu_cd text, sigungu_nm text, geom geometry) ON COMMIT DROP"
        )
        with conn.cursor() as cur:
            cur.executemany(
                "INSERT INTO stage_boundary VALUES (%s, %s, %s, %s, %s, %s, ST_SetSRID(ST_GeomFromGeoJSON(%s), 4326))",
                [
                    (r.adm_cd, r.adm_nm, r.sido_cd, r.sido_nm, r.sigungu_cd, r.sigungu_nm, json.dumps(r.geometry))
                    for r in records
                ],
            )
        repaired = conn.execute("SELECT count(*) FROM stage_boundary WHERE NOT ST_IsValid(geom)").fetchone()[0]
        conn.execute("TRUNCATE datasets.emd_boundary")
        conn.execute(
            "INSERT INTO datasets.emd_boundary "
            "SELECT adm_cd, adm_nm, sido_cd, sido_nm, sigungu_cd, sigungu_nm, "
            "ST_Multi(ST_CollectionExtract(ST_MakeValid(geom), 3)) FROM stage_boundary"
        )
        notes = [f"유효하지 않은 경계 Geometry {repaired}개를 ST_MakeValid로 보정"] if repaired else []
        metadata = _with_load_stats(
            conn, EMD_BOUNDARY, admdongkor.reference_date_from_name(path), notes, spatial_table="emd_boundary"
        )
        upsert_dataset(conn, metadata)
    return metadata


def ingest_population(conn: psycopg.Connection, path: Path) -> DatasetMetadata:
    records = mois_population.read_population(path, SEOUL.code)
    if not records:
        raise IngestError(f"{SEOUL.name} 인구 레코드가 없습니다: {path.name}")
    reference_dates = {r.reference_date for r in records}
    if len(reference_dates) != 1:
        raise IngestError(f"인구 기준일이 하나가 아닙니다: {sorted(reference_dates)}")

    with conn.transaction():
        conn.execute("TRUNCATE datasets.population_by_age")
        with conn.cursor() as cur:
            with cur.copy(
                "COPY datasets.population_by_age (adm_cd, age, population, reference_date) FROM STDIN"
            ) as copy:
                for r in records:
                    copy.write_row((r.adm_cd, r.age, r.population, r.reference_date))
        metadata = _with_load_stats(conn, POPULATION_BY_AGE, reference_dates.pop(), [])
        upsert_dataset(conn, metadata)
    return metadata


def screen_facilities(facilities: list[FacilityRecord]) -> tuple[list[FacilityRecord], list[str]]:
    """경계 데이터 없이 판정 가능한 품질 규칙 1~3 (설계 문서 13.3)."""
    notes: list[str] = []
    duplicated = [fid for fid, n in Counter(f.facility_id for f in facilities).items() if n > 1]
    if duplicated:
        raise IngestError(f"어린이집 코드가 중복됩니다: {duplicated[:5]}")

    closed = Counter(f.status or "미기재" for f in facilities if f.status not in OPERATING_STATUSES)
    operating = [f for f in facilities if f.status in OPERATING_STATUSES]
    if closed:
        detail = ", ".join(f"{status} {count}" for status, count in closed.most_common())
        notes.append(f"운영 중(정상·재개)이 아닌 시설 {closed.total()}건 제외 ({detail})")

    located = [f for f in operating if _within_korea(f)]
    if len(located) < len(operating):
        notes.append(f"좌표가 없거나 국내 범위를 벗어난 시설 {len(operating) - len(located)}건 제외")

    sigungu_by_point: defaultdict[tuple[float, float], set[str]] = defaultdict(set)
    for f in located:
        sigungu_by_point[_point_key(f)].add(f.declared_sigungu_cd)
    placeholders = {point for point, sigungu in sigungu_by_point.items() if len(sigungu) > 1}
    kept = [f for f in located if _point_key(f) not in placeholders]
    if len(kept) < len(located):
        notes.append(
            f"서로 다른 자치구 시설이 같은 좌표를 공유하는 지점 {len(placeholders)}곳(좌표 기본값으로 판단)의 "
            f"시설 {len(located) - len(kept)}건 제외"
        )
    return kept, notes


def ingest_daycare(conn: psycopg.Connection, rows: list[dict[str, Any]]) -> DatasetMetadata:
    facilities, notes = screen_facilities(seoul_childcare.parse_facilities(rows))
    if not facilities:
        raise IngestError("품질 규칙을 통과한 어린이집이 없습니다")

    with conn.transaction():
        boundary_count = conn.execute("SELECT count(*) FROM datasets.emd_boundary").fetchone()[0]
        if boundary_count == 0:
            raise IngestError("어린이집 위치 검증에 필요한 행정동 경계가 없습니다. emd_boundary를 먼저 적재하세요")
        conn.execute(
            "CREATE TEMP TABLE stage_daycare (facility_id text, name text, facility_type text, "
            "declared_sigungu_cd text, latitude double precision, longitude double precision, "
            "reference_date date) ON COMMIT DROP"
        )
        with conn.cursor() as cur:
            with cur.copy("COPY stage_daycare FROM STDIN") as copy:
                for f in facilities:
                    copy.write_row(
                        (
                            f.facility_id,
                            f.name,
                            f.facility_type,
                            f.declared_sigungu_cd,
                            f.latitude,
                            f.longitude,
                            f.reference_date,
                        )
                    )
        # 규칙 4: 좌표가 신고 자치구 경계 안에 있어야 한다.
        located = conn.execute(
            """
            WITH s AS (
                SELECT *, ST_SetSRID(ST_MakePoint(longitude, latitude), 4326) AS geom FROM stage_daycare
            )
            SELECT
                count(*) FILTER (WHERE NOT in_declared AND in_region) AS other_sigungu,
                count(*) FILTER (WHERE NOT in_region) AS outside_region
            FROM (
                SELECT
                    EXISTS (SELECT 1 FROM datasets.emd_boundary b WHERE ST_Covers(b.geom, s.geom)) AS in_region,
                    EXISTS (SELECT 1 FROM datasets.emd_boundary b
                            WHERE b.sigungu_cd = s.declared_sigungu_cd AND ST_Covers(b.geom, s.geom)) AS in_declared
                FROM s
            ) flags
            """
        ).fetchone()
        other_sigungu, outside_region = located
        if (other_sigungu + outside_region) / len(facilities) > MAX_EXCLUDED_RATIO:
            raise IngestError(
                f"좌표 위치 규칙으로 {other_sigungu + outside_region}/{len(facilities)}건이 제외됩니다. "
                "자치구 코드 체계나 좌표계를 확인하세요"
            )
        if other_sigungu:
            notes.append(f"좌표가 신고 자치구가 아닌 다른 자치구에 있는 시설 {other_sigungu}건 제외")
        if outside_region:
            notes.append(f"좌표가 {SEOUL.name} 경계 밖에 있는 시설 {outside_region}건 제외")

        conn.execute("TRUNCATE datasets.daycare_facility")
        conn.execute(
            """
            INSERT INTO datasets.daycare_facility
            SELECT facility_id, name, facility_type, latitude, longitude, geom
            FROM (SELECT *, ST_SetSRID(ST_MakePoint(longitude, latitude), 4326) AS geom FROM stage_daycare) s
            WHERE EXISTS (SELECT 1 FROM datasets.emd_boundary b
                          WHERE b.sigungu_cd = s.declared_sigungu_cd AND ST_Covers(b.geom, s.geom))
            """
        )
        # 원본의 시설별 데이터기준일자는 최종 갱신일이므로, 가장 최근 값을 Dataset 기준 시점으로 쓴다.
        reference_date = max(f.reference_date for f in facilities)
        metadata = _with_load_stats(conn, DAYCARE_FACILITY, reference_date, notes, spatial_table="daycare_facility")
        upsert_dataset(conn, metadata)
    return metadata


def _with_load_stats(
    conn: psycopg.Connection,
    definition: DatasetMetadata,
    reference_date: date,
    notes: list[str],
    spatial_table: str | None = None,
) -> DatasetMetadata:
    spatial = definition.spatial
    if spatial_table is not None:
        query = sql.SQL(
            "SELECT count(*), ST_XMin(ST_Extent(geom)), ST_YMin(ST_Extent(geom)), "
            "ST_XMax(ST_Extent(geom)), ST_YMax(ST_Extent(geom)) FROM {}"
        ).format(sql.Identifier("datasets", spatial_table))
        count, minx, miny, maxx, maxy = conn.execute(query).fetchone()
        spatial = spatial.model_copy(update={"feature_count": count, "bbox": [minx, miny, maxx, maxy]})
    temporal = definition.temporal.model_copy(update={"reference_date": reference_date})
    return definition.model_copy(update={"spatial": spatial, "temporal": temporal, "quality_notes": notes})


def _within_korea(f: FacilityRecord) -> bool:
    if f.latitude is None or f.longitude is None:
        return False
    minx, miny, maxx, maxy = _KOREA_BBOX
    return minx <= f.longitude <= maxx and miny <= f.latitude <= maxy


def _point_key(f: FacilityRecord) -> tuple[float, float]:
    return round(f.latitude, 6), round(f.longitude, 6)
