import json

import pytest
from pydantic import ValidationError

from app.domain.filters import FilterCondition, FilterGroup
from app.domain.operations import (
    AggregateByAreaOperation,
    AggregateOperation,
    CalculateRatioOperation,
    RankOperation,
)
from app.catalog.definitions import SEOUL, TRUSTED_DATASETS
from app.domain.enums import SpatialLevel
from app.domain.plan import AnalysisPlan, DatasetFilter, Region, analysis_units
from app.domain.state import DatasetSelection, Explanation, InterpretedQuery
from app.llm.schema import to_llm_json_schema
from tests.support import load_plan, load_plan_dict


def test_first_use_case_plan_parses_into_typed_operations():
    plan = load_plan()

    assert [type(op) for op in plan.operations] == [
        AggregateByAreaOperation,
        AggregateOperation,
        CalculateRatioOperation,
        RankOperation,
    ]
    assert plan.filter_for("population_by_age") == FilterGroup.model_validate(
        {"logic": "and", "conditions": [{"field": "age", "operator": "between", "value": [0, 5]}]}
    )
    assert plan.filter_for("daycare_facility") is None


def test_unknown_operation_type_is_rejected():
    data = load_plan_dict()
    data["operations"].append({"type": "buffer", "input": "daycare_facility", "distance": 500, "output": "x"})

    with pytest.raises(ValidationError, match="does not match any of the expected tags"):
        AnalysisPlan.model_validate(data)


def test_extra_fields_are_rejected():
    data = load_plan_dict()
    data["operations"][2]["sql"] = "SELECT 1"

    with pytest.raises(ValidationError, match="Extra inputs are not permitted"):
        AnalysisPlan.model_validate(data)


@pytest.mark.parametrize("output", ["Daycare Count", "1count", "count-1", ""])
def test_operation_output_must_be_snake_case(output):
    data = load_plan_dict()
    data["operations"][0]["output"] = output

    with pytest.raises(ValidationError):
        AnalysisPlan.model_validate(data)


def test_ratio_scale_must_be_positive():
    data = load_plan_dict()
    data["operations"][2]["scale"] = 0

    with pytest.raises(ValidationError):
        AnalysisPlan.model_validate(data)


def test_ranking_limit_is_bounded():
    data = load_plan_dict()
    data["output"]["ranking"]["limit"] = 500

    with pytest.raises(ValidationError):
        AnalysisPlan.model_validate(data)


@pytest.mark.parametrize(
    "condition",
    [
        {"field": "age", "operator": "between", "value": [5]},
        {"field": "age", "operator": "between", "value": [5, 0]},
        {"field": "age", "operator": "between", "value": [0, "5"]},
        {"field": "age", "operator": "in", "value": []},
        {"field": "age", "operator": "eq", "value": [1, 2]},
        {"field": "age", "operator": "gt", "value": None},
        {"field": "name", "operator": "contains", "value": 3},
        {"field": "name", "operator": "is_null", "value": "x"},
        {"field": "age", "operator": "like", "value": "1"},
    ],
)
def test_filter_condition_value_shape_is_validated(condition):
    with pytest.raises(ValidationError):
        FilterCondition.model_validate(condition)


@pytest.mark.parametrize(
    "condition",
    [
        {"field": "age", "operator": "between", "value": [0, 5]},
        {"field": "reference_date", "operator": "between", "value": ["2026-01-01", "2026-12-31"]},
        {"field": "facility_type", "operator": "in", "value": ["국공립", "민간"]},
        {"field": "name", "operator": "starts_with", "value": "서울"},
        {"field": "facility_type", "operator": "is_not_null", "value": None},
        {"field": "age", "operator": "lte", "value": 5},
    ],
)
def test_filter_condition_accepts_valid_shapes(condition):
    FilterCondition.model_validate(condition)


def test_filter_expression_distinguishes_condition_and_group():
    condition = DatasetFilter.model_validate({"dataset": "d", "where": {"field": "age", "operator": "eq", "value": 3}})
    group = DatasetFilter.model_validate(
        {"dataset": "d", "where": {"logic": "or", "conditions": [{"field": "age", "operator": "eq", "value": 3}]}}
    )

    assert isinstance(condition.where, FilterCondition)
    assert isinstance(group.where, FilterGroup)


def test_not_group_requires_exactly_one_condition():
    conditions = [{"field": "age", "operator": "eq", "value": 1}, {"field": "age", "operator": "eq", "value": 2}]

    with pytest.raises(ValidationError, match="not 그룹"):
        FilterGroup.model_validate({"logic": "not", "conditions": conditions})


def _walk(node):
    if isinstance(node, dict):
        yield node
        for value in node.values():
            yield from _walk(value)
    elif isinstance(node, list):
        for item in node:
            yield from _walk(item)


@pytest.mark.parametrize("model", [AnalysisPlan, InterpretedQuery, DatasetSelection, Explanation])
def test_llm_schema_follows_strict_structured_output_rules(model):
    schema = to_llm_json_schema(model)
    text = json.dumps(schema)

    for keyword in ("oneOf", "discriminator", '"const"', '"default"', '"pattern"', '"minimum"', '"minItems"'):
        assert keyword not in text
    for node in _walk(schema):
        if node.get("type") == "object":
            assert node["additionalProperties"] is False
            assert node["required"] == list(node["properties"])
        if "$ref" in node:
            assert list(node) == ["$ref"]


def test_llm_schema_expresses_operations_as_any_of_with_enum_tags():
    schema = to_llm_json_schema(AnalysisPlan)

    variants = schema["properties"]["operations"]["items"]["anyOf"]
    tags = [schema["$defs"][v["$ref"].split("/")[-1]]["properties"]["type"]["enum"] for v in variants]
    assert tags == [["aggregate_by_area"], ["aggregate"], ["calculate_ratio"], ["rank"]]


def test_analysis_units_come_from_polygon_datasets_covering_the_region():
    datasets = TRUSTED_DATASETS.values()

    assert analysis_units(datasets, SEOUL) == [SpatialLevel.EMD]
    assert analysis_units(datasets, Region(name="서울특별시", level="sido")) == [SpatialLevel.EMD]
    assert analysis_units(datasets, Region(name="부산광역시", level="sido")) == []
