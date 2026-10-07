from collections.abc import Iterator
from typing import Self

from pydantic import Field, model_validator

from app.domain.base import StrictModel
from app.domain.enums import FilterOperator, LogicalOperator

Scalar = str | int | float | bool

_NULL_CHECKS = {FilterOperator.IS_NULL, FilterOperator.IS_NOT_NULL}
_SET_OPERATORS = {FilterOperator.IN, FilterOperator.NOT_IN}
_STRING_OPERATORS = {FilterOperator.CONTAINS, FilterOperator.STARTS_WITH}


def _is_number(value: object) -> bool:
    return isinstance(value, int | float) and not isinstance(value, bool)


class FilterCondition(StrictModel):
    field: str = Field(description="필터할 컬럼명 (Dataset columns의 name)")
    operator: FilterOperator
    value: Scalar | list[Scalar] | None = Field(
        default=None,
        description="between은 [최솟값, 최댓값], in/not_in은 값 목록, is_null/is_not_null은 null",
    )

    @model_validator(mode="after")
    def _check_value_shape(self) -> Self:
        op, value = self.operator, self.value
        if op in _NULL_CHECKS:
            if value is not None:
                raise ValueError(f"{op} 조건의 value는 null이어야 합니다")
        elif op == FilterOperator.BETWEEN:
            if not (isinstance(value, list) and len(value) == 2):
                raise ValueError("between 조건의 value는 [최솟값, 최댓값] 2개여야 합니다")
            low, high = value
            same_kind = (_is_number(low) and _is_number(high)) or (isinstance(low, str) and isinstance(high, str))
            if not same_kind:
                raise ValueError("between 조건의 두 값은 모두 숫자이거나 모두 문자열(날짜)이어야 합니다")
            if low > high:
                raise ValueError("between 조건의 최솟값이 최댓값보다 큽니다")
        elif op in _SET_OPERATORS:
            if not (isinstance(value, list) and value):
                raise ValueError(f"{op} 조건의 value는 비어 있지 않은 목록이어야 합니다")
        elif op in _STRING_OPERATORS:
            if not (isinstance(value, str) and value):
                raise ValueError(f"{op} 조건의 value는 비어 있지 않은 문자열이어야 합니다")
        elif value is None or isinstance(value, list):
            raise ValueError(f"{op} 조건의 value는 단일 값이어야 합니다")
        return self


class FilterGroup(StrictModel):
    logic: LogicalOperator
    conditions: list[FilterCondition] = Field(min_length=1)

    @model_validator(mode="after")
    def _check_not(self) -> Self:
        if self.logic == LogicalOperator.NOT and len(self.conditions) != 1:
            raise ValueError("not 그룹은 조건이 정확히 1개여야 합니다")
        return self


# Group은 1단계만 허용한다 (설계 문서 5장 참고).
FilterExpression = FilterCondition | FilterGroup


def iter_conditions(expression: FilterExpression) -> Iterator[FilterCondition]:
    if isinstance(expression, FilterCondition):
        yield expression
    else:
        yield from expression.conditions
