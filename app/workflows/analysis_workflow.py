"""분석 Orchestrator. 단계마다 다음 단계를 반환하는 상태 머신이다.

interpret_query → select_datasets → build_analysis_plan ⇄ validate_plan (재생성 1회)
→ load_data → execute_operations → validate_result → create_map_layer → generate_explanation
"""

import logging
import uuid
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

import psycopg
from psycopg_pool import ConnectionPool

from app.agents import steps
from app.catalog.catalog import DatasetCatalog
from app.domain.catalog import DatasetMetadata
from app.domain.enums import RunStatus, Severity, WorkflowStep
from app.domain.plan import AnalysisPlan, resolve_region
from app.domain.results import ValidationIssue, ValidationReport
from app.domain.state import AgentState, InterpretedQuery, PlanAttempt, WorkflowError
from app.executor.operation_executor import ExecutionContext, execute_operations, prepare_context
from app.gis.tools import GisToolError, create_choropleth_layer
from app.llm.base import LLMError, LLMOutputError, StructuredLLM
from app.repositories.run_repository import save_run
from app.validation.plan_validator import validate_plan
from app.validation.result_validator import validate_result
from app.workflows.response import compose_response, explanation_facts

logger = logging.getLogger(__name__)

MAX_PLAN_ATTEMPTS = 2  # 최초 생성 + 검증 오류 피드백 후 재생성 1회


class WorkflowFailure(Exception):
    def __init__(self, code: str, message: str, issues: list[ValidationIssue] | None = None):
        super().__init__(message)
        self.code = code
        self.issues = issues or []


@dataclass
class _Run:
    state: AgentState
    datasets: dict[str, DatasetMetadata] = field(default_factory=dict)  # LLM에 제시한 후보 메타데이터
    conn: psycopg.Connection | None = None  # load_data ~ create_map_layer 동안 쓰는 읽기 전용 세션
    context: ExecutionContext | None = None


