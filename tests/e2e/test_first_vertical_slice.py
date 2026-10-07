"""첫 번째 Vertical Slice 성공 기준(전달 문서 40번) E2E.

실제 적재 데이터(DATABASE_URL)와 실제 LLM(LLM_PROVIDER 설정)이 필요하다: pytest -m e2e
"""

import math

import psycopg
import pytest
from psycopg_pool import ConnectionPool

from app.config import get_settings
from app.domain.enums import RunStatus
from app.llm.base import LLMError
from app.llm.factory import create_llm
from app.repositories.run_repository import get_run
from app.workflows.analysis_workflow import AnalysisWorkflow
from tests.support import QUESTION

pytestmark = pytest.mark.e2e

EXPECTED_DATASETS = {"emd_boundary", "population_by_age", "daycare_facility"}


@pytest.fixture(scope="module")
def environment():
    settings = get_settings()
    try:
        llm = create_llm(settings)
    except LLMError as error:
        pytest.skip(f"LLM이 설정되지 않았습니다: {error}")
    try:
        with psycopg.connect(settings.database_url) as conn:
            loaded = conn.execute("SELECT count(*) FROM catalog.dataset").fetchone()[0]
    except psycopg.Error as error:
        pytest.skip(f"DB에 연결할 수 없습니다: {error}")
    if loaded < len(EXPECTED_DATASETS):
        pytest.skip("실데이터가 적재되지 않았습니다 (python -m app.cli ingest all)")
    with ConnectionPool(settings.database_url, min_size=1, max_size=2) as pool:
        state = AnalysisWorkflow(llm, pool).run(QUESTION)
        yield state, pool


def test_success_criteria_1_to_5_interpretation_selection_and_plan(environment):
    state, _ = environment
    assert state.status == RunStatus.SUCCEEDED, state.errors

    interpreted = state.interpreted_query  # 1. 질문 해석
    assert interpreted.intent == "supply_demand_gap"
    assert (interpreted.region.name, interpreted.region.level, interpreted.analysis_unit) == (
        "서울특별시",
        "sido",
        "emd",
    )
    assert set(state.selected_datasets) == EXPECTED_DATASETS  # 2. Dataset 선택
    assert state.analysis_plan is not None  # 3·4. Pydantic 검증을 통과한 Plan
    assert state.plan_validation.ok  # 5. Plan Validator 통과


def test_success_criteria_6_to_9_computation_matches_independent_sql(environment):
    state, pool = environment
    plan = state.analysis_plan
    names = {op.type: op.output for op in plan.operations}
    rows = {row.key: row.values for row in state.execution_results.rows}

    with pool.connection() as conn:
        children = dict(
            conn.execute(
                "SELECT adm_cd, sum(population) FROM datasets.population_by_age WHERE age BETWEEN 0 AND 5 GROUP BY adm_cd"
            ).fetchall()
        )
        # 각 시설을 자신을 포함하는 행정동 중 코드가 가장 작은 곳 하나에 배정 (설계 9장의 정책)
        assigned = dict(
            conn.execute(
                """
                SELECT adm_cd, count(*) FROM (
                    SELECT (SELECT min(b.adm_cd) FROM datasets.emd_boundary b WHERE ST_Covers(b.geom, d.geom)) AS adm_cd
                    FROM datasets.daycare_facility d
                ) t
                WHERE adm_cd IS NOT NULL GROUP BY adm_cd
                """
            ).fetchall()
        )
    daycares = {key: assigned.get(key, 0) for key in rows}

    for key, values in rows.items():
        assert values[names["aggregate"]] == children.get(key)  # 6. 0~5세 인구
        assert values[names["aggregate_by_area"]] == daycares[key]  # 7. 어린이집 공간 집계
        ratio = values[names["calculate_ratio"]]  # 8. 어린이집 수 / 0~5세 인구 × 1000
        if children.get(key):
            assert math.isclose(ratio, daycares[key] / children[key] * 1000)
        else:
            assert ratio is None

    ranking = state.final_response.ranking  # 9. 부족 순위 (오름차순)
    assert [item.value for item in ranking] == sorted(item.value for item in ranking)
    assert ranking[0].rank == 1


def test_success_criteria_10_to_12_outputs_and_provenance(environment):
    state, pool = environment
    response = state.final_response
    layer = response.map_layer

    assert layer.geojson["type"] == "FeatureCollection" and layer.crs == "EPSG:4326"  # 10. Choropleth GeoJSON
    assert layer.feature_count == len(state.execution_results.rows) > 400
    assert response.summary and response.ranking and response.metric.name  # 11. 지도·Ranking·Metric
    assert {d.dataset_id for d in response.datasets} == EXPECTED_DATASETS
    assert all(d.reference_date for d in response.datasets)  # 데이터 기준 시점
    assert response.analysis_method and response.assumptions and response.limitations

    with pool.connection() as conn:  # 12. Provenance
        stored = get_run(conn, state.run_id)
    assert stored["status"] == "succeeded" and stored["result"]["result_id"] == response.result_id
    assert stored["provenance"]["analysis_plan"] == state.analysis_plan.model_dump(mode="json")
