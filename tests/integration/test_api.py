import uuid

import pytest
from fastapi.testclient import TestClient

from app.api.main import create_app, get_embedder, get_llm
from app.config import Settings
from tests.fakes import FakeEmbedder, daycare_llm
from tests.support import QUESTION

pytestmark = pytest.mark.integration


@pytest.fixture
def client(database_url, catalog):
    settings = Settings(
        database_url=database_url,
        llm_provider="ollama",
        ollama_model=None,
        openai_api_key=None,
        openai_embedding_model="test-embedding",
    )
    app = create_app(settings)
    app.dependency_overrides[get_llm] = lambda: daycare_llm()
    app.dependency_overrides[get_embedder] = lambda: FakeEmbedder()
    with TestClient(app) as test_client:
        yield test_client


def test_analysis_endpoint_returns_map_ranking_and_explanation(client):
    response = client.post("/api/analyses", json={"question": QUESTION})

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "succeeded" and body["errors"] == []
    result = body["result"]
    assert result["metric"]["name"] == "daycare_per_1000_children"
    assert result["ranking"][0]["unit_name"] == "카동"
    assert result["map_layer"]["geojson"]["type"] == "FeatureCollection"
    assert {d["dataset_id"]: d["reference_date"] for d in result["datasets"]} == {
        "emd_boundary": "2026-07-01",
        "population_by_age": "2026-09-30",
        "daycare_facility": "2026-10-07",
    }

    stored = client.get(f"/api/analyses/{body['run_id']}").json()
    assert stored["status"] == "succeeded"
    assert stored["provenance"]["analysis_plan"]["intent"] == "supply_demand_gap"
    assert stored["result"]["result_id"] == result["result_id"]


def test_unknown_run_is_404(client):
    assert client.get(f"/api/analyses/{uuid.uuid4()}").status_code == 404


def test_empty_question_is_rejected(client):
    assert client.post("/api/analyses", json={"question": ""}).status_code == 422


def test_missing_llm_configuration_is_503(client):
    client.app.dependency_overrides.pop(get_llm)

    response = client.post("/api/analyses", json={"question": QUESTION})

    assert response.status_code == 503
    assert "OLLAMA_MODEL" in response.json()["detail"]


def test_missing_embedding_configuration_is_503(client):
    client.app.dependency_overrides.pop(get_embedder)

    response = client.post("/api/analyses", json={"question": QUESTION})

    assert response.status_code == 503
    assert "OPENAI_API_KEY" in response.json()["detail"]


def test_catalog_and_health_endpoints(client):
    datasets = client.get("/api/datasets").json()
    health = client.get("/api/health").json()

    assert [d["dataset_id"] for d in datasets] == ["daycare_facility", "emd_boundary", "population_by_age"]
    assert health == {
        "status": "ok",
        "database": "ok",
        "llm_provider": "ollama",
        "llm_model": "",
        "embedding_model": "test-embedding",
    }
