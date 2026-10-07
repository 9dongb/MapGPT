import pytest

from app.catalog.definitions import DAYCARE_FACILITY, EMD_BOUNDARY, POPULATION_BY_AGE, SEOUL
from app.domain.enums import AggregationFunction
from app.domain.filters import FilterCondition
from app.executor.operation_executor import execute_operations, prepare_context
from app.gis import tools
from app.gis.tools import GisToolError
from tests.integration.synthetic import CHILD_ROWS, EXPECTED, POINTS, SEOUL_BBOX, load_synthetic
from tests.support import load_plan

pytestmark = pytest.mark.integration

CHILDREN = FilterCondition(field="age", operator="between", value=[0, 5])


@pytest.fixture
def datasets(conn):
    return load_synthetic(conn)


def test_get_boundary_restricts_to_region_and_reports_geometry(conn, datasets):
    boundary = tools.get_boundary(conn, EMD_BOUNDARY, SEOUL)

    assert boundary.unit_keys == sorted(EXPECTED["daycare_count"])
    assert boundary.units[0].name == "가동" and boundary.units[0].parent_name == "가가구"
    assert boundary.invalid_geometry_count == 0
    assert boundary.bbox == pytest.approx(SEOUL_BBOX)


def test_get_boundary_rejects_point_dataset(conn, datasets):
    with pytest.raises(GisToolError) as error:
        tools.get_boundary(conn, DAYCARE_FACILITY, SEOUL)
    assert error.value.code == "NOT_POLYGON"


def test_aggregate_by_area_assigns_each_point_once(conn, datasets):
    boundary = tools.get_boundary(conn, EMD_BOUNDARY, SEOUL)
    points = tools.get_dataset(conn, DAYCARE_FACILITY)

    result = tools.aggregate_by_area(conn, points, boundary, "count", "daycare_count")

    assert result.values == EXPECTED["daycare_count"]
    assert result.stats == {"input_points": len(POINTS), "assigned_points": len(POINTS) - 1, "unassigned_points": 1}


def test_aggregate_sums_filtered_rows_per_group(conn, datasets):
    population = tools.filter_dataset(conn, tools.get_dataset(conn, POPULATION_BY_AGE), CHILDREN)

    result = tools.aggregate(conn, population, ["adm_cd"], "population", AggregationFunction.SUM, "child_population")

    expected = {key: value for key, value in EXPECTED["child_population"].items() if value is not None}
    assert result.values == {**expected, "1199999999": 7}
    assert result.stats == {"input_rows": CHILD_ROWS, "group_count": len(expected) + 1}


def test_filter_with_no_rows_fails_explicitly(conn, datasets):
    with pytest.raises(GisToolError) as error:
        tools.filter_dataset(
            conn, tools.get_dataset(conn, POPULATION_BY_AGE), FilterCondition(field="age", operator="gt", value=200)
        )
    assert error.value.code == "FILTER_EMPTY_RESULT"


def test_full_plan_execution_matches_hand_computed_answer(conn, datasets):
    plan = load_plan()
    with conn.transaction():
        ctx = prepare_context(conn, plan, datasets)
        result = execute_operations(ctx)

    by_key = {row.key: row for row in result.rows}
    for metric, expected in EXPECTED.items():
        assert {key: by_key[key].values[metric] for key in expected} == expected
    assert by_key["1111000200"].null_reasons["daycare_per_1000_children"] == "denominator_zero"
    assert by_key["1114000100"].null_reasons["daycare_per_1000_children"] == "denominator_missing"
    assert by_key["1114000100"].null_reasons["child_population"] == "no_matching_records"
    assert result.unmatched_keys == {"child_population": ["1199999999"]}
    assert [log.type for log in result.operations] == ["aggregate_by_area", "aggregate", "calculate_ratio", "rank"]
    assert result.analysis_crs == "EPSG:4326"


def test_points_stored_in_another_crs_are_normalized_before_overlay(conn, datasets):
    conn.execute(
        "CREATE TABLE datasets.daycare_facility_5179 AS "
        "SELECT facility_id, ST_Transform(geom, 5179)::geometry(Point, 5179) AS geom "
        "FROM datasets.daycare_facility WHERE facility_id <> 'ab_edge'"
    )
    metadata = DAYCARE_FACILITY.model_copy(
        update={
            "dataset_id": "daycare_facility_5179",
            "spatial": DAYCARE_FACILITY.spatial.model_copy(update={"crs": "EPSG:5179"}),
        }
    )
    try:
        boundary = tools.get_boundary(conn, EMD_BOUNDARY, SEOUL)
        result = tools.aggregate_by_area(conn, tools.get_dataset(conn, metadata), boundary, "count", "n")
    finally:
        conn.rollback()

    assert result.values == {**EXPECTED["daycare_count"], "1111000100": 3}


def test_choropleth_layer_is_wgs84_geojson_with_quantile_breaks(conn, datasets):
    plan = load_plan()
    ctx = prepare_context(conn, plan, datasets)
    result = execute_operations(ctx)

    layer = tools.create_choropleth_layer(
        conn, ctx.boundary, result.rows, "daycare_per_1000_children", "0~5세 어린이 1,000명당 어린이집 수"
    )

    features = layer.geojson["features"]
    assert layer.crs == "EPSG:4326" and layer.geojson["type"] == "FeatureCollection"
    assert [f["id"] for f in features] == ctx.boundary.unit_keys
    assert features[0]["geometry"]["type"] == "MultiPolygon"
    assert features[0]["properties"]["daycare_per_1000_children"] == 40.0
    assert features[1]["properties"]["null_reason"] == "denominator_zero"
    assert (layer.null_count, layer.classification.min, layer.classification.max) == (2, 0.0, 40.0)
    assert layer.classification.breaks == [5.0, 20.0, 40.0]
