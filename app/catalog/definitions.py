"""Trusted Dataset 3종의 정적 메타데이터.

기준 시점, bbox, feature 수, 품질 기록은 적재(ingest) 시 계산해 채운다.
"""

from app.domain.catalog import (
    ColumnMetadata,
    DatasetMetadata,
    JoinKey,
    RegionRef,
    SpatialMetadata,
    TemporalMetadata,
)
from app.domain.enums import DataType, GeometryType, SemanticType, SpatialLevel

SEOUL = RegionRef(name="서울특별시", level=SpatialLevel.SIDO, code="11")
MOIS_ADM_CD = "mois_adm_cd"  # 행정안전부 10자리 행정기관코드


def _column(
    name: str,
    description: str,
    data_type: DataType,
    semantic_type: SemanticType,
    *,
    unit: str | None = None,
    nullable: bool = False,
) -> ColumnMetadata:
    return ColumnMetadata(
        name=name,
        description=description,
        data_type=data_type,
        semantic_type=semantic_type,
        unit=unit,
        nullable=nullable,
    )


_ADM_CD = _column(
    "adm_cd", "행정동 코드 (행정안전부 10자리 행정기관코드)", DataType.STRING, SemanticType.ADMINISTRATIVE_CODE
)
_ADM_CD_KEY = JoinKey(field="adm_cd", semantic_type=SemanticType.ADMINISTRATIVE_CODE, code_system=MOIS_ADM_CD)

EMD_BOUNDARY = DatasetMetadata(
    dataset_id="emd_boundary",
    title="서울특별시 행정동 경계",
    description=(
        "서울특별시 행정동 단위 경계 Polygon. 분석 공간 단위이며, 점 데이터를 행정동별로 공간 집계할 때의 "
        "경계이자 Choropleth 지도의 Geometry로 사용한다."
    ),
    category="boundary",
    semantic_tags=["행정동", "경계", "행정구역", "공간 단위", "polygon"],
    provider="통계청 SGIS (vuski/admdongkor 가공)",
    source="https://github.com/vuski/admdongkor",
    license="CC BY 4.0 (출처: 통계청 SGIS)",
    spatial=SpatialMetadata(
        level=SpatialLevel.EMD, geometry_type=GeometryType.MULTIPOLYGON, crs="EPSG:4326", coverage=SEOUL
    ),
    temporal=TemporalMetadata(reference_date=None, update_cycle="irregular"),
    columns=[
        _ADM_CD,
        _column("adm_nm", "행정동 이름 (예: 사직동)", DataType.STRING, SemanticType.ADMINISTRATIVE_NAME),
        _column("sido_cd", "시도 코드 (2자리)", DataType.STRING, SemanticType.SIDO_CODE),
        _column("sido_nm", "시도 이름 (예: 서울특별시)", DataType.STRING, SemanticType.SIDO_NAME),
        _column("sigungu_cd", "시군구 코드 (5자리)", DataType.STRING, SemanticType.SIGUNGU_CODE),
        _column("sigungu_nm", "시군구 이름 (예: 종로구)", DataType.STRING, SemanticType.SIGUNGU_NAME),
        _column("geom", "행정동 경계 MultiPolygon (EPSG:4326)", DataType.GEOMETRY, SemanticType.GEOMETRY),
    ],
    join_keys=[_ADM_CD_KEY],
)

POPULATION_BY_AGE = DatasetMetadata(
    dataset_id="population_by_age",
    title="행정동별 연령별 주민등록 인구",
    description=(
        "서울특별시 행정동 단위의 1세 단위 연령별 주민등록 인구(남녀 합계). 연령 조건으로 필터한 뒤 "
        "행정동 코드 기준으로 합계하면 특정 연령대 인구(수요)를 구할 수 있다."
    ),
    category="population",
    semantic_tags=["인구", "연령", "어린이", "영유아", "주민등록", "수요"],
    provider="행정안전부",
    source="https://www.data.go.kr/data/15097972/fileData.do",
    license="공공데이터포털 이용허락범위 제한 없음",
    spatial=SpatialMetadata(level=SpatialLevel.EMD, geometry_type=None, crs=None, coverage=SEOUL),
    temporal=TemporalMetadata(reference_date=None, update_cycle="monthly"),
    columns=[
        _ADM_CD,
        _column("age", "만 나이 (0~110, 110은 110세 이상)", DataType.INTEGER, SemanticType.AGE, unit="year"),
        _column(
            "population",
            "해당 행정동·연령의 주민등록 인구 (남녀 합계)",
            DataType.INTEGER,
            SemanticType.POPULATION,
            unit="person",
        ),
        _column("reference_date", "인구 기준일", DataType.DATE, SemanticType.REFERENCE_DATE),
    ],
    join_keys=[_ADM_CD_KEY],
)

DAYCARE_FACILITY = DatasetMetadata(
    dataset_id="daycare_facility",
    title="서울특별시 어린이집 위치",
    description=(
        "서울특별시에서 운영 중(운영현황 '정상' 또는 '재개')인 어린이집의 위치 Point. 행정동 경계와 공간 결합하여 "
        "행정동별 어린이집 수(공급)를 셀 수 있다. 좌표 품질 규칙을 통과한 시설만 포함한다."
    ),
    category="facility",
    semantic_tags=["어린이집", "보육시설", "영유아", "시설", "공급", "point"],
    provider="서울특별시 (어린이집정보공개포털 원천)",
    source="서울 열린데이터광장 OpenAPI ChildCareInfo (OA-20300)",
    license="공공누리 제4유형 (출처표시·상업적 이용금지·변경금지)",
    spatial=SpatialMetadata(level=None, geometry_type=GeometryType.POINT, crs="EPSG:4326", coverage=SEOUL),
    temporal=TemporalMetadata(reference_date=None, update_cycle="irregular"),
    columns=[
        _column("facility_id", "어린이집 코드", DataType.STRING, SemanticType.FACILITY_ID),
        _column("name", "어린이집 이름", DataType.STRING, SemanticType.FACILITY_NAME),
        _column(
            "facility_type",
            "어린이집 유형 (국공립, 민간, 가정, 직장, 사회복지법인, 법인·단체등, 협동)",
            DataType.STRING,
            SemanticType.FACILITY_TYPE,
            nullable=True,
        ),
        _column("latitude", "위도 (WGS84)", DataType.FLOAT, SemanticType.LATITUDE, unit="degree"),
        _column("longitude", "경도 (WGS84)", DataType.FLOAT, SemanticType.LONGITUDE, unit="degree"),
        _column("geom", "어린이집 위치 Point (EPSG:4326)", DataType.GEOMETRY, SemanticType.GEOMETRY),
    ],
    join_keys=[],
)

TRUSTED_DATASETS: dict[str, DatasetMetadata] = {
    d.dataset_id: d for d in (EMD_BOUNDARY, POPULATION_BY_AGE, DAYCARE_FACILITY)
}
