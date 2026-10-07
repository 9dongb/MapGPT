"""Plan Validator: LLM이 만든 AnalysisPlan을 실행 전에 결정론적으로 검증한다.

DB 없이 Dataset 메타데이터만으로 판정한다. 오류가 하나라도 있으면 실행하지 않는다.
"""

from collections.abc import Mapping, Sequence
from dataclasses import dataclass

from app.domain.catalog import DatasetMetadata
from app.domain.enums import AggregationFunction, DataType, GeometryType, Severity
from app.domain.operations import (
    AggregateByAreaOperation,
    AggregateOperation,
    CalculateRatioOperation,
    RankOperation,
)
from app.domain.plan import AnalysisPlan, resolve_region, unit_boundary_candidates
from app.domain.policies import POLICIES
from app.domain.results import RESERVED_PROPERTY_NAMES, ValidationIssue, ValidationReport
from app.gis.crs import CrsError, parse_srid
from app.gis.filter_sql import find_filter_problems

_NUMERIC = {DataType.INTEGER, DataType.FLOAT}


@dataclass(frozen=True)
class _Metric:
    operation: str  # 이 metric을 만든 operation type
    index: int


class _PlanChecker:
    def __init__(self, plan: AnalysisPlan, datasets: Mapping[str, DatasetMetadata], selected: Sequence[str]):
        self.plan = plan
        self.datasets = datasets
        self.selected = set(selected)
        self.issues: list[ValidationIssue] = []
        self.metrics: dict[str, _Metric] = {}
        self.unit_boundary: DatasetMetadata | None = None

    def error(self, code: str, message: str, path: str | None = None) -> None:
        self.issues.append(ValidationIssue(code=code, severity=Severity.ERROR, message=message, path=path))

    def warning(self, code: str, message: str, path: str | None = None) -> None:
        self.issues.append(ValidationIssue(code=code, severity=Severity.WARNING, message=message, path=path))

    def known(self, dataset_id: str, path: str) -> DatasetMetadata | None:
        """참조한 Dataset이 카탈로그와 plan.datasets에 모두 있는지 확인한다."""
        if dataset_id not in self.datasets:
            self.error("UNKNOWN_DATASET", f"'{dataset_id}'는 등록된 Dataset이 아닙니다", path)
            return None
        if dataset_id not in self.plan.datasets:
            self.error("DATASET_NOT_DECLARED", f"'{dataset_id}'가 plan.datasets에 선언되지 않았습니다", path)
        return self.datasets[dataset_id]

    def run(self) -> list[ValidationIssue]:
        self.check_datasets()
        self.check_filters()
        for index, op in enumerate(self.plan.operations):
            self.check_operation(index, op)
        self.check_output()
        self.check_policy()
        return self.issues

    def check_datasets(self) -> None:
        for i, dataset_id in enumerate(self.plan.datasets):
            path = f"datasets[{i}]"
            if dataset_id not in self.datasets:
                self.error("UNKNOWN_DATASET", f"'{dataset_id}'는 등록된 Dataset이 아닙니다", path)
                continue
            if dataset_id not in self.selected:
                self.error("DATASET_NOT_SELECTED", f"'{dataset_id}'는 선택 단계에서 고른 Dataset이 아닙니다", path)
            metadata = self.datasets[dataset_id]
            coverage = metadata.spatial.coverage
            if resolve_region(self.plan.region, coverage) is None:
                where = f"'{coverage.name}'({coverage.level})" if coverage else "지정되지 않은 지역"
                self.error(
                    "REGION_NOT_COVERED",
                    f"분석 지역 '{self.plan.region.name}'({self.plan.region.level})은 '{dataset_id}'의 범위({where})가 아닙니다",
                    "region",
                )
            if metadata.geometry_column is not None:
                try:
                    parse_srid(metadata.spatial.crs)
                except CrsError as error:
                    self.error("CRS_UNSUPPORTED", f"'{dataset_id}': {error}", path)

        candidates = unit_boundary_candidates(self.plan, self.datasets)
        if not candidates:
            self.error(
                "UNIT_BOUNDARY_MISSING",
                f"분석 단위 '{self.plan.analysis_unit}'의 Polygon 경계 Dataset이 plan.datasets에 없습니다",
                "analysis_unit",
            )
        elif len(candidates) > 1:
            self.error(
                "UNIT_BOUNDARY_AMBIGUOUS",
                f"분석 단위 경계 Dataset이 여러 개입니다: {[d.dataset_id for d in candidates]}",
                "datasets",
            )
        else:
            self.unit_boundary = candidates[0]

        used = {f.dataset for f in self.plan.filters}
        for op in self.plan.operations:
            if isinstance(op, AggregateByAreaOperation):
                used |= {op.input, op.boundary}
            elif isinstance(op, AggregateOperation):
                used.add(op.input)
        for i, dataset_id in enumerate(self.plan.datasets):
            if dataset_id not in used and not (self.unit_boundary and dataset_id == self.unit_boundary.dataset_id):
                self.warning(
                    "UNUSED_DATASET", f"'{dataset_id}'는 어떤 operation에서도 쓰이지 않습니다", f"datasets[{i}]"
                )

    def check_filters(self) -> None:
        seen: set[str] = set()
        for i, dataset_filter in enumerate(self.plan.filters):
            path = f"filters[{i}]"
            metadata = self.known(dataset_filter.dataset, f"{path}.dataset")
            if metadata is None:
                continue
            if dataset_filter.dataset in seen:
                self.error("DUPLICATE_FILTER", f"'{dataset_filter.dataset}'에 필터가 두 번 정의되었습니다", path)
            seen.add(dataset_filter.dataset)
            if self.unit_boundary and dataset_filter.dataset == self.unit_boundary.dataset_id:
                self.error(
                    "BOUNDARY_FILTER_UNSUPPORTED",
                    "분석 단위 경계 Dataset에는 필터를 둘 수 없습니다. 지역 범위는 region으로 지정하세요",
                    path,
                )
            for problem in find_filter_problems(dataset_filter.where, metadata):
                self.error(problem.code, problem.message, f"{path}.where")

    def check_operation(self, index: int, op) -> None:
        path = f"operations[{index}]"
        if isinstance(op, AggregateByAreaOperation):
            self.check_aggregate_by_area(op, path)
        elif isinstance(op, AggregateOperation):
            self.check_aggregate(op, path)
        elif isinstance(op, CalculateRatioOperation):
            self.check_ratio(op, path)
        elif isinstance(op, RankOperation):
            self.require_metric(op.input, f"{path}.input")

        conflict = (
            op.output in self.metrics
            or op.output in self.datasets
            or op.output in RESERVED_PROPERTY_NAMES
            or (self.unit_boundary is not None and self.unit_boundary.column(op.output) is not None)
        )
        if conflict:
            self.error("OUTPUT_NAME_CONFLICT", f"output 이름 '{op.output}'이 다른 이름과 충돌합니다", f"{path}.output")
        else:
            self.metrics[op.output] = _Metric(operation=op.type, index=index)

    def check_aggregate_by_area(self, op: AggregateByAreaOperation, path: str) -> None:
        points = self.known(op.input, f"{path}.input")
        boundary = self.known(op.boundary, f"{path}.boundary")
        if points is not None:
            if points.geometry_column is None:
                self.error(
                    "GEOMETRY_REQUIRED", f"'{op.input}'에 Geometry가 없어 공간 집계할 수 없습니다", f"{path}.input"
                )
            elif points.spatial.geometry_type != GeometryType.POINT:
                self.error("GEOMETRY_TYPE_INVALID", f"'{op.input}'는 Point Dataset이 아닙니다", f"{path}.input")
        if boundary is not None:
            if not boundary.is_polygon:
                self.error("GEOMETRY_TYPE_INVALID", f"'{op.boundary}'는 Polygon Dataset이 아닙니다", f"{path}.boundary")
            elif self.unit_boundary is not None and op.boundary != self.unit_boundary.dataset_id:
                self.error(
                    "BOUNDARY_NOT_ANALYSIS_UNIT",
                    f"'{op.boundary}'는 분석 단위 경계('{self.unit_boundary.dataset_id}')가 아닙니다",
                    f"{path}.boundary",
                )

    def check_aggregate(self, op: AggregateOperation, path: str) -> None:
        metadata = self.known(op.input, f"{path}.input")
        if metadata is None:
            return
        if len(op.group_by) != 1:
            self.error("JOIN_KEY_INCOMPATIBLE", "group_by는 분석 단위 join key 1개여야 합니다", f"{path}.group_by")
        else:
            self.check_join_key(metadata, op.group_by[0], f"{path}.group_by[0]")
        column = metadata.column(op.aggregation.field)
        if column is None:
            self.error(
                "FIELD_UNKNOWN", f"'{op.input}'에 '{op.aggregation.field}' 컬럼이 없습니다", f"{path}.aggregation"
            )
        elif op.aggregation.function == AggregationFunction.SUM and column.data_type not in _NUMERIC:
            self.error("FIELD_NOT_NUMERIC", f"'{column.name}'은 숫자 컬럼이 아닙니다", f"{path}.aggregation")

    def check_join_key(self, metadata: DatasetMetadata, field: str, path: str) -> None:
        if metadata.column(field) is None:
            self.error("FIELD_UNKNOWN", f"'{metadata.dataset_id}'에 '{field}' 컬럼이 없습니다", path)
            return
        if self.unit_boundary is None:
            return
        key = metadata.join_key(field)
        compatible = (
            key is not None
            and metadata.spatial.level == self.plan.analysis_unit
            and any(
                k.semantic_type == key.semantic_type and k.code_system == key.code_system
                for k in self.unit_boundary.join_keys
            )
        )
        if not compatible:
            self.error(
                "JOIN_KEY_INCOMPATIBLE",
                f"'{metadata.dataset_id}.{field}'는 분석 단위 경계('{self.unit_boundary.dataset_id}')와 결합할 수 있는 키가 아닙니다",
                path,
            )

    def check_ratio(self, op: CalculateRatioOperation, path: str) -> None:
        numerator = self.require_metric(op.numerator, f"{path}.numerator")
        denominator = self.require_metric(op.denominator, f"{path}.denominator")
        if op.numerator == op.denominator:
            self.error("RATIO_OPERAND_INVALID", "분자와 분모가 같습니다", path)
        for metric, name in ((numerator, "numerator"), (denominator, "denominator")):
            if metric is not None and metric.operation == "rank":
                self.error(
                    "RATIO_OPERAND_INVALID", "순위(rank) 결과는 비율의 피연산자가 될 수 없습니다", f"{path}.{name}"
                )

    def require_metric(self, name: str, path: str) -> _Metric | None:
        metric = self.metrics.get(name)
        if metric is None:
            self.error("OPERATION_INPUT_UNKNOWN", f"'{name}'은 앞에서 계산된 operation output이 아닙니다", path)
        return metric

    def check_output(self) -> None:
        output = self.plan.output
        producer = self.metrics.get(output.metric)
        if producer is None:
            self.error(
                "OUTPUT_METRIC_NOT_COMPUTED",
                f"output.metric '{output.metric}'을 계산하는 operation이 없습니다",
                "output.metric",
            )
        elif producer.operation == "rank":
            ranked = self.plan.operations[producer.index].input
            self.error(
                "OUTPUT_METRIC_IS_RANK",
                f"output.metric '{output.metric}'은 순위(rank) 결과입니다. 지도에는 순위를 매긴 지표 '{ranked}'를 써야 합니다",
                "output.metric",
            )
        elif output.ranking.enabled and not self._rank_of(output.metric):
            self.error("RANKING_NOT_DEFINED", f"'{output.metric}'에 대한 rank operation이 없습니다", "output.ranking")

    def check_policy(self) -> None:
        policy = POLICIES.get(self.plan.intent)
        if policy is None:
            return
        metric = self.plan.output.metric
        ratio = next(
            (op for op in self.plan.operations if isinstance(op, CalculateRatioOperation) and op.output == metric),
            None,
        )
        if ratio is None or ratio.scale != policy.ratio_scale:
            self.error(
                "POLICY_VIOLATION",
                f"'{policy.title}' 정책: output.metric은 scale {policy.ratio_scale:g}인 calculate_ratio 결과여야 합니다",
                "output.metric",
            )
        rank_op = self._rank_of(metric)
        if not self.plan.output.ranking.enabled or rank_op is None or rank_op.order != policy.rank_order:
            self.error(
                "POLICY_VIOLATION",
                f"'{policy.title}' 정책: output.metric에 대해 {policy.rank_order} 순위를 매기고 ranking을 켜야 합니다",
                "output.ranking",
            )

    def _rank_of(self, metric: str) -> RankOperation | None:
        return next((op for op in self.plan.operations if isinstance(op, RankOperation) and op.input == metric), None)


def validate_plan(
    plan: AnalysisPlan, datasets: Mapping[str, DatasetMetadata], selected: Sequence[str]
) -> ValidationReport:
    return ValidationReport(issues=_PlanChecker(plan, datasets, selected).run())
