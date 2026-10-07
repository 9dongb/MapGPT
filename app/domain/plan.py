from collections.abc import Mapping

from pydantic import Field

from app.domain.base import StrictModel
from app.domain.catalog import DatasetMetadata, RegionRef
from app.domain.enums import AnalysisIntent, MapType, SpatialLevel
from app.domain.filters import FilterExpression
from app.domain.operations import Operation


class Region(StrictModel):
    name: str = Field(description="지역 공식 명칭 (예: 서울특별시)")
    level: SpatialLevel


class DatasetFilter(StrictModel):
    dataset: str = Field(description="필터를 적용할 Dataset ID")
    where: FilterExpression


class RankingSpec(StrictModel):
    enabled: bool
    limit: int = Field(default=10, ge=1, le=50)


class OutputSpec(StrictModel):
    map_type: MapType
    metric: str = Field(description="지도에 표현할 operation output")
    ranking: RankingSpec


class AnalysisPlan(StrictModel):
    intent: AnalysisIntent
    region: Region
    analysis_unit: SpatialLevel
    datasets: list[str] = Field(min_length=1)
    filters: list[DatasetFilter] = []
    operations: list[Operation] = Field(min_length=1, description="실행 순서대로 나열")
    output: OutputSpec

    def filter_for(self, dataset_id: str) -> FilterExpression | None:
        return next((f.where for f in self.filters if f.dataset == dataset_id), None)


def unit_boundary_candidates(plan: AnalysisPlan, datasets: Mapping[str, DatasetMetadata]) -> list[DatasetMetadata]:
    """분석 단위(analysis_unit)의 Polygon Dataset. 결과 프레임과 지도의 기준이 되며 정확히 1개여야 한다."""
    return [
        datasets[d]
        for d in plan.datasets
        if d in datasets and datasets[d].is_polygon and datasets[d].spatial.level == plan.analysis_unit
    ]


def resolve_region(region: Region, coverage: RegionRef | None) -> RegionRef | None:
    """MVP: 분석 지역은 Dataset coverage와 같아야 한다 (지역 계층 해석은 범위 밖)."""
    if coverage is not None and coverage.name == region.name and coverage.level == region.level:
        return coverage
    return None
