"""GIS Tools: 검증된 Operation을 PostGIS(parameterized SQL)와 결정론적 코드로 실행한다.

데이터는 PostGIS에 두고, Tool 사이에는 View(메타데이터 + 필터) 참조만 주고받는다.
"""

import math
from collections import Counter
from dataclasses import dataclass, field, replace
from decimal import Decimal
from typing import Any

import psycopg
from psycopg import sql

from app.domain.catalog import DatasetMetadata, RegionRef
from app.domain.enums import (
    AggregationFunction,
    DataType,
    FilterOperator,
    GeometryType,
    MapType,
    SemanticType,
    SortOrder,
    SpatialLevel,
)
from app.domain.filters import FilterCondition, FilterExpression
from app.domain.results import Classification, MapLayer, MetricValue, UnitRow
from app.gis.crs import MAP_OUTPUT_SRID, CrsError, parse_srid, transform_crs
from app.gis.filter_sql import FilterCompileError, compile_filter

QUANTILE_CLASSES = 5
_REGION_NAME_COLUMN = {SpatialLevel.SIDO: SemanticType.SIDO_NAME, SpatialLevel.SIGUNGU: SemanticType.SIGUNGU_NAME}
_SQL_AGGREGATES = {AggregationFunction.COUNT: "count", AggregationFunction.SUM: "sum"}


class GisToolError(RuntimeError):
    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code


@dataclass(frozen=True)
class DatasetView:
    metadata: DatasetMetadata
    filter: FilterExpression | None
    row_count: int

    @property
    def table(self) -> sql.Identifier:
        return sql.Identifier("datasets", self.metadata.dataset_id)

    def where(self) -> tuple[sql.Composable, list[Any]]:
        if self.filter is None:
            return sql.SQL("TRUE"), []
        try:
            return compile_filter(self.filter, self.metadata)
        except FilterCompileError as error:
            raise GisToolError("FILTER_INVALID", str(error)) from error


@dataclass(frozen=True)
class Unit:
    key: str
    name: str
    parent_name: str | None


@dataclass(frozen=True)
class BoundaryView(DatasetView):
    region: RegionRef
    key_field: str
    srid: int
    units: tuple[Unit, ...]
    invalid_geometry_count: int
    empty_geometry_count: int
    bbox: list[float] | None  # EPSG:4326

    @property
    def unit_keys(self) -> list[str]:
        return [unit.key for unit in self.units]


@dataclass
class MetricValues:
    name: str
    values: dict[str, MetricValue]
    null_reasons: dict[str, str] = field(default_factory=dict)
    stats: dict[str, int | float] = field(default_factory=dict)


@dataclass(frozen=True)
class GeometryReport:
    invalid: int
    empty: int


def get_dataset(conn: psycopg.Connection, metadata: DatasetMetadata) -> DatasetView:
    """카탈로그에 등록된 내부 표준 Dataset 테이블 참조를 얻는다."""
    exists = conn.execute("SELECT to_regclass(%s)", (f"datasets.{metadata.dataset_id}",)).fetchone()[0]
    if exists is None:
        raise GisToolError(
            "DATASET_TABLE_MISSING", f"'{metadata.dataset_id}' 테이블이 없습니다. 적재(ingest)를 먼저 실행하세요"
        )
    view = DatasetView(metadata=metadata, filter=None, row_count=0)
    count = _count(conn, view)
    if count == 0:
        raise GisToolError("DATASET_EMPTY", f"'{metadata.dataset_id}' Dataset이 비어 있습니다")
    return replace(view, row_count=count)


def filter_dataset(conn: psycopg.Connection, view: DatasetView, expression: FilterExpression) -> DatasetView:
    """FilterExpression을 View에 적용한다 (데이터는 이동하지 않는다)."""
    filtered = replace(view, filter=expression)
    count = _count(conn, filtered)
    if count == 0:
        raise GisToolError("FILTER_EMPTY_RESULT", f"'{view.metadata.dataset_id}' 필터 결과가 비어 있습니다")
    return replace(filtered, row_count=count)


