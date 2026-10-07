"""CRS Policy. CRS는 LLM이 아니라 이 정책이 결정한다.

- 지도 반환: EPSG:4326
- 위상 연산(점-폴리곤 포함): 경계 Dataset의 CRS로 맞춘다.
- 거리·면적 연산(EPSG:5179 등)은 해당 Operation이 추가될 때 정책을 확장한다.
"""

import re

from psycopg import sql

MAP_OUTPUT_SRID = 4326
SUPPORTED_SRIDS = frozenset({4326, 5179})


class CrsError(ValueError):
    pass


def parse_srid(crs: str | None) -> int:
    if crs is None:
        raise CrsError("CRS가 명시되지 않았습니다")
    match = re.fullmatch(r"EPSG:(\d+)", crs)
    if match is None:
        raise CrsError(f"CRS 형식이 'EPSG:<코드>'가 아닙니다: {crs}")
    srid = int(match.group(1))
    if srid not in SUPPORTED_SRIDS:
        raise CrsError(f"지원하지 않는 CRS입니다: {crs} (지원: {sorted(SUPPORTED_SRIDS)})")
    return srid


def transform_crs(geometry: sql.Composable, source_srid: int, target_srid: int) -> sql.Composable:
    if source_srid == target_srid:
        return geometry
    return sql.SQL("ST_Transform({}, {})").format(geometry, sql.Literal(target_srid))
