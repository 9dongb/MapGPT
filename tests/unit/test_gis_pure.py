from datetime import date

import pytest
from psycopg import sql

from app.catalog.definitions import DAYCARE_FACILITY, EMD_BOUNDARY, POPULATION_BY_AGE
from app.domain.enums import SortOrder
from app.domain.filters import FilterCondition, FilterGroup
from app.gis.crs import CrsError, parse_srid, transform_crs
from app.gis.filter_sql import FilterCompileError, compile_filter, find_filter_problems
from app.gis.tools import GisToolError, MetricValues, calculate_ratio, quantile_breaks, rank


def _render(fragment: sql.Composable) -> str:
    return fragment.as_string(None)


def _group(logic: str, *conditions: dict) -> FilterGroup:
    return FilterGroup.model_validate({"logic": logic, "conditions": list(conditions)})


@pytest.mark.parametrize(
    ("condition", "expected_sql", "expected_params"),
    [
        ({"field": "age", "operator": "between", "value": [0, 5]}, '"age" BETWEEN %s AND %s', [0, 5]),
        ({"field": "age", "operator": "gte", "value": 65.0}, '"age" >= %s', [65]),
        ({"field": "age", "operator": "neq", "value": 3}, '"age" <> %s', [3]),
        ({"field": "adm_cd", "operator": "in", "value": ["1", "2"]}, '"adm_cd" = ANY(%s)', [["1", "2"]]),
        ({"field": "adm_cd", "operator": "not_in", "value": ["1"]}, 'NOT ("adm_cd" = ANY(%s))', [["1"]]),
        (
            {"field": "adm_cd", "operator": "starts_with", "value": "11_%"},
            "\"adm_cd\" LIKE %s ESCAPE '\\'",
            ["11\\_\\%%"],
        ),
        ({"field": "adm_cd", "operator": "contains", "value": "15"}, "\"adm_cd\" LIKE %s ESCAPE '\\'", ["%15%"]),
        ({"field": "adm_cd", "operator": "is_null", "value": None}, '"adm_cd" IS NULL', []),
        (
            {"field": "reference_date", "operator": "lte", "value": "2026-09-30"},
            '"reference_date" <= %s',
            [date(2026, 9, 30)],
        ),
    ],
)
def test_filter_compiles_to_parameterized_sql(condition, expected_sql, expected_params):
    fragment, params = compile_filter(FilterCondition.model_validate(condition), POPULATION_BY_AGE)

    assert _render(fragment) == expected_sql
    assert params == expected_params


def test_filter_group_combines_conditions_with_logic():
    expression = _group(
        "and",
        {"field": "age", "operator": "between", "value": [0, 5]},
        {"field": "adm_cd", "operator": "starts_with", "value": "11"},
    )
    fragment, params = compile_filter(expression, POPULATION_BY_AGE)
    negated, _ = compile_filter(_group("not", {"field": "age", "operator": "eq", "value": 1}), POPULATION_BY_AGE)

    assert _render(fragment) == '("age" BETWEEN %s AND %s AND "adm_cd" LIKE %s ESCAPE \'\\\')'
    assert params == [0, 5, "11%"]
    assert _render(negated) == 'NOT ("age" = %s)'


def test_injection_attempt_stays_a_parameter():
    hostile = "1'; DROP TABLE datasets.population_by_age; --"
    fragment, params = compile_filter(FilterCondition(field="adm_cd", operator="eq", value=hostile), POPULATION_BY_AGE)

    assert _render(fragment) == '"adm_cd" = %s'
    assert params == [hostile]


@pytest.mark.parametrize(
    ("condition", "code"),
    [
        ({"field": "agee", "operator": "eq", "value": 1}, "FILTER_FIELD_UNKNOWN"),
        ({"field": "adm_cd", "operator": "gt", "value": "1"}, "FILTER_TYPE_MISMATCH"),
        ({"field": "age", "operator": "contains", "value": "1"}, "FILTER_TYPE_MISMATCH"),
        ({"field": "age", "operator": "eq", "value": "five"}, "FILTER_TYPE_MISMATCH"),
        ({"field": "age", "operator": "eq", "value": 1.5}, "FILTER_TYPE_MISMATCH"),
        ({"field": "reference_date", "operator": "eq", "value": "어제"}, "FILTER_TYPE_MISMATCH"),
    ],
)
def test_filter_problems_are_reported_with_codes(condition, code):
    expression = FilterCondition.model_validate(condition)

    assert [p.code for p in find_filter_problems(expression, POPULATION_BY_AGE)] == [code]
    with pytest.raises(FilterCompileError):
        compile_filter(expression, POPULATION_BY_AGE)


def test_geometry_column_cannot_be_filtered():
    expression = FilterCondition(field="geom", operator="is_not_null", value=None)

    assert [p.code for p in find_filter_problems(expression, EMD_BOUNDARY)] == ["FILTER_TYPE_MISMATCH"]


def test_crs_policy_parses_supported_srids_and_transforms_only_when_needed():
    assert parse_srid(DAYCARE_FACILITY.spatial.crs) == 4326
    assert parse_srid("EPSG:5179") == 5179
    for invalid in (None, "WGS84", "EPSG:3857"):
        with pytest.raises(CrsError):
            parse_srid(invalid)
    geom = sql.Identifier("geom")
    assert transform_crs(geom, 4326, 4326) is geom
    assert _render(transform_crs(geom, 5179, 4326)) == 'ST_Transform("geom", 4326)'


def _metric(values: dict) -> MetricValues:
    return MetricValues(name="m", values=values)


def test_ratio_keeps_null_with_reason_instead_of_zero():
    numerator = _metric({"a": 4, "b": 1, "c": 0, "d": None})
    denominator = _metric({"a": 100, "b": 0, "d": 10})

    result = calculate_ratio(numerator, denominator, 1000, ["a", "b", "c", "d"], "ratio")

    assert result.values == {"a": 40.0, "b": None, "c": None, "d": None}
    assert result.null_reasons == {"b": "denominator_zero", "c": "denominator_missing", "d": "numerator_missing"}
    assert result.stats == {"computed": 1, "denominator_zero": 1, "denominator_missing": 1, "numerator_missing": 1}


def test_ratio_rejects_non_finite_values():
    with pytest.raises(GisToolError) as error:
        calculate_ratio(_metric({"a": float("inf")}), _metric({"a": 1}), 1, ["a"], "ratio")
    assert error.value.code == "NON_FINITE_RESULT"


def test_rank_uses_competition_ranking_and_excludes_nulls():
    metric = _metric({"a": 40.0, "e": 20.0, "f": 20.0, "b": None, "g": 50.0})

    ascending = rank(metric, SortOrder.ASC, ["a", "b", "e", "f", "g"], "r")
    descending = rank(metric, SortOrder.DESC, ["a", "b", "e", "f", "g"], "r")

    assert ascending.values == {"a": 3, "b": None, "e": 1, "f": 1, "g": 4}
    assert ascending.null_reasons == {"b": "input_null"}
    assert descending.values == {"a": 2, "b": None, "e": 3, "f": 3, "g": 1}


def test_quantile_breaks_are_strictly_increasing_and_above_minimum():
    assert quantile_breaks([], 5) == []
    assert quantile_breaks([1, 1, 1, 1], 5) == []
    assert quantile_breaks(list(range(11)), 5) == [2, 4, 6, 8]
    assert quantile_breaks([0, 0, 0, 5, 10], 5) == [5]
