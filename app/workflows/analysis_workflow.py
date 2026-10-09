"""분석 Orchestrator: LangGraph StateGraph로 구성한 단일 Agent 워크플로.

interpret_query → select_datasets → build_analysis_plan ⇄ validate_plan (재생성 1회)
→ load_data → execute_operations → validate_result → create_map_layer → generate_explanation

- 그래프 상태는 Provenance로 저장하는 AgentState 그대로다. LLM·카탈로그·DB 세션은 실행마다 Runtime context로 주입한다.
- 노드 안의 실패는 errors에 기록되고 조건부 엣지가 END로 보낸다. 그래서 실행 기록은 성공이든 실패든 항상 저장된다.
- LangGraph 의존은 이 모듈에만 둔다 (전달 문서 25번: Core Domain·GIS Logic이 Agent Framework에 종속되지 않게).
"""

import logging
import uuid
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

import psycopg
from langgraph.graph import END, START, StateGraph
from langgraph.graph.state import CompiledStateGraph
from langgraph.runtime import Runtime
from psycopg_pool import ConnectionPool

from app.agents import steps
from app.catalog.catalog import CatalogIndexError, DatasetCatalog
from app.domain.catalog import DatasetMetadata
from app.domain.enums import SPATIAL_LEVEL_NAMES, RunStatus, Severity, SpatialLevel, WorkflowStep
from app.domain.plan import AnalysisPlan, analysis_units, resolve_region
from app.domain.results import ValidationIssue, ValidationReport
from app.domain.state import AgentState, DatasetHit, DatasetSearch, InterpretedQuery, PlanAttempt, WorkflowError
from app.executor.operation_executor import ExecutionContext, execute_operations, prepare_context
from app.gis.tools import GisToolError, create_choropleth_layer
from app.llm.base import LLMError, LLMOutputError, StructuredLLM
from app.llm.embeddings import Embedder, EmbeddingError
from app.repositories.run_repository import save_run
from app.validation.plan_validator import validate_plan
from app.validation.result_validator import validate_result
from app.workflows.response import compose_response, explanation_facts

logger = logging.getLogger(__name__)

MAX_PLAN_ATTEMPTS = 2  # 최초 생성 + 검증 오류 피드백 후 재생성 1회

Update = dict[str, Any]  # 노드가 돌려주는 AgentState 부분 갱신


class WorkflowFailure(Exception):
    def __init__(self, code: str, message: str, issues: list[ValidationIssue] | None = None):
        super().__init__(message)
        self.code = code
        self.issues = issues or []


class _GisSession:
    """load_data ~ create_map_layer가 함께 쓰는 읽기 전용 트랜잭션 (REPEATABLE READ: 단계 사이 데이터 일관성)."""

    def __init__(self, pool: ConnectionPool):
        self._pool = pool
        self.conn: psycopg.Connection | None = None
        self.context: ExecutionContext | None = None

    def begin(self) -> psycopg.Connection:
        self.conn = self._pool.getconn()
        self.conn.execute("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ, READ ONLY")
        return self.conn

    def release(self) -> None:
        if self.conn is not None:
            self.conn.rollback()
            self._pool.putconn(self.conn)
            self.conn = None


@dataclass(frozen=True)
class _RunContext:
    """LangGraph Runtime context: 실행마다 주입하는 의존성. Provenance로 남길 값은 그래프 상태에 둔다."""

    llm: StructuredLLM
    catalog: DatasetCatalog
    gis: _GisSession


class AnalysisWorkflow:
    def __init__(self, llm: StructuredLLM, pool: ConnectionPool, embedder: Embedder):
        self._llm = llm
        self._pool = pool
        self._catalog = DatasetCatalog(pool, embedder)

    def run(self, question: str) -> AgentState:
        initial = AgentState(
            run_id=str(uuid.uuid4()),
            question=question,
            llm_provider=self._llm.provider,
            llm_model=self._llm.model,
            started_at=datetime.now(UTC),
        )
        gis = _GisSession(self._pool)
        try:
            values = ANALYSIS_GRAPH.invoke(initial, context=_RunContext(llm=self._llm, catalog=self._catalog, gis=gis))
        finally:
            gis.release()  # create_map_layer 전에 실패로 끝났을 때
        state = AgentState.model_validate(values)
        state.status = RunStatus.FAILED if state.errors else RunStatus.SUCCEEDED
        state.finished_at = datetime.now(UTC)
        with self._pool.connection() as conn:
            save_run(conn, state)
        return state