def get_boundary(conn: psycopg.Connection, metadata: DatasetMetadata, region: RegionRef) -> BoundaryView:
    """분석 지역 안의 경계 Polygon 집합을 얻고 Geometry 유효성을 검증한다."""
    if not metadata.is_polygon:
        raise GisToolError("NOT_POLYGON", f"'{metadata.dataset_id}'는 Polygon Dataset이 아닙니다")
    srid = _srid(metadata)
    name_column = metadata.column_with(SemanticType.ADMINISTRATIVE_NAME)
    region_column = metadata.column_with(_REGION_NAME_COLUMN.get(region.level))
    if not metadata.join_keys or name_column is None or region_column is None or metadata.geometry_column is None:
        raise GisToolError(
            "BOUNDARY_METADATA_INCOMPLETE", f"'{metadata.dataset_id}'에 단위 키·이름·지역 컬럼 정보가 없습니다"
        )
    key_field = metadata.join_keys[0].field
    parent_column = metadata.column_with(SemanticType.SIGUNGU_NAME)

    view = replace(
        get_dataset(conn, metadata),
        filter=FilterCondition(field=region_column.name, operator=FilterOperator.EQ, value=region.name),
    )
    where, params = view.where()
    key, geom = sql.Identifier(key_field), sql.Identifier(metadata.geometry_column.name)
    parent = sql.Identifier(parent_column.name) if parent_column else sql.NULL
    units = tuple(
        Unit(key=k, name=n, parent_name=p)
        for k, n, p in conn.execute(
            sql.SQL("SELECT {}::text, {}, {} FROM {} WHERE {} ORDER BY 1").format(
                key, sql.Identifier(name_column.name), parent, view.table, where
            ),
            params,
        ).fetchall()
    )
    if not units:
        raise GisToolError("REGION_NOT_FOUND", f"'{metadata.dataset_id}'에 '{region.name}' 경계가 없습니다")
    if len({u.key for u in units}) != len(units):
        raise GisToolError("DUPLICATE_UNIT_KEY", f"'{metadata.dataset_id}'에 중복된 단위 키가 있습니다")

    view = replace(view, row_count=len(units))
    report = validate_geometry(conn, view)
    if report.invalid or report.empty:
        raise GisToolError(
            "INVALID_GEOMETRY",
            f"'{metadata.dataset_id}' 경계에 유효하지 않은 Geometry {report.invalid}개, 빈 Geometry {report.empty}개가 있습니다",
        )
    extent = conn.execute(
        sql.SQL(
            "SELECT ST_XMin(e), ST_YMin(e), ST_XMax(e), ST_YMax(e) FROM (SELECT ST_Extent({}) AS e FROM {} WHERE {}) t"
        ).format(transform_crs(geom, srid, MAP_OUTPUT_SRID), view.table, where),
        params,
    ).fetchone()
    return BoundaryView(
        metadata=metadata,
        filter=view.filter,
        row_count=len(units),
        region=region,
        key_field=key_field,
        srid=srid,
        units=units,
        invalid_geometry_count=report.invalid,
        empty_geometry_count=report.empty,
        bbox=list(extent),
    )


def validate_geometry(conn: psycopg.Connection, view: DatasetView) -> GeometryReport:
    geom = sql.Identifier(view.metadata.geometry_column.name)
    where, params = view.where()
    invalid, empty = conn.execute(
        sql.SQL(
            "SELECT count(*) FILTER (WHERE NOT ST_IsValid({g})), count(*) FILTER (WHERE ST_IsEmpty({g})) "
            "FROM {t} WHERE {w}"
        ).format(g=geom, t=view.table, w=where),
        params,
    ).fetchone()
    return GeometryReport(invalid=invalid, empty=empty)


