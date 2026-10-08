import pytest

from app.domain.enums import RunStatus, WorkflowStep
from app.domain.plan import AnalysisPlan
from app.domain.state import DatasetSelection, InterpretedQuery
from app.llm.base import LLMError, LLMOutputError
from app.llm.embeddings import EmbeddingError
from app.repositories.run_repository import get_run
from app.workflows.analysis_workflow import AnalysisWorkflow
from tests.fakes import FakeEmbedder, daycare_llm, interpreted
from tests.support import QUESTION, load_plan, load_plan_dict

pytestmark = pytest.mark.integration


def test_first_use_case_runs_end_to_end_and_records_provenance(pool, catalog, conn):
    llm = daycare_llm()

    state = AnalysisWorkflow(llm, pool, FakeEmbedder()).run(QUESTION)

    assert state.status == RunStatus.SUCCEEDED, state.errors
    response = state.final_response
    assert [(item.rank, item.unit_name) for item in response.ranking] == [
        (1, "카동"),
        (2, "아동"),
        (3, "사동"),
        (3, "라동"),
        (3, "마동"),
        (6, "자동"),
        (7, "가동"),
        (7, "차동"),
    ]
    assert response.metric.label == "0~5세 어린이 1,000명당 어린이집 수"
    assert response.metric_labels["child_population"] == "0~5세 인구"
    assert response.rank_metric == "shortage_rank"
    assert response.summary == "카동이 가장 부족합니다."
    assert response.map_layer.feature_count == 10 and response.map_layer.null_count == 2
    assert [d.dataset_id for d in response.datasets] == ["emd_boundary", "population_by_age", "daycare_facility"]
    assert response.analysis_method[1] == "필터 — 행정동별 연령별 주민등록 인구(population_by_age): age 0~5"
    assert "'어린이'를 만 0~5세로 해석" in response.assumptions
    assert any("순위에서 제외" in item for item in response.limitations)
    assert any("분석 지역 경계 밖의 점 1개" in item for item in response.limitations)
    assert any(item.startswith("Dataset 기준 시점이 서로 다릅니다") for item in response.limitations)

    stored = get_run(conn, state.run_id)
    provenance = stored["provenance"]
    assert stored["status"] == "succeeded" and stored["result"]["result_id"] == response.result_id
    assert provenance["question"] == QUESTION
    assert provenance["dataset_search"]["query"] == (
        "서울특별시 행정동별 0~5세 인구 1,000명당 어린이집 수가 적은 곳 어린이집 위치 0~5세 인구 행정동 경계"
    )
    assert provenance["dataset_search"]["embedding_model"] == "fake-embedding"
    assert [hit["dataset_id"] for hit in provenance["dataset_search"]["hits"]] == [
        d.dataset_id for d in state.dataset_candidates
    ]
    assert provenance["dataset_selection"]["rationale"] == "경계, 수요(0~5세 인구), 공급(어린이집)"
    assert provenance["analysis_plan"]["output"]["metric"] == "daycare_per_1000_children"
    row = conn.execute(
        "SELECT datasets, crs, jsonb_array_length(operations), result_id::text FROM analysis.run WHERE run_id = %s",
        (state.run_id,),
    ).fetchone()
    assert row[0][1] == {"dataset_id": "population_by_age", "reference_date": "2026-09-30"}
    assert row[1:] == ("EPSG:4326", 4, response.result_id)


def test_invalid_plan_is_regenerated_with_validator_feedback(pool, catalog):
    data = load_plan_dict()
    data["operations"][2]["scale"] = 10000
    llm = daycare_llm(plans=[AnalysisPlan.model_validate(data), load_plan()])

    state = AnalysisWorkflow(llm, pool, FakeEmbedder()).run(QUESTION)

    assert state.status == RunStatus.SUCCEEDED, state.errors
    assert [attempt.validation.ok for attempt in state.plan_history] == [False, True]
    second_prompt = llm.prompts_for(AnalysisPlan)[1]
    assert "[POLICY_VIOLATION]" in second_prompt and '"scale": 10000' in second_prompt


def test_plan_that_stays_invalid_is_never_executed(pool, catalog, conn):
    data = load_plan_dict()
    data["filters"][0]["where"] = {"field": "ages", "operator": "between", "value": [0, 5]}
    llm = daycare_llm(plans=[AnalysisPlan.model_validate(data)])

    state = AnalysisWorkflow(llm, pool, FakeEmbedder()).run(QUESTION)

    assert state.status == RunStatus.FAILED
    [error] = state.errors
    assert (error.step, error.code) == (WorkflowStep.VALIDATE_PLAN, "PLAN_INVALID")
    assert [issue.code for issue in error.issues] == ["FILTER_FIELD_UNKNOWN"]
    assert state.execution_results is None
    assert get_run(conn, state.run_id)["status"] == "failed"


def test_plan_schema_failure_counts_as_invalid_plan(pool, catalog):
    llm = daycare_llm(plans=[LLMOutputError("AnalysisPlan 스키마 불일치"), load_plan()])

    state = AnalysisWorkflow(llm, pool, FakeEmbedder()).run(QUESTION)

    assert state.status == RunStatus.SUCCEEDED
    assert [attempt.plan is None for attempt in state.plan_history] == [True, False]
    assert "[PLAN_SCHEMA_INVALID]" in llm.prompts_for(AnalysisPlan)[1]


