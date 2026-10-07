import pytest

from app.catalog.definitions import TRUSTED_DATASETS
from app.domain.plan import AnalysisPlan
from app.validation.plan_validator import validate_plan
from tests.support import load_plan_dict

SELECTED = list(TRUSTED_DATASETS)


def _codes(data: dict, datasets=TRUSTED_DATASETS, selected=SELECTED) -> list[str]:
    report = validate_plan(AnalysisPlan.model_validate(data), datasets, selected)
    return [issue.code for issue in report.errors]


def _with_dataset(dataset_id: str, **updates) -> dict:
    datasets = dict(TRUSTED_DATASETS)
    datasets[dataset_id] = datasets[dataset_id].model_copy(update=updates)
    return datasets


def test_first_use_case_plan_is_valid():
    report = validate_plan(AnalysisPlan.model_validate(load_plan_dict()), TRUSTED_DATASETS, SELECTED)

    assert report.ok
    assert report.issues == []


def test_unknown_and_unselected_datasets_are_rejected():
    data = load_plan_dict()
    data["datasets"].append("subway_station")

    assert _codes(data) == ["UNKNOWN_DATASET"]
    assert "DATASET_NOT_SELECTED" in _codes(load_plan_dict(), selected=["emd_boundary", "population_by_age"])


def test_operation_dataset_must_be_declared():
    data = load_plan_dict()
    data["datasets"].remove("daycare_facility")

    assert _codes(data) == ["DATASET_NOT_DECLARED"]


@pytest.mark.parametrize(
    ("condition", "code"),
    [
        ({"field": "ages", "operator": "between", "value": [0, 5]}, "FILTER_FIELD_UNKNOWN"),
        ({"field": "adm_cd", "operator": "between", "value": [0, 5]}, "FILTER_TYPE_MISMATCH"),
    ],
)
def test_filter_fields_and_types_are_checked(condition, code):
    data = load_plan_dict()
    data["filters"][0]["where"] = condition

    assert _codes(data) == [code]


def test_filters_on_unit_boundary_and_duplicates_are_rejected():
    data = load_plan_dict()
    data["filters"].append(data["filters"][0])
    data["filters"].append(
        {"dataset": "emd_boundary", "where": {"field": "sigungu_nm", "operator": "eq", "value": "종로구"}}
    )

    assert _codes(data) == ["DUPLICATE_FILTER", "BOUNDARY_FILTER_UNSUPPORTED"]


def test_ratio_must_reference_previously_computed_metrics():
    data = load_plan_dict()
    data["operations"][2]["denominator"] = "population_by_age"

    assert _codes(data) == ["OPERATION_INPUT_UNKNOWN"]

    reordered = load_plan_dict()
    reordered["operations"] = [reordered["operations"][i] for i in (2, 0, 1, 3)]
    assert _codes(reordered)[:2] == ["OPERATION_INPUT_UNKNOWN", "OPERATION_INPUT_UNKNOWN"]


@pytest.mark.parametrize("output", ["child_population", "adm_cd", "unit_name", "emd_boundary"])
def test_output_names_must_not_conflict(output):
    data = load_plan_dict()
    data["operations"][0]["output"] = output
    data["operations"][2]["numerator"] = output

    assert "OUTPUT_NAME_CONFLICT" in _codes(data)


def test_spatial_aggregation_requires_point_input_and_unit_polygon_boundary():
    data = load_plan_dict()
    data["operations"][0]["input"] = "population_by_age"
    data["operations"][0]["boundary"] = "daycare_facility"

    assert _codes(data) == ["GEOMETRY_REQUIRED", "GEOMETRY_TYPE_INVALID"]


def test_unsupported_crs_is_rejected():
    spatial = TRUSTED_DATASETS["daycare_facility"].spatial.model_copy(update={"crs": "EPSG:3857"})

    assert _codes(load_plan_dict(), datasets=_with_dataset("daycare_facility", spatial=spatial)) == ["CRS_UNSUPPORTED"]


def test_group_by_must_be_a_compatible_join_key():
    data = load_plan_dict()
    data["operations"][1]["group_by"] = ["age"]
    assert _codes(data) == ["JOIN_KEY_INCOMPATIBLE"]

    other_code_system = [
        TRUSTED_DATASETS["population_by_age"].join_keys[0].model_copy(update={"code_system": "kostat_8"})
    ]
    datasets = _with_dataset("population_by_age", join_keys=other_code_system)
    assert _codes(load_plan_dict(), datasets=datasets) == ["JOIN_KEY_INCOMPATIBLE"]


def test_sum_requires_numeric_field():
    data = load_plan_dict()
    data["operations"][1]["aggregation"]["field"] = "adm_cd"

    assert _codes(data) == ["FIELD_NOT_NUMERIC"]


def test_ratio_operands_must_differ_and_not_be_ranks():
    data = load_plan_dict()
    data["operations"][2]["denominator"] = "daycare_count"
    assert _codes(data) == ["RATIO_OPERAND_INVALID"]

    ranked = load_plan_dict()
    ranked["operations"].insert(2, {**ranked["operations"][3], "input": "daycare_count", "output": "count_rank"})
    ranked["operations"][3]["numerator"] = "count_rank"
    assert _codes(ranked) == ["RATIO_OPERAND_INVALID"]


def test_output_metric_must_be_computed():
    data = load_plan_dict()
    data["output"]["metric"] = "unknown_metric"

    assert _codes(data)[0] == "OUTPUT_METRIC_NOT_COMPUTED"


def test_output_metric_must_not_be_the_rank_itself():
    data = load_plan_dict()
    data["output"]["metric"] = "shortage_rank"

    report = validate_plan(AnalysisPlan.model_validate(data), TRUSTED_DATASETS, SELECTED)

    assert report.errors[0].code == "OUTPUT_METRIC_IS_RANK"
    assert "'daycare_per_1000_children'" in report.errors[0].message


def test_ranking_requires_a_rank_on_the_output_metric():
    data = load_plan_dict()
    data["operations"][3]["input"] = "daycare_count"

    assert _codes(data)[0] == "RANKING_NOT_DEFINED"


def test_region_outside_dataset_coverage_is_rejected():
    data = load_plan_dict()
    data["region"] = {"name": "부산광역시", "level": "sido"}

    assert _codes(data) == ["REGION_NOT_COVERED"] * 3


def test_analysis_unit_needs_a_polygon_dataset_at_that_level():
    data = load_plan_dict()
    data["analysis_unit"] = "sigungu"

    assert "UNIT_BOUNDARY_MISSING" in _codes(data)


@pytest.mark.parametrize(
    ("path", "value"),
    [
        (("operations", 2, "scale"), 10000),
        (("operations", 3, "order"), "desc"),
        (("output", "ranking", "enabled"), False),
    ],
)
def test_supply_demand_policy_is_enforced(path, value):
    data = load_plan_dict()
    target = data
    for key in path[:-1]:
        target = target[key]
    target[path[-1]] = value

    assert "POLICY_VIOLATION" in _codes(data)


def test_unused_dataset_is_a_warning():
    data = load_plan_dict()
    data["datasets"] = ["emd_boundary", "population_by_age", "daycare_facility"]
    data["filters"] = []
    data["operations"] = [data["operations"][0], {**data["operations"][3], "input": "daycare_count"}]
    data["output"]["metric"] = "daycare_count"

    report = validate_plan(AnalysisPlan.model_validate(data), TRUSTED_DATASETS, SELECTED)

    assert [i.code for i in report.warnings] == ["UNUSED_DATASET"]
