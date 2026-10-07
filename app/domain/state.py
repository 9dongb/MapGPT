from datetime import datetime

from pydantic import Field

from app.domain.base import StrictModel
from app.domain.catalog import DatasetMetadata
from app.domain.enums import AnalysisIntent, RunStatus, SpatialLevel, WorkflowStep
from app.domain.plan import AnalysisPlan, Region
from app.domain.results import (
    ExecutionResult,
    FinalResponse,
    MapLayer,
    ValidationIssue,
    ValidationReport,
)


class InterpretedQuery(StrictModel):
    """자연어 공간 분석 질문의 해석 결과."""

    intent: AnalysisIntent | None = Field(description="지원하는 분석 유형. 지원 범위 밖이면 null")
    unsupported_reason: str | None = Field(description="intent가 null일 때 그 이유, 아니면 null")
    region: Region | None
    analysis_unit: SpatialLevel | None
    restated_question: str = Field(description="분석 질문을 명확하게 다시 쓴 문장")
    key_concepts: list[str] = Field(description="필요한 데이터 개념 (예: 어린이집, 0~5세 인구, 행정동 경계)")
    assumptions: list[str] = Field(description="해석 과정에서 둔 가정")


class DatasetSelection(StrictModel):
    """후보 Dataset 중 분석에 필요한 Dataset 선택 결과."""

    datasets: list[str] = Field(description="선택한 Dataset ID 목록")
    rationale: str


class Explanation(StrictModel):
    """분석 결과에 대한 한국어 설명."""

    summary: str


class PlanAttempt(StrictModel):
    """LLM이 만든 계획 한 번과 그 검증 결과 (스키마를 통과하지 못했으면 plan은 null)."""

    plan: AnalysisPlan | None
    validation: ValidationReport


class WorkflowError(StrictModel):
    step: WorkflowStep
    code: str
    message: str
    issues: list[ValidationIssue] = []


class AgentState(StrictModel):
    run_id: str
    question: str
    status: RunStatus = RunStatus.RUNNING
    current_step: WorkflowStep | None = None
    interpreted_query: InterpretedQuery | None = None
    dataset_candidates: list[DatasetMetadata] = []
    selected_datasets: list[str] = []
    analysis_plan: AnalysisPlan | None = None
    plan_validation: ValidationReport | None = None
    plan_history: list[PlanAttempt] = []  # 재생성을 포함한 모든 계획 시도
    execution_results: ExecutionResult | None = None
    result_validation: ValidationReport | None = None
    map_layer: MapLayer | None = None
    final_response: FinalResponse | None = None
    errors: list[WorkflowError] = []
    llm_provider: str
    llm_model: str
    started_at: datetime
    finished_at: datetime | None = None