def aggregate_by_area(
    conn: psycopg.Connection,
    view: DatasetView,
    boundary: BoundaryView,
    aggregation: str,
    name: str,
) -> MetricValues:
    """Point를 경계 Polygon 단위로 집계한다. 경계선 위 점은 단위 키가 작은 Polygon 하나에만 배정한다.

    CRS 정책: 위상 연산이므로 Point를 경계 Dataset의 CRS로 변환해서 비교한다.
    """
    if aggregation != AggregationFunction.COUNT:
        raise GisToolError("UNSUPPORTED_AGGREGATION", f"aggregate_by_area는 '{aggregation}' 집계를 지원하지 않습니다")
    metadata = view.metadata
    geometry_column = metadata.geometry_column
    if geometry_column is None:
        raise GisToolError("NO_GEOMETRY", f"'{metadata.dataset_id}'에 Geometry가 없습니다")
    if metadata.spatial.geometry_type != GeometryType.POINT:
        raise GisToolError("NOT_POINT", f"'{metadata.dataset_id}'는 Point Dataset이 아닙니다")
    point_geom = transform_crs(sql.Identifier(geometry_column.name), _srid(metadata), boundary.srid)

    boundary_where, boundary_params = boundary.where()
    point_where, point_params = view.where()
    query = sql.SQL(
        """
        WITH units AS NOT MATERIALIZED (
            SELECT {key}::text AS unit_key, {boundary_geom} AS geom FROM {boundary_table} WHERE {boundary_where}
        ),
        points AS NOT MATERIALIZED (
            SELECT ctid AS point_id, {point_geom} AS geom FROM {point_table} WHERE {point_where}
        ),
        assigned AS (
            SELECT DISTINCT ON (p.point_id) p.point_id, u.unit_key
            FROM points p JOIN units u ON ST_Covers(u.geom, p.geom)
            ORDER BY p.point_id, u.unit_key
        )
        SELECT u.unit_key, count(a.point_id) FROM units u LEFT JOIN assigned a USING (unit_key) GROUP BY u.unit_key
        """
    ).format(
        key=sql.Identifier(boundary.key_field),
        boundary_geom=sql.Identifier(boundary.metadata.geometry_column.name),
        boundary_table=boundary.table,
        boundary_where=boundary_where,
        point_geom=point_geom,
        point_table=view.table,
        point_where=point_where,
    )
    values = dict(conn.execute(query, boundary_params + point_params).fetchall())
    assigned = sum(values.values())
    return MetricValues(
        name=name,
        values=values,
        stats={
            "input_points": view.row_count,
            "assigned_points": assigned,
            "unassigned_points": view.row_count - assigned,
        },
    )


def aggregate(
    conn: psycopg.Connection,
    view: DatasetView,
    group_by: list[str],
    field_name: str,
    function: AggregationFunction,
    name: str,
) -> MetricValues:
    """속성 Dataset을 그룹 키로 집계한다."""
    metadata = view.metadata
    if len(group_by) != 1:
        raise GisToolError("MULTI_GROUP_UNSUPPORTED", "aggregate는 그룹 키 1개만 지원합니다")
    for column_name in (group_by[0], field_name):
        if metadata.column(column_name) is None:
            raise GisToolError("FIELD_UNKNOWN", f"'{metadata.dataset_id}'에 '{column_name}' 컬럼이 없습니다")
    if function not in _SQL_AGGREGATES:
        raise GisToolError("UNSUPPORTED_AGGREGATION", f"'{function}' 집계는 지원하지 않습니다")
    if function == AggregationFunction.SUM and metadata.column(field_name).data_type not in (
        DataType.INTEGER,
        DataType.FLOAT,
    ):
        raise GisToolError("FIELD_NOT_NUMERIC", f"'{field_name}'은 숫자 컬럼이 아니어서 합계를 낼 수 없습니다")

    where, params = view.where()
    group = sql.Identifier(group_by[0])
    query = sql.SQL("SELECT {g}::text, {f}({v}) FROM {t} WHERE {w} GROUP BY {g}").format(
        g=group, f=sql.SQL(_SQL_AGGREGATES[function]), v=sql.Identifier(field_name), t=view.table, w=where
    )
    values = {key: _number(value) for key, value in conn.execute(query, params).fetchall()}
    return MetricValues(name=name, values=values, stats={"input_rows": view.row_count, "group_count": len(values)})


def calculate_ratio(
    numerator: MetricValues,
    denominator: MetricValues,
    scale: float,
    unit_keys: list[str],
    name: str,
) -> MetricValues:
    """numerator / denominator × scale. 분모가 0이거나 없으면 0으로 바꾸지 않고 null과 사유를 남긴다."""
    values: dict[str, MetricValue] = {}
    reasons: dict[str, str] = {}
    for key in unit_keys:
        top, bottom = numerator.values.get(key), denominator.values.get(key)
        if bottom is None:
            reasons[key] = "denominator_missing"
        elif bottom == 0:
            reasons[key] = "denominator_zero"
        elif top is None:
            reasons[key] = "numerator_missing"
        else:
            value = top / bottom * scale
            if not math.isfinite(value):
                raise GisToolError("NON_FINITE_RESULT", f"{key}: 비율 계산 결과가 유한하지 않습니다")
            values[key] = value
            continue
        values[key] = None
    stats: dict[str, int | float] = {"computed": len(unit_keys) - len(reasons), **Counter(reasons.values())}
    return MetricValues(name=name, values=values, null_reasons=reasons, stats=stats)


