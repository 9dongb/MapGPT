"""최종 응답 조립. LLM은 summary만 쓰고, 나머지 섹션은 실행 기록에서 결정론적으로 만든다."""

import statistics
from collections.abc import Mapping
from typing import Any

from app.domain.catalog import DatasetMetadata
from app.domain.enums import FilterOperator, LogicalOperator, SortOrder
from app.domain.filters import FilterCondition, FilterExpression
from app.domain.operations import (
    AggregateByAreaOperation,
    AggregateOperation,
    CalculateRatioOperation,
    Operation,
    RankOperation,
)
from app.domain.plan import AnalysisPlan
from app.domain.policies import POLICIES
from app.domain.results import (
    DatasetUsage,
    ExecutionResult,
    FinalResponse,
    MapLayer,
    MetricDescription,
    RankingItem,
    ValidationReport,
)
from app.domain.state import InterpretedQuery

_SYMBOLS = {
    FilterOperator.EQ: "=",
    FilterOperator.NEQ: "≠",
    FilterOperator.GT: ">",
    FilterOperator.GTE: "≥",
    FilterOperator.LT: "<",
    FilterOperator.LTE: "≤",
}
_LEVEL_NAMES = {"sido": "시도", "sigungu": "시군구", "emd": "행정동"}


def compose_response(
    *,
    run_id: str,
    result_id: str,
    question: str,
    interpreted: InterpretedQuery,
    plan: AnalysisPlan,
    datasets: Mapping[str, DatasetMetadata],
    result: ExecutionResult,
    result_validation: ValidationReport,
    map_layer: MapLayer,
    summary: str = "",
) -> FinalResponse:
    policy = POLICIES[plan.intent]
    metric_op = _producer(plan, plan.output.metric)
    rank_op = next(
        (op for op in plan.operations if isinstance(op, RankOperation) and op.input == plan.output.metric), None
    )
    used = [datasets[d] for d in plan.datasets]
    return FinalResponse(
        run_id=run_id,
        result_id=result_id,
        question=question,
        summary=summary,
        metric=MetricDescription(name=plan.output.metric, label=metric_op.label, interpretation=policy.interpretation),
        metric_labels={op.output: op.label for op in plan.operations},
        rank_metric=rank_op.output if rank_op else None,
        ranking=_ranking(plan, result, rank_op),
        map_layer=map_layer,
        analysis_method=_method(plan, datasets, result),
        datasets=[
            DatasetUsage(
                dataset_id=d.dataset_id,
                title=d.title,
                provider=d.provider,
                source=d.source,
                license=d.license,
                reference_date=d.temporal.reference_date,
            )
            for d in used
        ],
        assumptions=_dedupe([*policy.definitions, *interpreted.assumptions]),
        limitations=_dedupe(
            [
                *policy.limitations,
                *_temporal_note(used),
                *(f"[{d.title}] {note}" for d in used for note in d.quality_notes),
                *(issue.message for issue in result_validation.warnings),
            ]
        ),
    )


def explanation_facts(response: FinalResponse, plan: AnalysisPlan, result: ExecutionResult) -> dict[str, Any]:
    """설명 LLM에 넘길 사실. 여기에 없는 수치는 설명에 쓰지 않도록 지시한다."""
    labels = response.metric_labels
    values = [row.values[plan.output.metric] for row in result.rows if row.values[plan.output.metric] is not None]
    return {
        "question": response.question,
        "metric": response.metric.model_dump(),
        "ranking_top": [
            {
                "rank": item.rank,
                "자치구": item.parent_name,
                "행정동": item.unit_name,
                "value": round(item.value, 2),
                "components": {
                    labels[name]: value for name, value in item.values.items() if name != plan.output.metric
                },
            }
            for item in response.ranking
        ],
        "summary_stats": {
            "unit_count": len(result.rows),
            "units_with_value": len(values),
            "min": round(min(values), 2) if values else None,
            "median": round(statistics.median(values), 2) if values else None,
            "max": round(max(values), 2) if values else None,
        },
        "datasets": [d.model_dump(mode="json", include={"title", "reference_date"}) for d in response.datasets],
        "limitations": response.limitations,
    }


def _producer(plan: AnalysisPlan, output: str) -> Operation:
    return next(op for op in plan.operations if op.output == output)