# ── LLM 단계 ──────────────────────────────────────────────────────────────
# 단계 함수는 update에 결과를 기록하고, 실패하면 WorkflowFailure를 던진다 (_node 참고).


def _interpret_query(state: AgentState, ctx: _RunContext, update: Update) -> None:
    datasets = ctx.catalog.list_all()
    regions = list({d.spatial.coverage.name: d.spatial.coverage for d in datasets if d.spatial.coverage}.values())
    coverage = [(region, analysis_units(datasets, region)) for region in regions]
    interpreted = _llm_call(steps.interpret_query, ctx.llm, state.question, coverage)
    update["interpreted_query"] = interpreted
    if interpreted.intent is None:
        raise WorkflowFailure("UNSUPPORTED_QUESTION", interpreted.unsupported_reason or "지원하지 않는 분석 질문입니다")
    if interpreted.region is None or interpreted.analysis_unit is None:
        raise WorkflowFailure("INCOMPLETE_INTERPRETATION", "분석 지역 또는 분석 단위를 해석하지 못했습니다")
    if not any(resolve_region(interpreted.region, r) for r in regions):
        # 지역은 이름과 단위가 모두 맞아야 하므로 둘 다 보여준다 (예: '서울특별시'(emd) vs 서울특별시(sido)).
        supported = ", ".join(f"{r.name}({r.level})" for r in regions)
        raise WorkflowFailure(
            "REGION_NOT_SUPPORTED",
            f"'{interpreted.region.name}'({interpreted.region.level}) 데이터가 없습니다. 분석 가능한 지역: {supported}",
        )
    # 경계 데이터가 없는 단위는 계획을 만들어도 검증에서 실패하므로 LLM을 더 부르기 전에 끝낸다.
    units = analysis_units(datasets, interpreted.region)
    if interpreted.analysis_unit not in units:
        available = ", ".join(_unit_name(u) for u in units) or "없음"
        raise WorkflowFailure(
            "UNIT_NOT_SUPPORTED",
            f"'{interpreted.region.name}'에는 {_unit_name(interpreted.analysis_unit)} 단위 경계 데이터가 없습니다. "
            f"분석 가능한 단위: {available}",
        )


def _select_datasets(state: AgentState, ctx: _RunContext, update: Update) -> None:
    interpreted = state.interpreted_query
    query = " ".join([interpreted.restated_question, *interpreted.key_concepts])
    try:
        hits = ctx.catalog.search(query)
    except CatalogIndexError as error:
        raise WorkflowFailure("CATALOG_INDEX_STALE", str(error)) from error
    except EmbeddingError as error:
        raise WorkflowFailure("EMBEDDING_FAILED", str(error)) from error
    update["dataset_search"] = DatasetSearch(
        query=query,
        embedding_model=ctx.catalog.embedding_model,
        hits=[DatasetHit(dataset_id=hit.metadata.dataset_id, similarity=round(hit.similarity, 4)) for hit in hits],
    )
    candidates = [hit.metadata for hit in hits]
    update["dataset_candidates"] = candidates
    selection = _llm_call(steps.select_datasets, ctx.llm, interpreted, candidates)
    update["dataset_selection"] = selection  # 검사 전에 기록해 잘못된 선택도 추적할 수 있게 한다
    candidate_ids = {d.dataset_id for d in candidates}
    unknown = [d for d in selection.datasets if d not in candidate_ids]
    if unknown or not selection.datasets:
        raise WorkflowFailure("INVALID_DATASET_SELECTION", f"후보에 없는 Dataset을 선택했습니다: {unknown}")
    update["selected_datasets"] = list(dict.fromkeys(selection.datasets))


def _build_analysis_plan(state: AgentState, ctx: _RunContext, update: Update) -> None:
    feedback = None
    if state.plan_history:
        last = state.plan_history[-1]
        feedback = (last.plan.model_dump(mode="json") if last.plan else None, last.validation.errors)
    try:
        datasets = _candidates(state)
        selected = [datasets[d] for d in state.selected_datasets]
        plan = steps.build_analysis_plan(ctx.llm, state.interpreted_query, selected, feedback)
    except LLMOutputError as error:
        # 스키마를 통과하지 못한 계획은 실행하지 않는다. 오류를 피드백해 재생성을 시도한다.
        report = ValidationReport(
            issues=[ValidationIssue(code="PLAN_SCHEMA_INVALID", severity=Severity.ERROR, message=str(error))]
        )
        _record_plan_attempt(state, update, None, report)
        return
    except LLMError as error:
        raise WorkflowFailure("LLM_FAILED", str(error)) from error
    update["analysis_plan"] = plan


