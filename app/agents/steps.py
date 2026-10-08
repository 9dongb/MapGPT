"""LLM 4단계: 질문 해석 · Dataset 선택 · Analysis Plan 생성 · 결과 설명. 모두 Structured Output이다."""

from typing import Any

from app.agents import prompts
from app.domain.catalog import DatasetMetadata, RegionRef
from app.domain.enums import SpatialLevel
from app.domain.plan import AnalysisPlan
from app.domain.results import ValidationIssue
from app.domain.state import DatasetSelection, Explanation, InterpretedQuery
from app.llm.base import StructuredLLM


def interpret_query(
    llm: StructuredLLM, question: str, coverage: list[tuple[RegionRef, list[SpatialLevel]]]
) -> InterpretedQuery:
    system, user = prompts.interpret_prompt(question, coverage)
    return llm.generate(system=system, user=user, output_type=InterpretedQuery)


def select_datasets(
    llm: StructuredLLM, interpreted: InterpretedQuery, candidates: list[DatasetMetadata]
) -> DatasetSelection:
    system, user = prompts.select_prompt(interpreted.model_dump(mode="json"), candidates)
    return llm.generate(system=system, user=user, output_type=DatasetSelection)


def build_analysis_plan(
    llm: StructuredLLM,
    interpreted: InterpretedQuery,
    datasets: list[DatasetMetadata],
    feedback: tuple[dict[str, Any] | None, list[ValidationIssue]] | None = None,
) -> AnalysisPlan:
    system, user = prompts.plan_prompt(interpreted.model_dump(mode="json"), datasets, feedback)
    return llm.generate(system=system, user=user, output_type=AnalysisPlan)


def explain_result(llm: StructuredLLM, facts: dict[str, Any]) -> Explanation:
    system, user = prompts.explain_prompt(facts)
    return llm.generate(system=system, user=user, output_type=Explanation)