class AnalysisWorkflow:
    def __init__(self, llm: StructuredLLM, pool: ConnectionPool):
        self._llm = llm
        self._pool = pool
        self._catalog = DatasetCatalog(pool)
        self._steps: dict[WorkflowStep, Callable[[_Run], WorkflowStep | None]] = {
            WorkflowStep.INTERPRET_QUERY: self._interpret_query,
            WorkflowStep.SELECT_DATASETS: self._select_datasets,
            WorkflowStep.BUILD_ANALYSIS_PLAN: self._build_analysis_plan,
            WorkflowStep.VALIDATE_PLAN: self._validate_plan,
            WorkflowStep.LOAD_DATA: self._load_data,
            WorkflowStep.EXECUTE_OPERATIONS: self._execute_operations,
            WorkflowStep.VALIDATE_RESULT: self._validate_result,
            WorkflowStep.CREATE_MAP_LAYER: self._create_map_layer,
            WorkflowStep.GENERATE_EXPLANATION: self._generate_explanation,
        }

    def run(self, question: str) -> AgentState:
        state = AgentState(
            run_id=str(uuid.uuid4()),
            question=question,
            llm_provider=self._llm.provider,
            llm_model=self._llm.model,
            started_at=datetime.now(UTC),
        )
        run = _Run(state=state)
        step: WorkflowStep | None = WorkflowStep.INTERPRET_QUERY
        try:
            while step is not None:
                state.current_step = step
                step = self._steps[step](run)
            state.status = RunStatus.SUCCEEDED
        except WorkflowFailure as failure:
            state.status = RunStatus.FAILED
            state.errors.append(
                WorkflowError(step=state.current_step, code=failure.code, message=str(failure), issues=failure.issues)
            )
        except Exception as error:
            logger.exception("분석 실행 중 예상하지 못한 오류 (run_id=%s)", state.run_id)
            state.status = RunStatus.FAILED
            state.errors.append(
                WorkflowError(
                    step=state.current_step, code="INTERNAL_ERROR", message=f"{type(error).__name__}: {error}"
                )
            )
        finally:
            self._release(run)
            state.finished_at = datetime.now(UTC)
            with self._pool.connection() as conn:
                save_run(conn, state)
        return state

    # ── LLM 단계 ──────────────────────────────────────────────────────────

    def _interpret_query(self, run: _Run) -> WorkflowStep:
        datasets = self._catalog.list_all()
        regions = list({d.spatial.coverage.name: d.spatial.coverage for d in datasets if d.spatial.coverage}.values())
        interpreted = self._llm_call(steps.interpret_query, self._llm, run.state.question, regions)
        run.state.interpreted_query = interpreted
        if interpreted.intent is None:
            raise WorkflowFailure(
                "UNSUPPORTED_QUESTION", interpreted.unsupported_reason or "지원하지 않는 분석 질문입니다"
            )
        if interpreted.region is None or interpreted.analysis_unit is None:
            raise WorkflowFailure("INCOMPLETE_INTERPRETATION", "분석 지역 또는 분석 단위를 해석하지 못했습니다")
        if not any(resolve_region(interpreted.region, r) for r in regions):
            supported = ", ".join(r.name for r in regions)
            raise WorkflowFailure(
                "REGION_NOT_SUPPORTED", f"'{interpreted.region.name}' 데이터가 없습니다. 분석 가능한 지역: {supported}"
            )
        return WorkflowStep.SELECT_DATASETS

    def _select_datasets(self, run: _Run) -> WorkflowStep:
        interpreted = run.state.interpreted_query
        query = " ".join([interpreted.restated_question, *interpreted.key_concepts])
        candidates = self._catalog.search(query)
        run.state.dataset_candidates = candidates
        selection = self._llm_call(steps.select_datasets, self._llm, interpreted, candidates)
        candidate_ids = {d.dataset_id for d in candidates}
        unknown = [d for d in selection.datasets if d not in candidate_ids]
        if unknown or not selection.datasets:
            raise WorkflowFailure("INVALID_DATASET_SELECTION", f"후보에 없는 Dataset을 선택했습니다: {unknown}")
        run.state.selected_datasets = list(dict.fromkeys(selection.datasets))
        run.datasets = {d.dataset_id: d for d in candidates}
        return WorkflowStep.BUILD_ANALYSIS_PLAN

    def _build_analysis_plan(self, run: _Run) -> WorkflowStep:
        state = run.state
        feedback = None
        if state.plan_history:
            last = state.plan_history[-1]
            feedback = (last.plan.model_dump(mode="json") if last.plan else None, last.validation.errors)
        try:
            selected = [run.datasets[d] for d in state.selected_datasets]
            plan = steps.build_analysis_plan(self._llm, state.interpreted_query, selected, feedback)
        except LLMOutputError as error:
            # 스키마를 통과하지 못한 계획은 실행하지 않는다. 오류를 피드백해 재생성을 시도한다.
            report = ValidationReport(
                issues=[ValidationIssue(code="PLAN_SCHEMA_INVALID", severity=Severity.ERROR, message=str(error))]
            )
            return self._record_plan_attempt(run, None, report)
        except LLMError as error:
            raise WorkflowFailure("LLM_FAILED", str(error)) from error
        state.analysis_plan = plan
        return WorkflowStep.VALIDATE_PLAN

    def _validate_plan(self, run: _Run) -> WorkflowStep:
        state = run.state
        report = validate_plan(state.analysis_plan, run.datasets, state.selected_datasets)
        report.issues.extend(_consistency_issues(state.interpreted_query, state.analysis_plan))
        return self._record_plan_attempt(run, state.analysis_plan, report)

    def _record_plan_attempt(self, run: _Run, plan: AnalysisPlan | None, report: ValidationReport) -> WorkflowStep:
        state = run.state
        state.analysis_plan, state.plan_validation = plan, report
        state.plan_history.append(PlanAttempt(plan=plan, validation=report))
        if report.ok:
            return WorkflowStep.LOAD_DATA
        if len(state.plan_history) < MAX_PLAN_ATTEMPTS:
            return WorkflowStep.BUILD_ANALYSIS_PLAN
        raise WorkflowFailure("PLAN_INVALID", "검증을 통과하는 분석 계획을 만들지 못했습니다", report.errors)

    # ── 결정론적 GIS 실행 단계 (하나의 읽기 전용 트랜잭션) ─────────────────

    def _load_data(self, run: _Run) -> WorkflowStep:
        run.conn = self._pool.getconn()
        run.conn.execute("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ, READ ONLY")
        run.context = self._gis_call(prepare_context, run.conn, run.state.analysis_plan, run.datasets)
        return WorkflowStep.EXECUTE_OPERATIONS

    def _execute_operations(self, run: _Run) -> WorkflowStep:
        run.state.execution_results = self._gis_call(execute_operations, run.context)
        return WorkflowStep.VALIDATE_RESULT

    def _validate_result(self, run: _Run) -> WorkflowStep:
        state = run.state
        report = validate_result(state.execution_results, state.analysis_plan, run.datasets)
        state.result_validation = report
        if not report.ok:
            raise WorkflowFailure("RESULT_INVALID", "분석 결과가 검증을 통과하지 못했습니다", report.errors)
        return WorkflowStep.CREATE_MAP_LAYER

    def _create_map_layer(self, run: _Run) -> WorkflowStep:
        plan = run.state.analysis_plan
        label = next(op.label for op in plan.operations if op.output == plan.output.metric)
        run.state.map_layer = self._gis_call(
            create_choropleth_layer,
            run.conn,
            run.context.boundary,
            run.state.execution_results.rows,
            plan.output.metric,
            label,
        )
        self._release(run)
        return WorkflowStep.GENERATE_EXPLANATION

    def _generate_explanation(self, run: _Run) -> None:
        state = run.state
        response = compose_response(
            run_id=state.run_id,
            result_id=str(uuid.uuid4()),
            question=state.question,
            interpreted=state.interpreted_query,
            plan=state.analysis_plan,
            datasets=run.datasets,
            result=state.execution_results,
            result_validation=state.result_validation,
            map_layer=state.map_layer,
        )
        facts = explanation_facts(response, state.analysis_plan, state.execution_results)
        explanation = self._llm_call(steps.explain_result, self._llm, facts)
        state.final_response = response.model_copy(update={"summary": explanation.summary})
        return None

    # ── 공통 ──────────────────────────────────────────────────────────────

    @staticmethod
    def _llm_call(function: Callable[..., Any], *args: Any) -> Any:
        try:
            return function(*args)
        except LLMError as error:
            raise WorkflowFailure("LLM_FAILED", str(error)) from error

    @staticmethod
    def _gis_call(function: Callable[..., Any], *args: Any) -> Any:
        try:
            return function(*args)
        except GisToolError as error:
            raise WorkflowFailure(error.code, str(error)) from error

    def _release(self, run: _Run) -> None:
        if run.conn is not None:
            run.conn.rollback()
            self._pool.putconn(run.conn)
            run.conn = None


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
