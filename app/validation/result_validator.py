"""Result Validator: 실행 결과를 지도·설명으로 넘기기 전에 결정론적으로 검증한다."""

import math
from collections.abc import Mapping

from app.domain.catalog import DatasetMetadata
from app.domain.enums import AggregationFunction, SemanticType, Severity
from app.domain.operations import AggregateByAreaOperation, AggregateOperation, CalculateRatioOperation
from app.domain.plan import AnalysisPlan
from app.domain.results import ExecutionResult, ValidationIssue, ValidationReport

MAX_NULL_RATE = 0.2  # output metric의 null 비율이 이를 넘으면 결합 실패로 본다
UNIT_COUNT_TOLERANCE = 0.1  # 예상 단위 수 대비 허용 오차
BBOX_TOLERANCE = 0.01  # degree
_EXAMPLES = 5
_NULL_REASONS = {
    "denominator_zero": "분모 0",
    "denominator_missing": "분모 자료 없음",
    "numerator_missing": "분자 자료 없음",
    "no_matching_records": "자료 없음",
    "input_null": "입력 값 없음",
}


def validate_result(
    result: ExecutionResult, plan: AnalysisPlan, datasets: Mapping[str, DatasetMetadata]
) -> ValidationReport:
    issues: list[ValidationIssue] = []

    def error(code: str, message: str) -> None:
        issues.append(ValidationIssue(code=code, severity=Severity.ERROR, message=message))

    def warning(code: str, message: str) -> None:
        issues.append(ValidationIssue(code=code, severity=Severity.WARNING, message=message))

    rows = result.rows
    if not rows:
        error("RESULT_EMPTY", "분석 결과가 비어 있습니다")
        return ValidationReport(issues=issues)

    keys = [row.key for row in rows]
    if len(set(keys)) != len(keys):
        error("DUPLICATE_UNITS", "결과에 중복된 분석 단위가 있습니다")
    if result.boundary.invalid_geometry_count or result.boundary.empty_geometry_count:
        error("INVALID_GEOMETRY", "분석 단위 경계에 유효하지 않거나 빈 Geometry가 있습니다")

    for name in _count_like_metrics(plan, datasets):
        negative = [row.name for row in rows if (row.values.get(name) or 0) < 0]
        if negative:
            error("NEGATIVE_VALUE", f"'{name}'에 음수 값이 있습니다: {negative[:_EXAMPLES]}")

    for op in plan.operations:
        if isinstance(op, CalculateRatioOperation):
            unhandled = [
                row.name
                for row in rows
                if row.values.get(op.denominator) in (0, None)
                and (row.values.get(op.output) is not None or op.output not in row.null_reasons)
            ]
            if unhandled:
                error(
                    "ZERO_DENOMINATOR_UNHANDLED",
                    f"'{op.output}': 분모가 0이거나 없는데 값이 있습니다: {unhandled[:_EXAMPLES]}",
                )

    non_finite = [
        f"{row.name}.{name}"
        for row in rows
        for name, value in row.values.items()
        if isinstance(value, float) and not math.isfinite(value)
    ]
    if non_finite:
        error("NON_FINITE_VALUE", f"NaN/Infinity 값이 있습니다: {non_finite[:_EXAMPLES]}")

    metric = plan.output.metric
    missing = [row for row in rows if row.values.get(metric) is None]
    if len(missing) / len(rows) > MAX_NULL_RATE:
        error(
            "HIGH_NULL_RATE",
            f"'{metric}' 값이 없는 단위가 {len(missing)}/{len(rows)}개로 너무 많습니다 (데이터 결합 실패 가능성)",
        )
    elif missing:
        examples = ", ".join(
            f"{row.name}({_NULL_REASONS.get(row.null_reasons.get(metric), '사유 미상')})" for row in missing[:_EXAMPLES]
        )
        warning("NULL_VALUES", f"'{metric}' 값을 계산할 수 없는 행정동 {len(missing)}개는 순위에서 제외: {examples}")

    unit_metadata = datasets[result.unit_dataset]
    expected_bbox, actual_bbox = unit_metadata.spatial.bbox, result.boundary.bbox
    if expected_bbox is None or actual_bbox is None:
        warning("REGION_CHECK_SKIPPED", "범위(bbox) 정보가 없어 지역 범위 검증을 건너뜁니다")
    elif not _within(actual_bbox, expected_bbox):
        error("OUT_OF_REGION", f"결과 범위 {actual_bbox}가 '{result.region.name}' 범위 {expected_bbox}를 벗어납니다")

    expected_units = unit_metadata.spatial.feature_count
    if expected_units is None:
        warning("UNIT_COUNT_CHECK_SKIPPED", "예상 행정동 수 정보가 없어 단위 수 검증을 건너뜁니다")
    elif abs(len(rows) - expected_units) > expected_units * UNIT_COUNT_TOLERANCE:
        error("UNIT_COUNT_MISMATCH", f"결과 행정동 수 {len(rows)}개가 예상 {expected_units}개와 크게 다릅니다")
    elif len(rows) != expected_units:
        warning("UNIT_COUNT_MISMATCH", f"결과 행정동 수 {len(rows)}개가 예상 {expected_units}개와 다릅니다")

    for name, unmatched in result.unmatched_keys.items():
        warning(
            "UNMATCHED_KEYS",
            f"'{name}' 계산에 쓰인 코드 {len(unmatched)}개가 분석 단위 경계에 없어 제외: {unmatched[:_EXAMPLES]}",
        )
    for log in result.operations:
        unassigned = log.stats.get("unassigned_points", 0)
        if unassigned:
            warning("UNASSIGNED_POINTS", f"'{log.output}': 분석 지역 경계 밖의 점 {unassigned}개는 집계에서 제외")

    return ValidationReport(issues=issues)


def _count_like_metrics(plan: AnalysisPlan, datasets: Mapping[str, DatasetMetadata]) -> list[str]:
    """개수 또는 인구 합계처럼 음수가 될 수 없는 metric."""
    names = []
    for op in plan.operations:
        if isinstance(op, AggregateByAreaOperation):
            names.append(op.output)
        elif isinstance(op, AggregateOperation):
            column = datasets[op.input].column(op.aggregation.field)
            if op.aggregation.function == AggregationFunction.COUNT or (
                column is not None and column.semantic_type == SemanticType.POPULATION
            ):
                names.append(op.output)
    return names


def _within(inner: list[float], outer: list[float]) -> bool:
    return (
        inner[0] >= outer[0] - BBOX_TOLERANCE
        and inner[1] >= outer[1] - BBOX_TOLERANCE
        and inner[2] <= outer[2] + BBOX_TOLERANCE
        and inner[3] <= outer[3] + BBOX_TOLERANCE
    )
