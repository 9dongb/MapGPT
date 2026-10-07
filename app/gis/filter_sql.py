"""FilterExpression → parameterized SQL.

컬럼명은 Dataset 메타데이터로 확인한 뒤 sql.Identifier로, 값은 항상 파라미터로 전달한다.
"""

from dataclasses import dataclass
from datetime import date
from typing import Any

from psycopg import sql

from app.domain.catalog import ColumnMetadata, DatasetMetadata
from app.domain.enums import DataType, FilterOperator, LogicalOperator
from app.domain.filters import FilterCondition, FilterExpression, Scalar, iter_conditions

_ORDERED_TYPES = {DataType.INTEGER, DataType.FLOAT, DataType.DATE}
_ORDERED_OPERATORS = {
    FilterOperator.GT,
    FilterOperator.GTE,
    FilterOperator.LT,
    FilterOperator.LTE,
    FilterOperator.BETWEEN,
}
_STRING_OPERATORS = {FilterOperator.CONTAINS, FilterOperator.STARTS_WITH}
_NULL_CHECKS = {FilterOperator.IS_NULL, FilterOperator.IS_NOT_NULL}
_COMPARISON_SQL = {
    FilterOperator.EQ: "=",
    FilterOperator.NEQ: "<>",
    FilterOperator.GT: ">",
    FilterOperator.GTE: ">=",
    FilterOperator.LT: "<",
    FilterOperator.LTE: "<=",
}


@dataclass(frozen=True)
class FilterProblem:
    index: int  # Group 내 조건 위치 (단일 조건이면 0)
    code: str
    message: str


class FilterCompileError(ValueError):
    pass


def find_filter_problems(expression: FilterExpression, metadata: DatasetMetadata) -> list[FilterProblem]:
    problems: list[FilterProblem] = []
    for index, condition in enumerate(iter_conditions(expression)):
        column = metadata.column(condition.field)
        if column is None:
            problems.append(
                FilterProblem(
                    index, "FILTER_FIELD_UNKNOWN", f"'{metadata.dataset_id}'에 '{condition.field}' 컬럼이 없습니다"
                )
            )
            continue
        message = _type_problem(condition, column)
        if message:
            problems.append(FilterProblem(index, "FILTER_TYPE_MISMATCH", message))
    return problems


def compile_filter(expression: FilterExpression, metadata: DatasetMetadata) -> tuple[sql.Composable, list[Any]]:
    problems = find_filter_problems(expression, metadata)
    if problems:
        raise FilterCompileError("; ".join(p.message for p in problems))
    if isinstance(expression, FilterCondition):
        return _compile_condition(expression, metadata.column(expression.field))

    compiled = [_compile_condition(c, metadata.column(c.field)) for c in expression.conditions]
    params = [param for _, condition_params in compiled for param in condition_params]
    fragments = [fragment for fragment, _ in compiled]
    if expression.logic == LogicalOperator.NOT:
        return sql.SQL("NOT ({})").format(fragments[0]), params
    joiner = sql.SQL(" AND ") if expression.logic == LogicalOperator.AND else sql.SQL(" OR ")
    return sql.SQL("({})").format(joiner.join(fragments)), params


def _type_problem(condition: FilterCondition, column: ColumnMetadata) -> str | None:
    op, data_type = condition.operator, column.data_type
    if data_type == DataType.GEOMETRY:
        return f"Geometry 컬럼 '{column.name}'은 필터할 수 없습니다"
    if op in _NULL_CHECKS:
        return None
    if op in _ORDERED_OPERATORS and data_type not in _ORDERED_TYPES:
        return f"'{op}'는 숫자·날짜 컬럼에만 쓸 수 있습니다 ('{column.name}': {data_type})"
    if op in _STRING_OPERATORS and data_type != DataType.STRING:
        return f"'{op}'는 문자열 컬럼에만 쓸 수 있습니다 ('{column.name}': {data_type})"
    values = condition.value if isinstance(condition.value, list) else [condition.value]
    for value in values:
        try:
            _coerce(value, data_type)
        except (TypeError, ValueError):
            return f"'{column.name}'({data_type}) 컬럼과 값 {value!r}의 타입이 맞지 않습니다"
    return None


def _coerce(value: Scalar, data_type: DataType) -> Any:
    if data_type == DataType.STRING and isinstance(value, str):
        return value
    if data_type == DataType.BOOLEAN and isinstance(value, bool):
        return value
    if not isinstance(value, bool):
        if data_type == DataType.INTEGER and isinstance(value, int | float) and float(value).is_integer():
            return int(value)
        if data_type == DataType.FLOAT and isinstance(value, int | float):
            return float(value)
        if data_type == DataType.DATE and isinstance(value, str):
            return date.fromisoformat(value)
    raise TypeError(f"{value!r}는 {data_type} 값이 아닙니다")


def _escape_like(value: str) -> str:
    return value.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


def _compile_condition(condition: FilterCondition, column: ColumnMetadata) -> tuple[sql.Composable, list[Any]]:
    op, value = condition.operator, condition.value
    identifier = sql.Identifier(column.name)

    def coerce(v: Scalar) -> Any:
        return _coerce(v, column.data_type)

    if op in _COMPARISON_SQL:
        return sql.SQL("{} {} %s").format(identifier, sql.SQL(_COMPARISON_SQL[op])), [coerce(value)]
    if op == FilterOperator.BETWEEN:
        low, high = value
        return sql.SQL("{} BETWEEN %s AND %s").format(identifier), [coerce(low), coerce(high)]
    if op == FilterOperator.IN:
        return sql.SQL("{} = ANY(%s)").format(identifier), [[coerce(v) for v in value]]
    if op == FilterOperator.NOT_IN:
        return sql.SQL("NOT ({} = ANY(%s))").format(identifier), [[coerce(v) for v in value]]
    if op == FilterOperator.CONTAINS:
        return sql.SQL("{} LIKE %s ESCAPE '\\'").format(identifier), [f"%{_escape_like(value)}%"]
    if op == FilterOperator.STARTS_WITH:
        return sql.SQL("{} LIKE %s ESCAPE '\\'").format(identifier), [f"{_escape_like(value)}%"]
    if op == FilterOperator.IS_NULL:
        return sql.SQL("{} IS NULL").format(identifier), []
    return sql.SQL("{} IS NOT NULL").format(identifier), []
