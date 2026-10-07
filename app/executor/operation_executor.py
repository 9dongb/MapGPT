"""Operation Executor: 검증된 AnalysisPlan의 Operation을 GIS Tool에 매핑해 순서대로 실행한다."""

import time
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field

import psycopg

from app.domain.catalog import DatasetMetadata
from app.domain.operations import (
    AggregateByAreaOperation,
    AggregateOperation,
    CalculateRatioOperation,
    Operation,
    RankOperation,
)
from app.domain.plan import AnalysisPlan, resolve_region, unit_boundary_candidates
from app.domain.results import BoundaryStats, ExecutionResult, MetricInfo, OperationLog, UnitRow
from app.gis import tools
from app.gis.tools import BoundaryView, DatasetView, GisToolError, MetricValues


@dataclass
class ExecutionContext:
    conn: psycopg.Connection
    plan: AnalysisPlan
    views: dict[str, DatasetView]
    boundary: BoundaryView
    metrics: dict[str, MetricValues] = field(default_factory=dict)  # operation output(result_ref) → 결과
    logs: list[OperationLog] = field(default_factory=list)


def _run_aggregate_by_area(op: AggregateByAreaOperation, ctx: ExecutionContext) -> MetricValues:
    return tools.aggregate_by_area(ctx.conn, ctx.views[op.input], ctx.boundary, op.aggregation, op.output)


def _run_aggregate(op: AggregateOperation, ctx: ExecutionContext) -> MetricValues:
    return tools.aggregate(
        ctx.conn, ctx.views[op.input], op.group_by, op.aggregation.field, op.aggregation.function, op.output
    )


def _run_calculate_ratio(op: CalculateRatioOperation, ctx: ExecutionContext) -> MetricValues:
    return tools.calculate_ratio(
        ctx.metrics[op.numerator], ctx.metrics[op.denominator], op.scale, ctx.boundary.unit_keys, op.output
    )


def _run_rank(op: RankOperation, ctx: ExecutionContext) -> MetricValues:
    return tools.rank(ctx.metrics[op.input], op.order, ctx.boundary.unit_keys, op.output)


HANDLERS: dict[str, Callable[[Operation, ExecutionContext], MetricValues]] = {
    "aggregate_by_area": _run_aggregate_by_area,
    "aggregate": _run_aggregate,
    "calculate_ratio": _run_calculate_ratio,
    "rank": _run_rank,
}


def prepare_context(
    conn: psycopg.Connection, plan: AnalysisPlan, datasets: Mapping[str, DatasetMetadata]
) -> ExecutionContext:
    """load_data 단계: 분석 단위 경계와 (필터가 적용된) Dataset View를 바인딩한다."""
    candidates = unit_boundary_candidates(plan, datasets)
    if len(candidates) != 1:
        raise GisToolError(
            "UNIT_BOUNDARY_MISSING", f"분석 단위 '{plan.analysis_unit}'의 경계 Dataset을 정할 수 없습니다"
        )
    unit_metadata = candidates[0]
    region = resolve_region(plan.region, unit_metadata.spatial.coverage)
    if region is None:
        raise GisToolError("REGION_NOT_COVERED", f"'{plan.region.name}'은 '{unit_metadata.dataset_id}' 범위가 아닙니다")

    boundary = tools.get_boundary(conn, unit_metadata, region)
    views: dict[str, DatasetView] = {unit_metadata.dataset_id: boundary}
    for dataset_id in plan.datasets:
        if dataset_id in views:
            continue
        view = tools.get_dataset(conn, datasets[dataset_id])
        expression = plan.filter_for(dataset_id)
        views[dataset_id] = tools.filter_dataset(conn, view, expression) if expression else view
    return ExecutionContext(conn=conn, plan=plan, views=views, boundary=boundary)


def execute_operations(ctx: ExecutionContext) -> ExecutionResult:
    for index, op in enumerate(ctx.plan.operations):
        started = time.perf_counter()
        metric = HANDLERS[op.type](op, ctx)
        ctx.metrics[op.output] = metric
        ctx.logs.append(
            OperationLog(
                index=index,
                type=op.type,
                output=op.output,
                label=op.label,
                tool=op.type,
                params=op.model_dump(mode="json"),
                stats=metric.stats,
                duration_ms=round((time.perf_counter() - started) * 1000, 2),
            )
        )
    return _assemble(ctx)


def _assemble(ctx: ExecutionContext) -> ExecutionResult:
    """분석 단위 목록을 기준으로 각 metric을 key로 결합한다. 값이 없는 단위는 null과 사유를 남긴다."""
    outputs = [op.output for op in ctx.plan.operations]
    unit_keys = set(ctx.boundary.unit_keys)
    rows = []
    for unit in ctx.boundary.units:
        values = {name: ctx.metrics[name].values.get(unit.key) for name in outputs}
        reasons = {}
        for name in outputs:
            if values[name] is None:
                reasons[name] = ctx.metrics[name].null_reasons.get(unit.key, "no_matching_records")
        rows.append(
            UnitRow(key=unit.key, name=unit.name, parent_name=unit.parent_name, values=values, null_reasons=reasons)
        )

    unmatched = {
        name: sorted(set(ctx.metrics[name].values) - unit_keys)
        for name in outputs
        if set(ctx.metrics[name].values) - unit_keys
    }
    labels = {op.output: (op.label, op.type) for op in ctx.plan.operations}
    return ExecutionResult(
        analysis_unit=ctx.plan.analysis_unit,
        unit_dataset=ctx.boundary.metadata.dataset_id,
        region=ctx.boundary.region,
        analysis_crs=f"EPSG:{ctx.boundary.srid}",
        boundary=BoundaryStats(
            unit_count=len(ctx.boundary.units),
            invalid_geometry_count=ctx.boundary.invalid_geometry_count,
            empty_geometry_count=ctx.boundary.empty_geometry_count,
            bbox=ctx.boundary.bbox,
        ),
        rows=rows,
        metrics=[
            MetricInfo(
                name=name,
                label=labels[name][0],
                operation=labels[name][1],
                null_count=sum(1 for row in rows if row.values[name] is None),
            )
            for name in outputs
        ],
        operations=ctx.logs,
        unmatched_keys=unmatched,
    )