def test_plan_that_changes_the_interpretation_is_rejected(pool, catalog):
    llm = daycare_llm(plans=[load_plan(analysis_unit="sigungu")])

    state = AnalysisWorkflow(llm, pool, FakeEmbedder()).run(QUESTION)

    assert state.errors[0].code == "PLAN_INVALID"
    assert "PLAN_INTERPRETATION_MISMATCH" in [issue.code for issue in state.errors[0].issues]


@pytest.mark.parametrize(
    ("interpretation", "code"),
    [
        (
            InterpretedQuery.model_validate(
                {
                    "intent": None,
                    "unsupported_reason": "지하철역 거리 분석은 아직 지원하지 않습니다",
                    "region": None,
                    "analysis_unit": None,
                    "restated_question": "지하철역 500m 밖 지역",
                    "key_concepts": ["지하철역"],
                    "assumptions": [],
                }
            ),
            "UNSUPPORTED_QUESTION",
        ),
        (interpreted(region="부산광역시"), "REGION_NOT_SUPPORTED"),
        (interpreted(analysis_unit="sigungu"), "UNIT_NOT_SUPPORTED"),
        (LLMError("OpenAI 호출 실패: 401"), "LLM_FAILED"),
    ],
)
def test_interpretation_failures_stop_before_planning(pool, catalog, conn, interpretation, code):
    llm = daycare_llm(interpreted=[interpretation])

    state = AnalysisWorkflow(llm, pool, FakeEmbedder()).run("지하철역에서 500m 이상 떨어진 지역을 찾아줘")

    assert state.status == RunStatus.FAILED
    assert (state.errors[0].step, state.errors[0].code) == (WorkflowStep.INTERPRET_QUERY, code)
    assert llm.prompts_for(AnalysisPlan) == []
    assert get_run(conn, state.run_id)["status"] == "failed"


def test_interpretation_prompt_lists_analysis_units_per_region(pool, catalog):
    llm = daycare_llm()

    AnalysisWorkflow(llm, pool, FakeEmbedder()).run(QUESTION)

    system = next(system for output_type, system, _ in llm.calls if output_type is InterpretedQuery)
    assert "- 서울특별시 (sido): emd(행정동)" in system


def test_unit_without_boundary_data_fails_with_available_units(pool, catalog):
    llm = daycare_llm(interpreted=[interpreted(analysis_unit="sigungu")])

    state = AnalysisWorkflow(llm, pool, FakeEmbedder()).run(QUESTION)

    assert state.errors[0].message == (
        "'서울특별시'에는 시군구(sigungu) 단위 경계 데이터가 없습니다. 분석 가능한 단위: 행정동(emd)"
    )


class FailingEmbedder(FakeEmbedder):
    def embed(self, texts: list[str]) -> list[list[float]]:
        raise EmbeddingError("OpenAI 임베딩 호출 실패: timeout")


@pytest.mark.parametrize(
    ("embedder", "code"),
    [(FakeEmbedder(model="other-model"), "CATALOG_INDEX_STALE"), (FailingEmbedder(), "EMBEDDING_FAILED")],
)
def test_dataset_search_failures_stop_before_selection(pool, catalog, embedder, code):
    llm = daycare_llm()

    state = AnalysisWorkflow(llm, pool, embedder).run(QUESTION)

    assert (state.errors[0].step, state.errors[0].code) == (WorkflowStep.SELECT_DATASETS, code)
    assert state.dataset_search is None and llm.prompts_for(DatasetSelection) == []


def test_invalid_dataset_selection_is_recorded_before_stopping(pool, catalog, conn):
    selection = DatasetSelection(datasets=["emd_boundary", "subway_station"], rationale="지하철역 거리를 계산")
    llm = daycare_llm(selection=[selection])

    state = AnalysisWorkflow(llm, pool, FakeEmbedder()).run(QUESTION)

    assert (state.errors[0].step, state.errors[0].code) == (WorkflowStep.SELECT_DATASETS, "INVALID_DATASET_SELECTION")
    assert llm.prompts_for(AnalysisPlan) == []
    stored = get_run(conn, state.run_id)["provenance"]["dataset_selection"]
    assert stored == {"datasets": ["emd_boundary", "subway_station"], "rationale": "지하철역 거리를 계산"}


def test_result_validation_failure_blocks_map_and_explanation(pool, catalog, conn):
    conn.execute(
        "UPDATE catalog.dataset SET metadata = jsonb_set(metadata, '{spatial,feature_count}', '50') "
        "WHERE dataset_id = 'emd_boundary'"
    )
    conn.commit()

    state = AnalysisWorkflow(daycare_llm(), pool, FakeEmbedder()).run(QUESTION)

    assert (state.errors[0].step, state.errors[0].code) == (WorkflowStep.VALIDATE_RESULT, "RESULT_INVALID")
    assert [issue.code for issue in state.errors[0].issues] == ["UNIT_COUNT_MISMATCH"]
    assert state.map_layer is None and state.final_response is None
