from typing import Annotated, Literal

from pydantic import Field

from app.domain.base import StrictModel
from app.domain.enums import AggregationFunction, SortOrder

MetricName = Annotated[
    str,
    Field(pattern=r"^[a-z][a-z0-9_]{0,62}$", description="결과 지표 이름 (snake_case, 고유)"),
]
Label = Annotated[str, Field(min_length=1, description="결과 지표의 짧은 한국어 이름 (예: 어린이집 수)")]


class AggregateByAreaOperation(StrictModel):
    """Point Dataset을 경계 Polygon 단위로 공간 집계한다."""

    type: Literal["aggregate_by_area"]
    label: Label
    input: str = Field(description="집계할 Point Dataset ID")
    boundary: str = Field(description="집계 단위 Polygon Dataset ID")
    aggregation: Literal["count"]
    output: MetricName


class AggregationSpec(StrictModel):
    field: str = Field(description="집계할 숫자 컬럼명")
    function: AggregationFunction


class AggregateOperation(StrictModel):
    """속성 Dataset을 분석 단위 키로 그룹 집계한다."""

    type: Literal["aggregate"]
    label: Label
    input: str = Field(description="집계할 Dataset ID")
    group_by: list[str] = Field(min_length=1, description="분석 단위 join key 컬럼 (1개)")
    aggregation: AggregationSpec
    output: MetricName


class CalculateRatioOperation(StrictModel):
    """numerator / denominator × scale. 분모가 0이거나 없으면 null이다."""

    type: Literal["calculate_ratio"]
    label: Label
    numerator: str = Field(description="분자: 앞선 operation의 output")
    denominator: str = Field(description="분모: 앞선 operation의 output")
    scale: float = Field(default=1.0, gt=0)
    output: MetricName


class RankOperation(StrictModel):
    """지표 값으로 순위를 매긴다 (null 제외, 동순위는 1,2,2,4)."""

    type: Literal["rank"]
    label: Label
    input: str = Field(description="순위를 매길 앞선 operation의 output")
    order: SortOrder
    output: MetricName


Operation = Annotated[
    AggregateByAreaOperation | AggregateOperation | CalculateRatioOperation | RankOperation,
    Field(discriminator="type"),
]