def _validate_plan(state: AgentState, ctx: _RunContext, update: Update) -> None:
    report = validate_plan(state.analysis_plan, _candidates(state), state.selected_datasets)
    report.issues.extend(_consistency_issues(state.interpreted_query, state.analysis_plan))
    _record_plan_attempt(state, update, state.analysis_plan, report)


def _record_plan_attempt(
    state: AgentState, update: Update, plan: AnalysisPlan | None, report: ValidationReport
) -> None:
    history = [*state.plan_history, PlanAttempt(plan=plan, validation=report)]
    update.update(analysis_plan=plan, plan_validation=report, plan_history=history)
    if not report.ok and len(history) >= MAX_PLAN_ATTEMPTS:
        raise WorkflowFailure("PLAN_INVALID", "검증을 통과하는 분석 계획을 만들지 못했습니다", report.errors)


# ── 결정론적 GIS 실행 단계 (하나의 읽기 전용 트랜잭션) ─────────────────────


def _load_data(state: AgentState, ctx: _RunContext, update: Update) -> None:
    conn = ctx.gis.begin()
    ctx.gis.context = _gis_call(prepare_context, conn, state.analysis_plan, _candidates(state))


def _execute_operations(state: AgentState, ctx: _RunContext, update: Update) -> None:
    update["execution_results"] = _gis_call(execute_operations, ctx.gis.context)


def _validate_result(state: AgentState, ctx: _RunContext, update: Update) -> None:
    report = validate_result(state.execution_results, state.analysis_plan, _candidates(state))
    update["result_validation"] = report
    if not report.ok:
        raise WorkflowFailure("RESULT_INVALID", "분석 결과가 검증을 통과하지 못했습니다", report.errors)


def _create_map_layer(state: AgentState, ctx: _RunContext, update: Update) -> None:
    plan = state.analysis_plan
    label = next(op.label for op in plan.operations if op.output == plan.output.metric)
    update["map_layer"] = _gis_call(
        create_choropleth_layer,
        ctx.gis.conn,
        ctx.gis.context.boundary,
        state.execution_results.rows,
        plan.output.metric,
        label,
    )
    ctx.gis.release()


def _generate_explanation(state: AgentState, ctx: _RunContext, update: Update) -> None:
    response = compose_response(
        run_id=state.run_id,
        result_id=str(uuid.uuid4()),
        question=state.question,
        interpreted=state.interpreted_query,
        plan=state.analysis_plan,
        datasets=_candidates(state),
        result=state.execution_results,
        result_validation=state.result_validation,
        map_layer=state.map_layer,
    )
    facts = explanation_facts(response, state.analysis_plan, state.execution_results)
    explanation = _llm_call(steps.explain_result, ctx.llm, facts)
    update["final_response"] = response.model_copy(update={"summary": explanation.summary})


# ── LangGraph 그래프 ──────────────────────────────────────────────────────

StepFunction = Callable[[AgentState, _RunContext, Update], None]

_STEPS: dict[WorkflowStep, StepFunction] = {
    WorkflowStep.INTERPRET_QUERY: _interpret_query,
    WorkflowStep.SELECT_DATASETS: _select_datasets,
    WorkflowStep.BUILD_ANALYSIS_PLAN: _build_analysis_plan,
    WorkflowStep.VALIDATE_PLAN: _validate_plan,
    WorkflowStep.LOAD_DATA: _load_data,
    WorkflowStep.EXECUTE_OPERATIONS: _execute_operations,
    WorkflowStep.VALIDATE_RESULT: _validate_result,
    WorkflowStep.CREATE_MAP_LAYER: _create_map_layer,
    WorkflowStep.GENERATE_EXPLANATION: _generate_explanation,
}


def _node(step: WorkflowStep, function: StepFunction) -> Callable[[AgentState, Runtime[_RunContext]], Update]:
    """단계 함수를 LangGraph 노드로 감싼다.

    실패해도 그 전에 기록한 값(해석·후보·계획 시도 등)은 상태에 남겨 Provenance로 추적할 수 있게 하고,
    오류는 errors에 더한다. 다음 단계로 갈지는 라우터가 errors를 보고 정한다.
    """

    def node(state: AgentState, runtime: Runtime[_RunContext]) -> Update:
        update: Update = {"current_step": step}
        try:
            function(state, runtime.context, update)
        except WorkflowFailure as failure:
            error = WorkflowError(step=step, code=failure.code, message=str(failure), issues=failure.issues)
            update["errors"] = [*state.errors, error]
        except Exception as exception:
            logger.exception("분석 실행 중 예상하지 못한 오류 (run_id=%s)", state.run_id)
            message = f"{type(exception).__name__}: {exception}"
            update["errors"] = [*state.errors, WorkflowError(step=step, code="INTERNAL_ERROR", message=message)]
        return update

    return node


