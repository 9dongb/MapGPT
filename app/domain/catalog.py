from datetime import date

from pydantic import Field

from app.domain.base import StrictModel
from app.domain.enums import DataType, GeometryType, SemanticType, SpatialLevel


class ColumnMetadata(StrictModel):
    name: str
    description: str
    data_type: DataType
    semantic_type: SemanticType
    unit: str | None = None
    nullable: bool = False


class JoinKey(StrictModel):
    field: str
    semantic_type: SemanticType
    # 같은 의미라도 코드 체계가 다르면 결합할 수 없다 (예: 행안부 10자리 vs 통계청 8자리).
    code_system: str | None = None


class RegionRef(StrictModel):
    name: str
    level: SpatialLevel
    code: str


class SpatialMetadata(StrictModel):
    level: SpatialLevel | None
    geometry_type: GeometryType | None
    crs: str | None
    coverage: RegionRef | None
    bbox: list[float] | None = Field(default=None, description="EPSG:4326 [minx, miny, maxx, maxy]")
    feature_count: int | None = None


class TemporalMetadata(StrictModel):
    reference_date: date | None
    update_cycle: str | None


class DatasetMetadata(StrictModel):
    dataset_id: str
    title: str
    description: str
    category: str
    semantic_tags: list[str]
    provider: str
    source: str
    license: str | None
    spatial: SpatialMetadata
    temporal: TemporalMetadata
    columns: list[ColumnMetadata]
    join_keys: list[JoinKey]
    quality_notes: list[str] = []

    def column(self, name: str) -> ColumnMetadata | None:
        return next((c for c in self.columns if c.name == name), None)

    def column_with(self, semantic_type: SemanticType) -> ColumnMetadata | None:
        return next((c for c in self.columns if c.semantic_type == semantic_type), None)

    def join_key(self, field: str) -> JoinKey | None:
        return next((k for k in self.join_keys if k.field == field), None)

    @property
    def geometry_column(self) -> ColumnMetadata | None:
        return next((c for c in self.columns if c.data_type == DataType.GEOMETRY), None)

    @property
    def is_polygon(self) -> bool:
        return self.spatial.geometry_type in (GeometryType.POLYGON, GeometryType.MULTIPOLYGON)