def rank(metric: MetricValues, order: SortOrder, unit_keys: list[str], name: str) -> MetricValues:
    """표준 경쟁 순위(1,2,2,4). null 값은 순위에서 제외한다."""
    present = [(key, metric.values[key]) for key in unit_keys if metric.values.get(key) is not None]
    ascending = order == SortOrder.ASC
    present.sort(key=lambda item: (item[1] if ascending else -item[1], item[0]))

    values: dict[str, MetricValue] = {key: None for key in unit_keys}
    reasons = {key: "input_null" for key in unit_keys if metric.values.get(key) is None}
    previous_value, previous_rank = None, 0
    for position, (key, value) in enumerate(present, start=1):
        current = previous_rank if value == previous_value else position
        values[key] = current
        previous_value, previous_rank = value, current
    return MetricValues(
        name=name, values=values, null_reasons=reasons, stats={"ranked": len(present), "excluded_null": len(reasons)}
    )


def create_choropleth_layer(
    conn: psycopg.Connection,
    boundary: BoundaryView,
    rows: list[UnitRow],
    metric: str,
    metric_label: str,
) -> MapLayer:
    """결과 행을 EPSG:4326 GeoJSON FeatureCollection과 분위 구간으로 만든다."""
    bbox = boundary.bbox or []
    if len(bbox) != 4 or not (-180 <= bbox[0] <= bbox[2] <= 180 and -90 <= bbox[1] <= bbox[3] <= 90):
        raise GisToolError("OUTPUT_CRS_INVALID", f"지도 좌표가 경위도 범위를 벗어났습니다: {bbox}")
    where, params = boundary.where()
    geom = transform_crs(sql.Identifier(boundary.metadata.geometry_column.name), boundary.srid, MAP_OUTPUT_SRID)
    geometries = dict(
        conn.execute(
            sql.SQL("SELECT {}::text, ST_AsGeoJSON({}, 6)::json FROM {} WHERE {}").format(
                sql.Identifier(boundary.key_field), geom, boundary.table, where
            ),
            params,
        ).fetchall()
    )

    features = []
    for row in rows:
        geometry = geometries.get(row.key)
        if geometry is None:
            raise GisToolError("GEOMETRY_MISSING", f"{row.key} ({row.name})의 Geometry가 없습니다")
        properties = {"unit_key": row.key, "unit_name": row.name, "parent_name": row.parent_name, **row.values}
        properties["null_reason"] = row.null_reasons.get(metric)
        features.append({"type": "Feature", "id": row.key, "geometry": geometry, "properties": properties})

    values = [row.values[metric] for row in rows if row.values.get(metric) is not None]
    breaks = quantile_breaks(values, QUANTILE_CLASSES)
    return MapLayer(
        type=MapType.CHOROPLETH,
        metric=metric,
        metric_label=metric_label,
        crs=f"EPSG:{MAP_OUTPUT_SRID}",
        classification=Classification(
            method="quantile",
            class_count=len(breaks) + 1 if values else 0,
            breaks=breaks,
            min=min(values, default=None),
            max=max(values, default=None),
        ),
        feature_count=len(features),
        null_count=len(rows) - len(values),
        geojson={"type": "FeatureCollection", "features": features},
    )


def quantile_breaks(values: list[float], classes: int) -> list[float]:
    """분위 경계값(최대 classes-1개). MapLibre step 식에서 '경계값 이상'이 다음 구간이 된다."""
    if not values:
        return []
    ordered = sorted(values)
    breaks: list[float] = []
    for i in range(1, classes):
        candidate = ordered[round(i * (len(ordered) - 1) / classes)]
        if candidate > ordered[0] and (not breaks or candidate > breaks[-1]):
            breaks.append(candidate)
    return breaks


def _count(conn: psycopg.Connection, view: DatasetView) -> int:
    where, params = view.where()
    return conn.execute(sql.SQL("SELECT count(*) FROM {} WHERE {}").format(view.table, where), params).fetchone()[0]


def _srid(metadata: DatasetMetadata) -> int:
    try:
        return parse_srid(metadata.spatial.crs)
    except CrsError as error:
        raise GisToolError("CRS_UNSUPPORTED", f"'{metadata.dataset_id}': {error}") from error


def _number(value: Any) -> MetricValue:
    return float(value) if isinstance(value, Decimal) else value
