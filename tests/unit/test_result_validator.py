from app.catalog.definitions import SEOUL, TRUSTED_DATASETS
from app.domain.enums import SpatialLevel
from app.domain.results import BoundaryStats, ExecutionResult, OperationLog, UnitRow
from app.validation.result_validator import validate_result
from tests.support import load_plan

PLAN = load_plan()
BBOX = [126.76, 37.42, 127.19, 37.71]


def _datasets(feature_count: int | None = 10, bbox: list[float] | None = BBOX) -> dict:
    boundary = TRUSTED_DATASETS["emd_boundary"]
    spatial = boundary.spatial.model_copy(update={"feature_count": feature_count, "bbox": bbox})
    return {**TRUSTED_DATASETS, "emd_boundary": boundary.model_copy(update={"spatial": spatial})}


def _row(i: int, count=2, children=100, ratio=None, rank=1, reasons=None) -> UnitRow:
    if ratio is None and children:
        ratio = count / children * 1000
    return UnitRow(
        key=f"11110{i:05d}",
        name=f"동{i}",
        parent_name="종로구",
        values={
            "daycare_count": count,
            "child_population": children,
            "daycare_per_1000_children": ratio,
            "shortage_rank": rank,
        },
        null_reasons=reasons or {},
    )


def _result(rows: list[UnitRow], bbox=BBOX, unmatched=None, unassigned=0) -> ExecutionResult:
    log = OperationLog(
        index=0,
        type="aggregate_by_area",
        output="daycare_count",
        label="어린이집 수",
        tool="aggregate_by_area",
        params={},
        stats={"unassigned_points": unassigned},
        duration_ms=1.0,
    )
    return ExecutionResult(
        analysis_unit=SpatialLevel.EMD,
        unit_dataset="emd_boundary",
        region=SEOUL,
        analysis_crs="EPSG:4326",
        boundary=BoundaryStats(unit_count=len(rows), invalid_geometry_count=0, empty_geometry_count=0, bbox=bbox),
        rows=rows,
        metrics=[],
        operations=[log],
        unmatched_keys=unmatched or {},
    )


def _codes(result: ExecutionResult, datasets=None) -> tuple[list[str], list[str]]:
    report = validate_result(result, PLAN, datasets or _datasets())
    return [i.code for i in report.errors], [i.code for i in report.warnings]


def test_clean_result_passes():
    assert _codes(_result([_row(i) for i in range(10)])) == ([], [])


def test_empty_and_duplicate_results_fail():
    assert _codes(_result([]))[0] == ["RESULT_EMPTY"]
    assert "DUPLICATE_UNITS" in _codes(_result([_row(1)] * 10))[0]


def test_negative_counts_and_populations_fail():
    rows = [_row(i) for i in range(9)] + [_row(9, children=-5, ratio=1.0)]

    assert _codes(_result(rows))[0] == ["NEGATIVE_VALUE"]


def test_zero_denominator_must_be_null_with_reason():
    handled = _row(9, children=0, ratio=None, rank=None, reasons={"daycare_per_1000_children": "denominator_zero"})
    unhandled = _row(9, children=0, ratio=0.0)

    assert _codes(_result([_row(i) for i in range(9)] + [handled])) == ([], ["NULL_VALUES"])
    assert _codes(_result([_row(i) for i in range(9)] + [unhandled]))[0] == ["ZERO_DENOMINATOR_UNHANDLED"]


def test_non_finite_values_fail():
    rows = [_row(i) for i in range(9)] + [_row(9, ratio=float("nan"))]

    assert _codes(_result(rows))[0] == ["NON_FINITE_VALUE"]


def test_high_null_rate_fails():
    missing = {"daycare_per_1000_children": "denominator_missing"}
    rows = [_row(i) for i in range(7)] + [
        _row(i, children=None, ratio=None, rank=None, reasons=missing) for i in range(7, 10)
    ]

    assert _codes(_result(rows))[0] == ["HIGH_NULL_RATE"]


def test_result_outside_region_bbox_fails():
    rows = [_row(i) for i in range(10)]

    assert _codes(_result(rows, bbox=[955000.0, 1940000.0, 960000.0, 1950000.0]))[0] == ["OUT_OF_REGION"]
    assert _codes(_result(rows), datasets=_datasets(bbox=None))[1] == ["REGION_CHECK_SKIPPED"]


def test_unit_count_is_compared_with_expected_count():
    rows = [_row(i) for i in range(10)]

    assert _codes(_result(rows), datasets=_datasets(feature_count=20))[0] == ["UNIT_COUNT_MISMATCH"]
    assert _codes(_result(rows), datasets=_datasets(feature_count=11))[1] == ["UNIT_COUNT_MISMATCH"]


def test_unmatched_keys_and_unassigned_points_are_warnings():
    result = _result([_row(i) for i in range(10)], unmatched={"child_population": ["1199999999"]}, unassigned=3)

    assert _codes(result) == ([], ["UNMATCHED_KEYS", "UNASSIGNED_POINTS"])