def _ranking(plan: AnalysisPlan, result: ExecutionResult, rank_op: RankOperation | None) -> list[RankingItem]:
    if not plan.output.ranking.enabled or rank_op is None:
        return []
    metric = plan.output.metric
    ranked = sorted(
        (row for row in result.rows if row.values[rank_op.output] is not None),
        key=lambda row: (row.values[rank_op.output], row.key),
    )
    return [
        RankingItem(
            rank=row.values[rank_op.output],
            unit_key=row.key,
            unit_name=row.name,
            parent_name=row.parent_name,
            value=row.values[metric],
            values=row.values,
        )
        for row in ranked[: plan.output.ranking.limit]
    ]


def _method(plan: AnalysisPlan, datasets: Mapping[str, DatasetMetadata], result: ExecutionResult) -> list[str]:
    def title(dataset_id: str) -> str:
        return f"{datasets[dataset_id].title}({dataset_id})"

    steps = [
        f"분석 범위: {plan.region.name} {_LEVEL_NAMES[plan.analysis_unit]} {len(result.rows)}개 "
        f"(공간 연산 CRS {result.analysis_crs}, 지도 출력 EPSG:4326)"
    ]
    steps += [f"필터 — {title(f.dataset)}: {_render_filter(f.where)}" for f in plan.filters]
    for op in plan.operations:
        if isinstance(op, AggregateByAreaOperation):
            steps.append(
                f"{op.label}({op.output}): {title(op.input)}의 위치를 {title(op.boundary)}와 공간 결합(점이 경계 안에 "
                "포함되는지 판정)해 단위별 개수를 셈. 경계선 위의 점은 한 단위에만 배정"
            )
        elif isinstance(op, AggregateOperation):
            kind = "합계" if op.aggregation.function == "sum" else "개수"
            steps.append(
                f"{op.label}({op.output}): {title(op.input)}의 {op.aggregation.field} {kind}를 "
                f"{', '.join(op.group_by)} 기준으로 집계"
            )
        elif isinstance(op, CalculateRatioOperation):
            steps.append(
                f"{op.label}({op.output}) = {op.numerator} ÷ {op.denominator} × {op.scale:,g}. "
                "분모가 0이거나 없으면 값 없음(null)으로 두고 순위에서 제외"
            )
        elif isinstance(op, RankOperation):
            direction = "오름차순(값이 작을수록 1위)" if op.order == SortOrder.ASC else "내림차순(값이 클수록 1위)"
            steps.append(f"{op.label}({op.output}): {op.input}을 {direction}으로 순위화. 같은 값은 같은 순위")
    return steps


def _render_filter(expression: FilterExpression) -> str:
    if isinstance(expression, FilterCondition):
        return _render_condition(expression)
    parts = [_render_condition(c) for c in expression.conditions]
    if expression.logic == LogicalOperator.NOT:
        return f"NOT ({parts[0]})"
    return (" 그리고 " if expression.logic == LogicalOperator.AND else " 또는 ").join(parts)


def _render_condition(c: FilterCondition) -> str:
    op, value = c.operator, c.value
    if op in _SYMBOLS:
        return f"{c.field} {_SYMBOLS[op]} {value}"
    if op == FilterOperator.BETWEEN:
        return f"{c.field} {value[0]}~{value[1]}"
    if op == FilterOperator.IN:
        return f"{c.field} ∈ {value}"
    if op == FilterOperator.NOT_IN:
        return f"{c.field} ∉ {value}"
    if op == FilterOperator.CONTAINS:
        return f"{c.field}에 '{value}' 포함"
    if op == FilterOperator.STARTS_WITH:
        return f"{c.field}가 '{value}'로 시작"
    return f"{c.field} 값 {'없음' if op == FilterOperator.IS_NULL else '있음'}"


def _temporal_note(datasets: list[DatasetMetadata]) -> list[str]:
    dates = {d.temporal.reference_date for d in datasets if d.temporal.reference_date}
    if len(dates) <= 1:
        return []
    detail = ", ".join(f"{d.title} {d.temporal.reference_date}" for d in datasets if d.temporal.reference_date)
    return [f"Dataset 기준 시점이 서로 다릅니다: {detail}"]


def _dedupe(items: list[str]) -> list[str]:
    return list(dict.fromkeys(items))
