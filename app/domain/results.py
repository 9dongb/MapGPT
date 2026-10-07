from datetime import date
from typing import Any, Literal

from app.domain.base import StrictModel
from app.domain.catalog import RegionRef
from app.domain.enums import MapType, Severity, SpatialLevel

MetricValue = float | int | None

# 지도 GeoJSON properties에서 지표 이름과 겹치면 안 되는 예약 이름
RESERVED_PROPERTY_NAMES = frozenset({"unit_key", "unit_name", "parent_name", "null_reason"})


class ValidationIssue(StrictModel):
    code: str
    severity: Severity
    message: str
    path: str | None = None


class ValidationReport(StrictModel):
    issues: list[ValidationIssue] = []

    @property
    def errors(self) -> list[ValidationIssue]:
        return [i for i in self.issues if i.severity == Severity.ERROR]

    @property
    def warnings(self) -> list[ValidationIssue]:
        return [i for i in self.issues if i.severity == Severity.WARNING]

    @property
    def ok(self) -> bool:
        return not self.errors


class OperationLog(StrictModel):
    index: int
    type: str
    output: str
    label: str
    tool: str
    params: dict[str, Any]
    stats: dict[str, float | int]
    duration_ms: float


class UnitRow(StrictModel):
    key: str
    name: str
    parent_name: str | None
    values: dict[str, MetricValue]
    null_reasons: dict[str, str] = {}


class MetricInfo(StrictModel):
    name: str
    label: str
    operation: str
    null_count: int


class BoundaryStats(StrictModel):
    unit_count: int
    invalid_geometry_count: int
    empty_geometry_count: int
    bbox: list[float] | None


class ExecutionResult(StrictModel):
    analysis_unit: SpatialLevel
    unit_dataset: str
    region: RegionRef
    analysis_crs: str
    boundary: BoundaryStats
    rows: list[UnitRow]
    metrics: list[MetricInfo]
    operations: list[OperationLog]
    # 분석 단위에 매칭되지 않은 metric key (예: 경계에 없는 인구 행정동 코드)
    unmatched_keys: dict[str, list[str]] = {}


class Classification(StrictModel):
    method: Literal["quantile"]
    class_count: int
    breaks: list[float]
    min: float | None
    max: float | None


class MapLayer(StrictModel):
    type: MapType
    metric: str
    metric_label: str
    crs: str
    classification: Classification
    feature_count: int
    null_count: int
    geojson: dict[str, Any]


class MetricDescription(StrictModel):
    name: str
    label: str
    interpretation: str


class RankingItem(StrictModel):
    rank: int
    unit_key: str
    unit_name: str
    parent_name: str | None
    value: float
    values: dict[str, MetricValue]


class DatasetUsage(StrictModel):
    dataset_id: str
    title: str
    provider: str
    source: str
    license: str | None
    reference_date: date | None


class FinalResponse(StrictModel):
    run_id: str
    result_id: str
    question: str
    summary: str
    metric: MetricDescription
    metric_labels: dict[str, str]  # operation output → label (랭킹 표·툴팁 열 이름)
    rank_metric: str | None  # ranking 순위를 담은 operation output
    ranking: list[RankingItem]
    map_layer: MapLayer
    analysis_method: list[str]
    datasets: list[DatasetUsage]
    assumptions: list[str]
    limitations: list[str]