def _then(next_step: WorkflowStep) -> Callable[[AgentState], str]:
    """실패가 기록되면 멈추고, 아니면 다음 단계로 간다."""
    return lambda state: END if state.errors else next_step


def _after_plan_built(state: AgentState) -> str:
    if state.errors:
        return END
    # 스키마를 통과하지 못한 계획(analysis_plan=None)은 검증할 것이 없으므로 피드백과 함께 바로 다시 만든다.
    return WorkflowStep.VALIDATE_PLAN if state.analysis_plan is not None else WorkflowStep.BUILD_ANALYSIS_PLAN


def _after_plan_validated(state: AgentState) -> str:
    if state.errors:
        return END
    return WorkflowStep.LOAD_DATA if state.plan_validation.ok else WorkflowStep.BUILD_ANALYSIS_PLAN


def _build_graph() -> CompiledStateGraph:
    graph = StateGraph(AgentState, context_schema=_RunContext)
    for step, function in _STEPS.items():
        graph.add_node(step, _node(step, function))
    graph.add_edge(START, WorkflowStep.INTERPRET_QUERY)
    for step, next_step in [
        (WorkflowStep.INTERPRET_QUERY, WorkflowStep.SELECT_DATASETS),
        (WorkflowStep.SELECT_DATASETS, WorkflowStep.BUILD_ANALYSIS_PLAN),
        (WorkflowStep.LOAD_DATA, WorkflowStep.EXECUTE_OPERATIONS),
        (WorkflowStep.EXECUTE_OPERATIONS, WorkflowStep.VALIDATE_RESULT),
        (WorkflowStep.VALIDATE_RESULT, WorkflowStep.CREATE_MAP_LAYER),
        (WorkflowStep.CREATE_MAP_LAYER, WorkflowStep.GENERATE_EXPLANATION),
    ]:
        graph.add_conditional_edges(step, _then(next_step), [next_step, END])
    graph.add_conditional_edges(
        WorkflowStep.BUILD_ANALYSIS_PLAN,
        _after_plan_built,
        [WorkflowStep.VALIDATE_PLAN, WorkflowStep.BUILD_ANALYSIS_PLAN, END],
    )
    graph.add_conditional_edges(
        WorkflowStep.VALIDATE_PLAN,
        _after_plan_validated,
        [WorkflowStep.LOAD_DATA, WorkflowStep.BUILD_ANALYSIS_PLAN, END],
    )
    graph.add_edge(WorkflowStep.GENERATE_EXPLANATION, END)
    return graph.compile()


ANALYSIS_GRAPH = _build_graph()


# ── 공통 ──────────────────────────────────────────────────────────────────


def _candidates(state: AgentState) -> dict[str, DatasetMetadata]:
    """LLM에 제시한 후보 Dataset 메타데이터. 계획·검증·실행은 모두 이 메타데이터를 기준으로 한다."""
    return {d.dataset_id: d for d in state.dataset_candidates}


def _llm_call(function: Callable[..., Any], *args: Any) -> Any:
    try:
        return function(*args)
    except LLMError as error:
        raise WorkflowFailure("LLM_FAILED", str(error)) from error


def _gis_call(function: Callable[..., Any], *args: Any) -> Any:
    try:
        return function(*args)
    except GisToolError as error:
        raise WorkflowFailure(error.code, str(error)) from error


def _unit_name(level: SpatialLevel) -> str:
    return f"{SPATIAL_LEVEL_NAMES[level]}({level})"


def _consistency_issues(interpreted: InterpretedQuery, plan: AnalysisPlan) -> list[ValidationIssue]:
    """계획이 해석 결과(intent·지역·분석 단위)를 바꾸지 않았는지 확인한다."""
    pairs = [
        ("intent", plan.intent, interpreted.intent),
        ("region", plan.region, interpreted.region),
        ("analysis_unit", plan.analysis_unit, interpreted.analysis_unit),
    ]
    return [
        ValidationIssue(
            code="PLAN_INTERPRETATION_MISMATCH",
            severity=Severity.ERROR,
            message=f"plan.{path}({planned})가 질문 해석 결과({expected})와 다릅니다",
            path=path,
        )
        for path, planned, expected in pairs
        if planned != expected
    ]
