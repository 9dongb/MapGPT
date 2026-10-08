# 공간 분석 AI Agent — MVP 설계안 (첫 번째 Vertical Slice)

> 기준 문서: `공간 분석 AI Agent 개발 전달 문서.md` (source of truth)
> 이 문서는 전달 문서 41번 "첫 작업 지시"의 16개 항목에 대한 설계안이며, 구현은 이 설계를 따른다.

## 0. 출발점

### 0.1 Repository 현황 (2026-10-07)

- 커밋된 파일은 `README.md` 하나뿐이다. 코드, 의존성, 인프라 설정이 없는 빈 저장소다.
- 개발 환경: conda `mapgpt` (Python 3.12), Docker Desktop (Apple Silicon), Node 23, Ollama 0.40 (모델 미설치).

### 0.2 사용자 결정 사항

| 항목 | 결정 |
|---|---|
| LLM | 운영은 **OpenAI**, 로컬 테스트는 **Ollama**. 환경변수로 전환한다. |
| Ollama 모델 | 사용자가 `qwen3.5:9b`를 준비했다. 실제 LLM E2E는 이 모델로 수행한다 (OpenAI는 키가 준비되면 같은 테스트로 확인). |
| 어린이집 데이터 | 서울 열린데이터광장 `ChildCareInfo` API. 사용자가 `SEOUL_OPEN_API_KEY`를 `.env`에 설정한다. |
| 경계·인구 원본 | 다운로드 허용 (`data/raw/`, git 제외) |
| 커밋 | 설계 1커밋(AGENTS.md·전달 문서 포함) + 구현 1커밋 |

### 0.3 데이터 조사 결과 (실제 파일 확인)

| Dataset | 원본 | 기준 시점 | 확인 사실 |
|---|---|---|---|
| `emd_boundary` | GitHub `vuski/admdongkor` `HangJeongDong_ver20260701.geojson` (통계청 SGIS 기반, CC BY 4.0), 34.6MB | 2026-07-01 | 전국 3,558개 / **서울 427개**, 전부 MultiPolygon, CRS84(=EPSG:4326 경위도 순서). `adm_cd2`가 10자리 행정안전부 행정기관코드이고, `adm_cd`는 8자리 통계청 코드다. |
| `population_by_age` | 공공데이터포털 `행정안전부_지역별(행정동) 성별 연령별 주민등록 인구수_20260930.csv`, 2.6MB | 2026-09-30 | cp949 인코딩의 wide 형식(230열: `0세남자`…`110세이상 여자`). 전국 3,619개 / **서울 427개** 행정동이며 `행정기관코드`는 10자리다. |
| `daycare_facility` | 서울 열린데이터광장 OpenAPI `ChildCareInfo` | 2026-10-07 | 총 9,495건(폐지·휴지 포함). `STCODE`(앞 5자리 = 시군구코드), `CRSTATUSNAME`(정상/휴지/폐지), `LA`/`LO`를 제공한다. 샘플 5건 중 3건이 **서울시청 좌표(37.566470, 126.977963) 기본값**을 갖고 있었다. |

- 경계와 인구의 10자리 코드는 **427개 모두 일치**한다(누락 0).
- 서울 0~5세 인구는 최소 33명(명동), 최대 2,502명(위례동), 합계 250,170명이다. 0명인 행정동은 없지만 0 분모 정책은 구현하고 테스트한다.

---

## 1. 전체 MVP Architecture

```text
 React + MapLibre UI ──POST /api/analyses──▶ FastAPI (app/api)
                                                  │
                                                  ▼
                                   AnalysisWorkflow (상태 머신, app/workflows)
   ┌───────────────┬───────────────┬──────────────┼───────────────┬───────────────┐
   ▼               ▼               ▼              ▼               ▼               ▼
 LLM Steps     DatasetCatalog  PlanValidator  OperationExecutor ResultValidator RunRepository
 (app/agents)  (app/catalog)   (app/validation) (app/executor)  (app/validation) (Provenance)
   │                                              │
   ▼                                              ▼
 StructuredLLM 포트 (app/llm)                 GIS Tools (app/gis)
 ├ OpenAIResponsesLLM                          get_dataset / get_boundary / filter_dataset
 └ OllamaChatLLM                               aggregate_by_area / aggregate
                                               calculate_ratio / rank / create_choropleth_layer
                                               (내부) transform_crs / validate_geometry
                                                  │  parameterized SQL (psycopg 3)
                                                  ▼
                                   PostgreSQL + PostGIS (Docker)
                                                  ▲
 Ingestion CLI (app/data_sources) ── Provider Adapter ── 외부 원본(GeoJSON / CSV / Seoul API)
```

**계층 책임과 의존 방향**

| 계층 | 책임 | 의존 가능 |
|---|---|---|
| `domain` | Core Contract(Pydantic 모델, Enum, 분석 정책). 외부 I/O가 없다. | (없음) |
| `llm` | 공급자별 Structured Output 호출. 공급자 차이를 숨긴다. | domain |
| `agents` | 프롬프트 구성, LLM 4단계(해석·선택·계획·설명) | domain, llm |
| `catalog` | Dataset 메타데이터 조회·검색 (향후 pgvector로 교체할 지점) | domain, repositories |
| `validation` | Plan/Result 결정론적 검증 | domain |
| `gis` | GIS Tool, CRS 정책, Filter → SQL 컴파일 | domain |
| `executor` | Operation → GIS Tool 매핑 실행 | domain, gis |
| `workflows` | 상태 머신, 최종 응답 조립 | 위 전부 |
| `data_sources` | 외부 원본 → 내부 표준 Dataset 정규화·적재 | domain, catalog |
| `api` | HTTP 경계 | workflows, catalog |

LLM은 `AnalysisPlan`(구조화 JSON)까지만 만든다. 수치 계산과 공간 연산은 전부 `executor → gis → PostGIS`가 수행한다. LLM이 SQL이나 Python 코드를 생성하는 경로는 존재하지 않는다.

---

## 2. Project Directory

```text
MapGPT/
├── pyproject.toml              # 의존성, pytest 설정
├── docker-compose.yml          # PostGIS (imresamu/postgis:17-3.5, Apple Silicon 네이티브)
├── .env.example                # DATABASE_URL, LLM_PROVIDER, OPENAI_*, OLLAMA_*, SEOUL_OPEN_API_KEY
├── docs/design/mvp-design.md   # 본 문서
├── app/
│   ├── config.py               # Settings (pydantic-settings, .env)
│   ├── cli.py                  # init-db / download / ingest / analyze
│   ├── db/                     # connect·init_schema + schema.sql (DDL, idempotent)
│   ├── domain/                 # ── Core Contract ──
│   │   ├── base.py             # StrictModel (extra="forbid")
│   │   ├── enums.py
│   │   ├── catalog.py          # DatasetMetadata, ColumnMetadata, JoinKey, Spatial/TemporalMetadata
│   │   ├── filters.py          # FilterExpression
│   │   ├── operations.py       # Operation Discriminated Union
│   │   ├── plan.py             # AnalysisPlan, Region, DatasetFilter, OutputSpec
│   │   ├── results.py          # ExecutionResult, ValidationReport, MapLayer, FinalResponse
│   │   ├── state.py            # AgentState, InterpretedQuery, DatasetSelection, Explanation
│   │   └── policies.py         # 분석 정책 (supply_demand_gap: ×1000, 오름차순)
│   ├── catalog/
│   │   ├── definitions.py      # Trusted Dataset 3종의 정적 메타데이터
│   │   └── catalog.py          # DatasetCatalog.search / get
│   ├── data_sources/
│   │   ├── adapters/           # admdongkor.py / mois_population.py / seoul_childcare.py
│   │   └── ingest.py           # 정규화 → 품질 규칙 → 적재 → 카탈로그 갱신
│   ├── gis/
│   │   ├── crs.py              # CRS Policy
│   │   ├── filter_sql.py       # FilterExpression → parameterized SQL
│   │   └── tools.py            # GIS Tools
│   ├── executor/
│   │   └── operation_executor.py
│   ├── validation/
│   │   ├── plan_validator.py
│   │   └── result_validator.py
│   ├── llm/
│   │   ├── base.py             # StructuredLLM 포트, LLMError
│   │   ├── schema.py           # Pydantic → 공급자 호환 JSON Schema
│   │   ├── openai_llm.py       # OpenAI Responses API
│   │   ├── ollama_llm.py       # Ollama (OpenAI 호환 Chat Completions)
│   │   └── factory.py          # LLM_PROVIDER로 선택
│   ├── agents/
│   │   ├── prompts.py
│   │   └── steps.py            # interpret / select / plan / explain
│   ├── workflows/
│   │   ├── analysis_workflow.py # 상태 머신 Orchestrator
│   │   └── response.py          # 결정론적 응답 섹션(방법·가정·한계) 조립
│   ├── repositories/
│   │   ├── catalog_repository.py
│   │   └── run_repository.py   # Provenance 저장/조회
│   └── api/
│       ├── main.py             # FastAPI app, 라우트
│       └── schemas.py          # Request/Response
├── tests/
│   ├── unit/                   # DB·네트워크 없음
│   ├── integration/            # PostGIS 필요 (mapgpt_test DB)
│   ├── e2e/                    # 실제 데이터 + 실제 LLM (opt-in)
│   ├── fixtures/               # 소형 GeoJSON 샘플, 첫 Use Case 기대 Plan
│   ├── fakes.py                # FakeLLM
│   └── support.py              # 공용 테스트 헬퍼
├── frontend/                   # Vite + React + TypeScript + maplibre-gl
└── data/raw/                   # 원본 데이터 (gitignore)
```

전달 문서 28번의 관심사 분리(LLM/Agent, Domain, Catalog, Adapter, GIS Execution, DB Access, Validation, API)는 그대로 유지한다. 하위 폴더는 파일이 1~2개뿐인 곳을 모듈로 평탄화했다.

---

## 3. Core Domain Model

```text
DatasetMetadata ─┬─ ColumnMetadata[]          (의미 단위 컬럼 설명)
                 ├─ JoinKey[]                 (field, semantic_type, code_system)
                 ├─ SpatialMetadata           (level, geometry_type, crs, coverage, bbox, feature_count)
                 └─ TemporalMetadata          (reference_date, update_cycle)

AnalysisPlan ────┬─ Region                    (name, level)
                 ├─ DatasetFilter[] ── FilterExpression = FilterCondition | FilterGroup
                 ├─ Operation[]  (discriminated union by "type")
                 │     AggregateByArea | Aggregate | CalculateRatio | Rank
                 └─ OutputSpec ── RankingSpec

AgentState ──── InterpretedQuery, DatasetSelection, AnalysisPlan, ValidationReport×2,
                ExecutionResult, MapLayer, FinalResponse, WorkflowError[]

ExecutionResult ─ UnitRow[] (key, name, parent_name, values{metric→값}, null_reasons{metric→사유})
                 ├ MetricInfo[] / OperationLog[] (Provenance용 실행 기록)
                 └ boundary 통계 (unit_count, invalid_geometry_count, bbox)

IntentPolicy (domain/policies.py) ─ intent별 명시적 분석 정책 (ratio scale, rank 방향, 개념 정의, 고정 한계)
```

- 모든 계약 모델은 `StrictModel`(`extra="forbid"`)을 상속한다. 정의되지 않은 필드는 거부한다.
- Enum은 `StrEnum`으로 정의한다. Intent·Operator 등을 확장할 때는 멤버만 추가하면 된다.
- LLM 출력 모델(InterpretedQuery, DatasetSelection, AnalysisPlan, Explanation)은 **공급자 Structured Output 제약**을 만족하도록 설계한다(6.2 참고).

---

## 4. DatasetMetadata Pydantic Schema

```python
class ColumnMetadata(StrictModel):
    name: str
    description: str                 # LLM에 제공하는 의미 설명 (향후 embedding source)
    data_type: DataType              # string | integer | float | boolean | date | geometry
    semantic_type: SemanticType      # administrative_code, population, age, latitude, ...
    unit: str | None = None          # person, year, degree ...
    nullable: bool = False

class JoinKey(StrictModel):
    field: str
    semantic_type: SemanticType
    code_system: str | None = None   # 예: "mois_adm_cd" (행안부 10자리). 통계청 8자리와의 오조인 방지

class RegionRef(StrictModel):
    name: str                        # "서울특별시"
    level: SpatialLevel              # sido
    code: str                        # "11"

class SpatialMetadata(StrictModel):
    level: SpatialLevel | None       # 데이터가 표현하는 공간 단위 (점 데이터는 None)
    geometry_type: GeometryType | None   # Point | Polygon | MultiPolygon | None
    crs: str | None                  # "EPSG:4326" — 공간 데이터는 필수 (validator로 강제)
    coverage: RegionRef | None       # 데이터가 커버하는 지역
    bbox: list[float] | None = None  # EPSG:4326 [minx, miny, maxx, maxy], 적재 시 계산
    feature_count: int | None = None # 적재 시 계산

class TemporalMetadata(StrictModel):
    reference_date: date | None      # 적재 시 원본에서 추출
    update_cycle: str | None         # monthly | irregular ...

class DatasetMetadata(StrictModel):
    dataset_id: str
    title: str
    description: str
    category: str
    semantic_tags: list[str]
    provider: str
    source: str                      # 원본 URL/식별자
    license: str | None
    spatial: SpatialMetadata
    temporal: TemporalMetadata
    columns: list[ColumnMetadata]
    join_keys: list[JoinKey]
    quality_notes: list[str] = []    # 적재 품질 기록 (예: "좌표 오류로 N건 제외") → 결과의 한계로 노출
```

- 저장 테이블은 `datasets.<dataset_id>` 규칙을 따르므로 메타데이터에 저장 위치 필드를 두지 않는다. 식별자는 카탈로그에 등록된 이름만 `sql.Identifier`로 사용한다.
- 지오메트리도 `data_type=geometry` 컬럼으로 `columns`에 포함한다. 필터 대상으로는 쓸 수 없다.

### 4.1 Trusted Dataset 3종 (내부 표준 형태)

| dataset_id | 컬럼 (내부 표준) | join key | spatial |
|---|---|---|---|
| `emd_boundary` | `adm_cd`(10자리), `adm_nm`(동명), `sido_cd`, `sido_nm`, `sigungu_cd`, `sigungu_nm`, `geom` | `adm_cd` (administrative_code, mois_adm_cd) | emd / MultiPolygon / EPSG:4326 / 서울특별시 |
| `population_by_age` | `adm_cd`, `age`(0~110, 110=110세 이상), `population`(남+여), `reference_date` | `adm_cd` (동일) | emd / 지오메트리 없음 / 서울특별시 |
| `daycare_facility` | `facility_id`(STCODE), `name`, `facility_type`(국공립·민간·가정…), `latitude`, `longitude`, `geom` (기준 시점은 Dataset temporal) | 없음(공간 관계로 결합) | Point / EPSG:4326 / 서울특별시 |

`daycare_facility`의 포함 기준은 운영현황이 '정상' 또는 '재개'이고 좌표 품질 규칙을 통과한 시설이다(13.3). 제외 건수는 `quality_notes`에 기록한다.

---

## 5. FilterExpression Pydantic Schema

```python
Scalar = str | int | float | bool

class FilterCondition(StrictModel):
    field: str
    operator: FilterOperator        # eq neq gt gte lt lte between in not_in contains starts_with is_null is_not_null
    value: Scalar | list[Scalar] | None = None
    # model_validator: operator별 value 형태 검사
    #   is_null/is_not_null → None | between → 숫자 2개 [low<=high] | in/not_in → 비어있지 않은 list
    #   contains/starts_with → str | 비교 연산자 → 단일 scalar

class FilterGroup(StrictModel):
    logic: LogicalOperator          # and | or | not  (not은 조건 정확히 1개)
    conditions: list[FilterCondition]   # 1개 이상

FilterExpression = FilterCondition | FilterGroup   # 필드 구성으로 구분 (extra=forbid)
```

**설계 결정: Group은 1단계까지만 둔다(재귀 미사용).** 전달 문서는 재귀를 선택사항으로 두었다. 소형 로컬 모델(Ollama)의 출력 안정성과 MVP 필요 범위(13.2 예시)를 고려해 1단계로 제한한다. 필요해지면 깊이 제한 모델을 Union 멤버로 추가한다.

**컴파일 (`gis/filter_sql.py`)**: 메타데이터로 field 존재·타입을 확인한 뒤 `psycopg.sql`로 조립한다.

| operator | SQL | 비고 |
|---|---|---|
| eq / neq | `col = %s` / `col <> %s` | 값은 컬럼 data_type으로 Python 변환(int/float/str/date) |
| gt gte lt lte | `col > %s` … | 숫자·날짜 컬럼만 |
| between | `col BETWEEN %s AND %s` | |
| in / not_in | `col = ANY(%s)` / `NOT (col = ANY(%s))` | list 파라미터 |
| contains / starts_with | `col LIKE %s ESCAPE '\'` | `%`,`_`,`\` 이스케이프 후 `%v%` / `v%`. 문자열 컬럼만 |
| is_null / is_not_null | `col IS NULL` / `col IS NOT NULL` | |
| and / or / not | `(a AND b)` / `(a OR b)` / `NOT (a)` | |

컬럼명은 `sql.Identifier`로 쓰고 값은 전부 파라미터로 넘긴다. LLM이 만든 문자열이 SQL 텍스트에 들어가는 경로는 없다.

---

## 6. AnalysisPlan Pydantic Schema

```python
class Region(StrictModel):
    name: str                        # 공식 명칭 "서울특별시"
    level: SpatialLevel              # sido

class DatasetFilter(StrictModel):
    dataset: str
    where: FilterExpression

class RankingSpec(StrictModel):
    enabled: bool
    limit: int = Field(10, ge=1, le=50)

class OutputSpec(StrictModel):
    map_type: MapType                # choropleth
    metric: str                      # 지도에 표현할 Operation output
    ranking: RankingSpec

class AnalysisPlan(StrictModel):
    intent: AnalysisIntent           # supply_demand_gap
    region: Region
    analysis_unit: SpatialLevel      # emd
    datasets: list[str]              # min 1
    filters: list[DatasetFilter] = []
    operations: list[Operation]      # min 1, 실행 순서
    output: OutputSpec
```

### 6.1 첫 Use Case의 기대 Plan

```json
{
  "intent": "supply_demand_gap",
  "region": {"name": "서울특별시", "level": "sido"},
  "analysis_unit": "emd",
  "datasets": ["emd_boundary", "population_by_age", "daycare_facility"],
  "filters": [
    {"dataset": "population_by_age",
     "where": {"logic": "and", "conditions": [{"field": "age", "operator": "between", "value": [0, 5]}]}}
  ],
  "operations": [
    {"type": "aggregate_by_area", "label": "어린이집 수", "input": "daycare_facility",
     "boundary": "emd_boundary", "aggregation": "count", "output": "daycare_count"},
    {"type": "aggregate", "label": "0~5세 인구", "input": "population_by_age", "group_by": ["adm_cd"],
     "aggregation": {"field": "population", "function": "sum"}, "output": "child_population"},
    {"type": "calculate_ratio", "label": "0~5세 어린이 1,000명당 어린이집 수",
     "numerator": "daycare_count", "denominator": "child_population", "scale": 1000,
     "output": "daycare_per_1000_children"},
    {"type": "rank", "label": "부족 순위", "input": "daycare_per_1000_children", "order": "asc",
     "output": "shortage_rank"}
  ],
  "output": {"map_type": "choropleth", "metric": "daycare_per_1000_children",
             "ranking": {"enabled": true, "limit": 10}}
}
```

### 6.2 전달 문서 예시 대비 변경점과 이유

| 변경 | 이유 |
|---|---|
| `filters`: `{dataset_id: expr}` 객체 → `[{dataset, where}]` 리스트 | OpenAI strict / Ollama 문법 제약은 임의 키 객체(`additionalProperties`가 스키마인 경우)를 표현하지 못한다. 의미는 같다. |
| 각 Operation에 `label` (짧은 한국어 이름) 추가 | 최종 응답의 `metric.description`, 랭킹 표 헤더, 범례에 사람이 읽는 이름이 필요하다. 실제 계산 내용은 결정론적으로 렌더링한 `analysis_method`가 별도로 보여준다. |
| 모든 필드를 LLM 스키마에서 required로 둠 (nullable로 생략 표현) | OpenAI strict 모드 규칙이다. Pydantic 기본값은 코드에서 생성할 때만 쓰인다. |

---

## 7. Operation Discriminated Union

```python
class AggregateByAreaOperation(StrictModel):
    type: Literal["aggregate_by_area"]
    label: str
    input: str                       # Point Dataset ID
    boundary: str                    # Polygon Dataset ID
    aggregation: AreaAggregation     # count (MVP)
    output: MetricName               # ^[a-z][a-z0-9_]*$

class AggregationSpec(StrictModel):
    field: str
    function: AggregationFunction    # sum | count

class AggregateOperation(StrictModel):
    type: Literal["aggregate"]
    label: str
    input: str                       # Dataset ID
    group_by: list[str]              # MVP: 분석 단위 join key 1개
    aggregation: AggregationSpec
    output: MetricName

class CalculateRatioOperation(StrictModel):
    type: Literal["calculate_ratio"]
    label: str
    numerator: str                   # 앞선 Operation output
    denominator: str                 # 앞선 Operation output
    scale: float = Field(1.0, gt=0)
    output: MetricName

class RankOperation(StrictModel):
    type: Literal["rank"]
    label: str
    input: str                       # 앞선 Operation output
    order: SortOrder                 # asc | desc
    output: MetricName

Operation = Annotated[
    AggregateByAreaOperation | AggregateOperation | CalculateRatioOperation | RankOperation,
    Field(discriminator="type"),
]
```

- **참조 규칙**: `input`/`boundary`(공간·속성 집계)는 Dataset ID를, `numerator`/`denominator`/`rank.input`은 **앞에서 정의된** Operation output을 가리킨다. 모든 output은 분석 단위(행정동) key별 값이다.
- 새 Operation은 기존 스키마를 바꾸지 않고 Union 멤버와 executor handler를 추가하는 방식으로 확장한다. 단위 테스트로 Union의 모든 멤버에 handler가 있는지 확인한다.
- LLM용 JSON Schema 변환(`llm/schema.py`)에서는 Pydantic이 만든 `oneOf`+`discriminator`를 `anyOf`로 바꾸고, `const`는 `enum`으로 바꾸고, 수치·길이 제약은 제거한다. 제거한 제약은 응답을 받은 뒤 Pydantic이 다시 검증한다.

---

## 8. Agent State

```python
class InterpretedQuery(StrictModel):        # LLM 출력
    intent: AnalysisIntent | None            # None = 지원 범위 밖
    unsupported_reason: str | None
    region: Region | None
    analysis_unit: SpatialLevel | None
    restated_question: str                   # 분석 질문 재진술
    key_concepts: list[str]                  # 카탈로그 검색어 (예: 어린이집, 0~5세 인구)
    assumptions: list[str]                   # 해석 과정의 가정

class DatasetSelection(StrictModel):        # LLM 출력
    datasets: list[str]
    rationale: str

class Explanation(StrictModel):             # LLM 출력
    summary: str

class WorkflowError(StrictModel):
    step: WorkflowStep
    code: str                                # UNSUPPORTED_QUESTION, PLAN_INVALID, LLM_FAILED ...
    message: str
    issues: list[ValidationIssue] = []

class AgentState(BaseModel):
    run_id: str
    question: str
    status: RunStatus                        # running | succeeded | failed
    current_step: WorkflowStep | None = None
    interpreted_query: InterpretedQuery | None = None
    dataset_candidates: list[DatasetMetadata] = []   # LLM이 본 메타데이터를 그대로 기록
    dataset_selection: DatasetSelection | None = None # LLM 선택 원본 (근거 포함, 검사 전에 기록)
    selected_datasets: list[str] = []                 # 검사를 통과한 선택 (중복 제거)
    analysis_plan: AnalysisPlan | None = None
    plan_history: list[PlanAttempt] = []   # 재생성을 포함한 모든 계획 시도 (plan + 검증 결과)
    plan_validation: ValidationReport | None = None
    execution_results: ExecutionResult | None = None
    result_validation: ValidationReport | None = None
    map_layer: MapLayer | None = None
    final_response: FinalResponse | None = None
    errors: list[WorkflowError] = []
    llm_provider: str
    llm_model: str
    started_at: datetime
    finished_at: datetime | None = None
```

상태 전체를 Provenance(`analysis.run.state`)에 JSONB로 저장한다. "LLM이 무엇을 보고 무엇을 판단했는가"를 재현하기 위해서다.

---

## 9. GIS Tool Interfaces

Tool은 `app/gis/tools.py`의 타입 있는 함수다. 실패하면 `GisToolError(code, message)`를 던진다. 데이터는 PostGIS에 그대로 두고, View는 (메타데이터 + 필터) 참조만 들고 다닌다(지연 평가).

```python
class DatasetView(BaseModel):     metadata; filter: FilterExpression | None; row_count: int
class BoundaryView(DatasetView):  region: RegionRef; key_field; name_field; parent_name_field
                                  unit_count; invalid_geometry_count; bbox: list[float]
class MetricValues(BaseModel):    name; values: dict[key, float|int|None]
                                  null_reasons: dict[key, str]; stats: dict[str, int|float]
```

전달 문서 18번의 `result_ref`는 Operation의 `output` 이름이다. Executor가 `MetricValues`를 그 이름으로 `ExecutionContext.metrics`에 등록한다.

| Tool | 목적 | Input → Output | Validation | 실패 조건 (code) |
|---|---|---|---|---|
| `get_dataset` | 등록 Dataset 테이블 참조 확보 | metadata → DatasetView | 테이블 존재, row>0 | `DATASET_TABLE_MISSING`, `DATASET_EMPTY` |
| `get_boundary` | 분석 지역의 경계 Polygon 집합 | metadata, region → BoundaryView | Polygon 계열, CRS 명시, 지역 해석, key 유일, `validate_geometry` | `NOT_POLYGON`, `CRS_MISSING`, `REGION_NOT_FOUND`, `DUPLICATE_UNIT_KEY`, `INVALID_GEOMETRY` |
| `filter_dataset` | FilterExpression을 View에 적용 | view, expr → DatasetView | field 존재, operator·값 타입 호환, 결과 row>0 | `FILTER_FIELD_UNKNOWN`, `FILTER_TYPE_MISMATCH`, `FILTER_EMPTY_RESULT` |
| `aggregate_by_area` | Point → Polygon 공간 집계 | input view, boundary view, `count` → MetricValues | Point·Polygon 여부, CRS 정규화(`transform_crs`), 지원 aggregation | `NO_GEOMETRY`, `NOT_POINT`, `NOT_POLYGON`, `CRS_UNSUPPORTED`, `UNSUPPORTED_AGGREGATION` |
| `aggregate` | 속성 그룹 집계 | view, group_by, field, function → MetricValues | group_by 1개, field 존재·숫자형(sum) | `FIELD_UNKNOWN`, `FIELD_NOT_NUMERIC`, `MULTI_GROUP_UNSUPPORTED`, `UNSUPPORTED_AGGREGATION` |
| `calculate_ratio` | 분자/분모×scale | 두 MetricValues, scale, unit keys → MetricValues | 분모 0/없음 → `null` + 사유, 결과 유한값 | `NON_FINITE_RESULT` |
| `rank` | 순위 | MetricValues, order → MetricValues | null 제외, 동순위 표준 경쟁 순위(1,2,2,4) | — |
| `create_choropleth_layer` | Choropleth GeoJSON | boundary view, 결과 행, metric → MapLayer | 출력 EPSG:4326, 좌표 경위도 범위, 모든 feature에 geometry | `OUTPUT_CRS_INVALID`, `GEOMETRY_MISSING` |
| `transform_crs` (내부) | 연산 전 CRS 정규화 | geom SQL, src, dst → SQL 조각 | 지원 SRID {4326, 5179} | `CRS_UNSUPPORTED` |
| `validate_geometry` (내부) | 유효성 점검 | view → {invalid, empty, null} 개수 | `ST_IsValid`, `ST_IsEmpty` | (호출자가 판정) |

**aggregate_by_area SQL 요지**

```sql
WITH units AS (SELECT key, geom FROM boundary WHERE <region filter>),
     pts AS (SELECT id, <transform_crs(geom → boundary SRID)> AS geom FROM input WHERE <filter>),
     assigned AS (SELECT DISTINCT ON (p.id) p.id, u.key
                  FROM pts p JOIN units u ON ST_Covers(u.geom, p.geom)
                  ORDER BY p.id, u.key)              -- 경계선 위 점은 코드가 작은 행정동 하나에만 배정
SELECT u.key, count(a.id) FROM units u LEFT JOIN assigned a USING (key) GROUP BY u.key;
```

시설이 없는 행정동은 0이다. 지역 밖 점(미배정)의 수는 `stats.unassigned_points`에 기록하고 결과 검증에서 경고로 보고한다.

**CRS Policy (`gis/crs.py`)**: 지도 출력은 EPSG:4326이다. Point-in-Polygon처럼 위상 연산은 경계 Dataset의 SRID로 맞춘다. 거리·면적 연산(EPSG:5179)은 두 번째 Vertical Slice에서 정책에 추가한다. LLM은 CRS를 결정하지 않는다.

---

## 10. Plan Validator 구조

`validate_plan(plan, datasets: Mapping[str, DatasetMetadata], selected: Sequence[str]) -> ValidationReport`

순수 함수다(DB 없음). 규칙 함수들이 `ValidationIssue(code, severity, message, path)`를 누적한다. Operation을 순서대로 훑으면서 **심볼 테이블**(정의된 metric 이름 → 출처·숫자 여부)을 만든다. 오류가 1개라도 있으면 실행하지 않는다.

| 전달 문서 20번 항목 | 규칙 (code) |
|---|---|
| Dataset ID가 실제 존재하는가 | `UNKNOWN_DATASET` |
| 필요 Dataset이 모두 있는가 | `DATASET_NOT_DECLARED`(참조했는데 `datasets`에 없음), `DATASET_NOT_SELECTED`(선택 단계 밖), `UNUSED_DATASET`(경고) |
| Filter field가 존재하는가 | `FILTER_FIELD_UNKNOWN`, `FILTER_TYPE_MISMATCH`, `DUPLICATE_FILTER` |
| Operation input이 존재하는가 | `OPERATION_INPUT_UNKNOWN` (Dataset 또는 *앞서 정의된* metric) |
| output 이름 충돌 | `OUTPUT_NAME_CONFLICT` (중복, Dataset ID·경계 컬럼명과 충돌) |
| Geometry가 있는가 / 타입이 적절한가 | `GEOMETRY_REQUIRED`, `GEOMETRY_TYPE_INVALID` (input=Point, boundary=Polygon 계열) |
| CRS를 처리할 수 있는가 | `CRS_UNSUPPORTED` (CRS 누락 또는 정책 밖 SRID) |
| Join 가능한 키/공간 관계가 있는가 | `JOIN_KEY_INCOMPATIBLE` (group_by가 경계 join key와 semantic_type·code_system·level 일치) |
| Ratio denominator가 유효한가 | `RATIO_OPERAND_INVALID` (숫자 metric, 분자≠분모, rank 결과 사용 금지) |
| 지원하지 않는 Operation | Pydantic discriminated union이 1차로 거부하고, handler 누락은 테스트로 보장한다 |
| Output metric이 실제 계산되는가 | `OUTPUT_METRIC_NOT_COMPUTED`, `RANKING_NOT_DEFINED` (ranking.enabled면 output.metric에 대한 rank 존재) |
| (보완) 분석 단위·지역 | `UNIT_BOUNDARY_MISSING`/`AMBIGUOUS`(analysis_unit의 Polygon Dataset이 정확히 1개), `REGION_NOT_COVERED` (region이 Dataset coverage와 일치) |
| (보완) 분석 정책 준수 | `POLICY_VIOLATION` (supply_demand_gap: output.metric이 ratio이고 scale=1000, rank=asc) |

**재생성 루프**: Pydantic 파싱 실패나 Plan Validator 오류가 나면 오류 목록을 LLM에 피드백해 **최대 1회** 다시 만든다. 그래도 실패하면 `PLAN_INVALID`로 종료하고 오류 목록을 반환한다.

---

## 11. Operation Executor 구조

```python
class ExecutionContext:                 # load_data 단계에서 생성
    conn                                # 읽기 전용 트랜잭션 (REPEATABLE READ, READ ONLY)
    plan: AnalysisPlan
    views: dict[str, DatasetView]       # 필터가 적용된 Dataset View
    boundary: BoundaryView              # 분석 단위 경계 (결과 프레임의 기준)
    metrics: dict[str, MetricValues]    # output 이름(result_ref) → 결과
    logs: list[OperationLog]            # type, output, tool, 입력 요약, stats, duration_ms

HANDLERS: dict[str, Handler] = {
    "aggregate_by_area": _run_aggregate_by_area,   # → tools.aggregate_by_area
    "aggregate":         _run_aggregate,           # → tools.aggregate
    "calculate_ratio":   _run_calculate_ratio,     # → tools.calculate_ratio
    "rank":              _run_rank,                # → tools.rank
}

def prepare_context(conn, plan, datasets) -> ExecutionContext   # get_boundary / get_dataset / filter_dataset
def execute_operations(ctx) -> ExecutionResult                  # 순서대로 handler 실행 → 결과 조립
```

- **결과 조립**: 경계 View의 행정동 목록(key, 동명, 자치구명)을 기준으로, 각 metric을 key로 LEFT JOIN해 `UnitRow`를 만든다.
- **결측 의미**: count는 0이다(관측된 0). sum 결과가 없는 단위는 `null`이다(인구 정보 없음). ratio의 분모가 0이면 `null` + `denominator_zero`, 분모가 없으면 `null` + `denominator_missing`이다. 0으로 대체하지 않는다.
- 단위 목록에 매칭되지 않은 metric key(예: 경계에 없는 인구 코드)는 `ExecutionResult.unmatched_keys`에 기록한다.

---

## 12. 첫 Vertical Slice Sequence

```text
UI ─POST /api/analyses {question}─▶ API ─▶ AnalysisWorkflow.run(question)
 1 interpret_query      LLM(InterpretedQuery)  ← 질문 + 지원 intent/단위 + 카탈로그 coverage + 분석 정책
                        intent=None이면 UNSUPPORTED_QUESTION, 데이터 없는 지역·단위면 REGION/UNIT_NOT_SUPPORTED로 종료
 2 select_datasets      catalog.search(key_concepts) → 후보 3개 → LLM(DatasetSelection) → 후보 내 ID인지 확인
 3 build_analysis_plan  LLM(AnalysisPlan)      ← 해석 + 선택 Dataset 메타데이터(컬럼/join key/공간/시간) + 정책
 4 validate_plan        PlanValidator → 오류면 3으로 1회 복귀(피드백), 재실패 시 PLAN_INVALID
 5 load_data            get_boundary(emd_boundary, 서울특별시) / get_dataset(population_by_age)
                        + filter_dataset(age between 0~5) / get_dataset(daycare_facility)
 6 execute_operations   aggregate_by_area(count) → daycare_count
                        aggregate(sum population by adm_cd) → child_population
                        calculate_ratio(÷, ×1000) → daycare_per_1000_children
                        rank(asc) → shortage_rank → UnitRow 조립
 7 validate_result      ResultValidator → 오류면 RESULT_INVALID, 경고는 한계로 전달
 8 create_map_layer     create_choropleth_layer → GeoJSON(EPSG:4326) + 5분위(quantile) 구간
 9 generate_explanation LLM(Explanation)       ← 상위 랭킹·요약 통계·경고·기준 시점 (주어진 수치만 사용)
10 compose & persist    FinalResponse 조립(방법·가정·한계는 결정론적) → analysis.run / analysis.result 저장
 ◀─ {run_id, status, result, errors} ── UI: 지도 + Ranking + Metric + Dataset·기준 시점 + 방법·가정·한계
```

각 단계는 `(state) -> 다음 단계`를 반환하는 핸들러다. 예외는 `WorkflowError`로 기록하고 `failed`로 전이한다. 성공이든 실패든 항상 Provenance를 저장한다.

**최종 응답(FinalResponse) 구성 원칙**: LLM이 쓰는 것은 `summary`뿐이다. `metric`, `ranking`, `map_layer`, `datasets`(+기준 시점), `analysis_method`(실행 Plan으로 렌더링), `assumptions`(정책 + 해석 가정), `limitations`(정책 고정 한계 + Dataset quality_notes + 검증 경고 + 기준 시점 차이)는 결정론적으로 조립한다.

---

## 13. 필요한 DB Table

### 13.1 스키마

```sql
CREATE EXTENSION IF NOT EXISTS postgis;
CREATE SCHEMA catalog;  CREATE SCHEMA datasets;  CREATE SCHEMA analysis;

-- Dataset Catalog (향후 pgvector embedding 컬럼을 추가할 위치)
CREATE TABLE catalog.dataset (
  dataset_id text PRIMARY KEY,
  metadata   jsonb NOT NULL,              -- DatasetMetadata 전체 (적재 통계·품질 기록 포함)
  loaded_at  timestamptz NOT NULL
);

-- 내부 표준 Dataset
CREATE TABLE datasets.emd_boundary (
  adm_cd text PRIMARY KEY, adm_nm text NOT NULL,
  sido_cd text NOT NULL, sido_nm text NOT NULL, sigungu_cd text NOT NULL, sigungu_nm text NOT NULL,
  geom geometry(MultiPolygon, 4326) NOT NULL
);
CREATE INDEX ON datasets.emd_boundary USING gist (geom);

CREATE TABLE datasets.population_by_age (
  adm_cd text NOT NULL, age integer NOT NULL CHECK (age >= 0),
  population integer NOT NULL CHECK (population >= 0), reference_date date NOT NULL,
  PRIMARY KEY (adm_cd, age)
);

CREATE TABLE datasets.daycare_facility (
  facility_id text PRIMARY KEY, name text NOT NULL, facility_type text,
  latitude double precision NOT NULL, longitude double precision NOT NULL,
  geom geometry(Point, 4326) NOT NULL
);
CREATE INDEX ON datasets.daycare_facility USING gist (geom);

-- Provenance
CREATE TABLE analysis.run (
  run_id uuid PRIMARY KEY, question text NOT NULL, status text NOT NULL,
  analysis_plan jsonb, datasets jsonb,      -- [{dataset_id, reference_date}]
  operations jsonb, crs text,               -- 실행 Operation 기록, 분석 CRS
  result_id uuid, llm_provider text, llm_model text,
  errors jsonb, state jsonb NOT NULL,       -- AgentState 전체
  started_at timestamptz NOT NULL, finished_at timestamptz
);
CREATE TABLE analysis.result (
  result_id uuid PRIMARY KEY, run_id uuid NOT NULL REFERENCES analysis.run,
  response jsonb NOT NULL,                  -- FinalResponse (GeoJSON 포함)
  created_at timestamptz NOT NULL
);
```

전달 문서 24번 Provenance 항목(run_id, 질문, Dataset ID·기준 시점, Plan, 실행 Operation, CRS, 실행 시각, 결과 ID)은 모두 `analysis.run`의 컬럼에 매핑된다.

### 13.2 적재 (`python -m app.cli ingest all`)

순서: `emd_boundary` → `population_by_age` → `daycare_facility`(경계를 품질 규칙에 쓰므로 마지막에 적재). Dataset마다 한 트랜잭션에서 테이블을 교체한다. 그 뒤 `bbox`·`feature_count`·`reference_date`·`quality_notes`를 계산해 `catalog.dataset`을 upsert한다.

- `emd_boundary`: `sido == "11"`만 남긴다. `adm_cd2` → `adm_cd`, `adm_nm`은 마지막 토큰(동명), `ST_Multi(ST_MakeValid(ST_SetSRID(ST_GeomFromGeoJSON(...), 4326)))`.
- `population_by_age`: cp949로 읽고 서울(`11*`)만 남긴다. 연령별 남+여를 long 형식 `(adm_cd, age, population)`으로 변환한다(110세 이상 → 110). `기준연월` → `reference_date`. 정합성(계 = 연령 합) 검사.
- `daycare_facility`: API를 1,000건 단위로 페이지 수집한다(원본 JSON은 `data/raw/`에 캐시).

### 13.3 어린이집 좌표 품질 규칙 (적재 시, 결정론적)

1. 운영현황 `정상`·`재개`(휴지 후 운영 재개)만 포함한다(휴지·폐지·미기재 제외).
2. 좌표가 없거나, 파싱되지 않거나, 대한민국 범위 밖이면 제외한다.
3. **서로 다른 자치구의 시설들이 같은 좌표를 공유하면** 기본값 좌표로 보고, 그 좌표의 시설을 모두 제외한다(서울시청 기본값 대응).
4. 좌표가 위치한 자치구가 신고 자치구(`STCODE` 앞 5자리)와 다르거나 서울 경계 밖이면 제외한다.

규칙별 제외 건수는 `quality_notes`에 기록하고 최종 응답의 한계에 노출한다. 실제 전체 데이터를 적재한 뒤 제외 규모를 확인해 보고한다.

---

## 14. REST API

| Method | Path | 설명 |
|---|---|---|
| `POST` | `/api/analyses` | `{"question": str}` → 워크플로를 동기 실행한다. `200 {run_id, status, result: FinalResponse \| null, errors: WorkflowError[]}`. 분석 실패(지원 범위 밖, Plan 무효 등)도 run이 기록되므로 200 + `status="failed"`다. 요청 형식 오류는 422, 서버 장애는 500이다. |
| `GET` | `/api/analyses/{run_id}` | Provenance(상태 전체)와 결과를 조회한다. 없으면 404. |
| `GET` | `/api/datasets` | 카탈로그 메타데이터 목록 |
| `GET` | `/api/health` | DB 연결, LLM provider/model |

**FinalResponse (전달 문서 22번)**

```python
class FinalResponse(StrictModel):
    run_id: str; result_id: str; question: str
    summary: str                                   # LLM
    metric: MetricDescription                      # name, label(설명), interpretation("낮을수록 공급 부족")
    ranking: list[RankingItem]                     # rank, unit_key, unit_name, parent_name, value, values{}
    map_layer: MapLayer                            # GeoJSON FeatureCollection + quantile breaks
    analysis_method: list[str]                     # 실행 Plan 렌더링
    datasets: list[DatasetUsage]                   # dataset_id, title, provider, source, reference_date, license
    assumptions: list[str]
    limitations: list[str]
```

**UI (frontend/)**: 질문 입력, 단계 진행 표시, MapLibre Choropleth(5분위, 낮을수록 진한 색으로 부족을 강조, null은 회색, hover 툴팁), 랭킹 표(순위·자치구·동·어린이집 수·0~5세 인구·지표), Metric/Dataset(기준 시점)/분석 방법/가정/한계 패널, 실패 시 단계와 오류 목록. 배경지도는 키가 필요 없는 OpenFreeMap 벡터 스타일(positron / dark, © OpenMapTiles · OpenStreetMap)이다. 개발 서버는 `/api`를 FastAPI로 프록시한다.

---

## 15. Test Strategy

| 계층 | 범위 | 환경 |
|---|---|---|
| **Unit** | 도메인 스키마(유효/무효 Plan, Filter value 형태, union 판별, 미지원 type 거부), LLM JSON Schema 변환(oneOf·dict·기본값 없음, 전 필드 required, additionalProperties=false), Filter SQL 컴파일(연산자별 SQL·파라미터, 주입 시도 값이 파라미터로만 전달), Plan Validator(규칙별 음성 케이스 + 정상 Plan), ratio/rank(0·결측 분모, 동순위, null), Result Validator 규칙, Adapter(소형 fixture 파일 파싱), LLM 어댑터 요청 형식(HTTP mock), Executor handler가 Union 전 멤버를 커버하는지 | DB·네트워크 없음 |
| **Integration** | GIS Tool을 합성 데이터로 검증한다: 정사각형 2개 경계, 내부/외부/공유 경계선 위 점, **EPSG:5179로 저장한 점의 CRS 정규화**, 0 분모·결측 단위 인구. 정확한 count·ratio·rank, Choropleth GeoJSON 유효성, 적재 파이프라인(fixture → 테이블 → 카탈로그), Workflow 전체를 FakeLLM으로 실행해 FinalResponse·Provenance 저장 확인, API(TestClient) | Docker PostGIS의 `mapgpt_test` DB. 연결이 불가하면 사유와 함께 skip |
| **E2E** (opt-in `-m e2e`) | 실제 적재 데이터 + 실제 LLM(OpenAI 또는 Ollama)으로 대표 질문을 실행해 40번 성공 기준 1~12를 단언한다 | API 키 또는 Ollama 모델 필요 |

LLM 응답은 비결정적이므로 Unit/Integration에서는 FakeLLM(사전에 정한 구조화 출력)을 쓴다. "LLM이 올바르게 해석·선택·계획하는가"는 E2E에서 확인한다.

---

## 16. 구현 순서

| # | 단계 | 검증 |
|---|---|---|
| 1 | 골격: `pyproject.toml`, `docker-compose.yml`, `config`, `db`, `schema.sql`, `cli init-db`, `.gitignore`, `.env.example` | PostGIS 기동, `init-db` 반복 실행이 멱등 |
| 2 | **Phase 1 Core Schema**: domain 모델 전체 + LLM JSON Schema 변환 | Unit: 스키마 유효/무효, 첫 Use Case Plan 파싱 |
| 3 | **Phase 2 Dataset**: 3개 Adapter + 적재 + 카탈로그 정의 + 좌표 품질 규칙 | Unit(fixture), 실제 적재 후 행정동 427·코드 매칭·좌표 제외 규모 확인 |
| 4 | **Phase 3 GIS Execution**: Filter 컴파일, GIS Tools, Executor | Integration(합성 데이터 정답 비교), 6.1 Plan을 실제 데이터에 직접 실행 |
| 5 | **Phase 5 Validation**: Plan Validator, Result Validator, Geometry/CRS 검증 | Unit(규칙별), 실제 결과에 Result Validator 통과 |
| 6 | **Phase 4 LLM Integration**: 포트 + OpenAI/Ollama 어댑터 + 프롬프트 + 4단계 + 상태 머신 Workflow + Provenance | Unit(FakeLLM, HTTP mock), Integration(Workflow 전체) |
| 7 | **Phase 6 API/UI**: FastAPI + React/MapLibre | API 테스트, 브라우저에서 지도·랭킹·패널 확인 |
| 8 | 마무리: README 실행 방법, 전체 테스트, 커밋 | `pytest` 통과, diff 검토 |

Validation(5)을 LLM 연동(6)보다 먼저 한다. LLM 출력은 처음부터 검증 게이트를 통과해야만 실행되어야 하기 때문이다. 결정론적 파이프라인을 손으로 쓴 Plan으로 먼저 완성해 두면, LLM은 그 Plan을 생성하는 역할만 하면 된다.

---

## 부록 A. 명시적 가정

1. 데이터는 서울만 적재한다(coverage = 서울특별시). 다른 지역 질문은 Plan Validation에서 `REGION_NOT_COVERED`로 명시적으로 실패한다.
2. 행정동 코드는 행정안전부 10자리 행정기관코드로 통일한다(통계청 8자리 미사용).
3. 0~5세는 주민등록 기준 만 나이 0~5세(1세 단위 남+여 합계)다. 이 개념 정의는 분석 정책에 둔다.
4. 어린이집 수는 운영 중('정상'·'재개') 시설 수다. 정원·현원은 반영하지 않는다(한계로 명시).
5. 데이터 기준 시점은 경계 2026-07-01, 인구 2026-09-30, 어린이집 2026-10-07이며 서로 다르다는 점을 한계로 명시한다.
6. 경계선 위의 시설은 하나의 행정동에만 배정한다(코드 오름차순 우선).
7. 순위는 표준 경쟁 순위이고 null은 제외한다. 기본 상위 10개다.
8. `POST /api/analyses`는 분석이 끝날 때까지 응답을 기다린다(LLM 4회 호출). 비동기 Job은 범위 밖이다.
9. OpenAI 기본 모델은 `gpt-6.1-sol`(공식 모델 페이지, 2026-10 기준)이고 `OPENAI_MODEL`로 바꿀 수 있다. Ollama 모델은 `OLLAMA_MODEL`로 지정한다.

## 부록 B. LLM Provider 전략

- 포트: `StructuredLLM.generate(system, user, output_type: type[T]) -> T`. 공급자별 차이는 어댑터 안에 숨긴다.
- `OpenAIResponsesLLM`: Responses API, `text.format = {type: json_schema, strict: true}`.
- `OllamaChatLLM`: OpenAI SDK의 `base_url`을 Ollama `/v1`로 지정하고 Chat Completions `response_format=json_schema`, `temperature=0`을 쓴다. Ollama 권장사항에 따라 스키마를 프롬프트에도 포함한다.
- 공통: `llm/schema.py`가 만든 호환 스키마를 보내고, 응답은 `model_validate_json`으로 다시 검증한다. 거절·잘림(refusal, length)·JSON 오류는 `LLMError`로 명시적으로 처리한다.
- 전환: `.env`의 `LLM_PROVIDER=openai|ollama`.

## 부록 C. 이번 범위에서 하지 않는 것

전달 문서 30번 목록을 그대로 따른다(pgvector, Vector DB, Dynamic Discovery, Multi-Agent, MCP, OGC API, Sedona, Raster, Routing, Isochrone, 입지 최적화, Knowledge Graph, 임의 코드/SQL 실행, Plugin System). 그 밖에 다음도 하지 않는다: 비동기 Job 큐, 마이그레이션 도구(Alembic), 인증, Vector Tile, 지역 계층(시군구 단위 질의) 해석.

## 부록 D. 구현 중 변경·보완 사항

설계를 따르되 구현과 검증 과정에서 아래를 바꾸거나 보완했다.

| 항목 | 내용 | 이유 |
|---|---|---|
| 배경지도 | CARTO 래스터 → OpenFreeMap 벡터 스타일, Choropleth는 도로·면 위·레이블 아래에 삽입 | CARTO 타일이 API 키를 요구하게 되어 워터마크가 표시됨 |
| MapLibre worker | `maplibre-gl-worker.mjs?worker&url` + `setWorkerUrl` | MapLibre v6는 번들러 환경에서 worker 경로를 직접 지정해야 함 |
| Choropleth 색 | 단일 색상(blue) ordinal 5단계, 라이트는 진할수록·다크는 밝을수록 공급 부족, 값 없음은 회색 | 부족 지역 강조. dataviz `validate_palette.js --ordinal` 라이트·다크 모두 통과 |
| FinalResponse | `metric_labels`(output → label), `rank_metric` 추가 | 랭킹 표·툴팁 열 이름과 전체 표의 순위 열을 결정론적으로 제공 |
| Plan Validator | `BOUNDARY_FILTER_UNSUPPORTED`, `BOUNDARY_NOT_ANALYSIS_UNIT`, `DUPLICATE_FILTER`, `FIELD_UNKNOWN`, `FIELD_NOT_NUMERIC` 추가 | 경계 Dataset 필터는 기대 단위 수 검증과 충돌하고, 공간 집계 결과는 분석 단위에 키가 맞아야 함 |
| Workflow 검증 | 해석 단계에서 데이터 없는 지역은 `REGION_NOT_SUPPORTED`로 바로 종료, 계획 검증에 `PLAN_INTERPRETATION_MISMATCH`(Plan이 해석된 intent·지역·단위를 바꾸지 않았는지) 추가 | LLM이 지원 지역으로 몰래 바꾸는 것을 결정론적으로 차단하고 불필요한 LLM 호출을 줄임 |
| GIS 런타임 객체 | `DatasetView`·`BoundaryView`·`MetricValues`는 dataclass | 외부 계약이 아닌 실행 중 참조 객체. 계약(로그·결과)은 Pydantic으로 남김 |
| 실행 트랜잭션 | load_data~create_map_layer를 하나의 `REPEATABLE READ, READ ONLY` 트랜잭션에서 실행 | 단계 사이 데이터 일관성, 쓰기 차단 |
| 어린이집 운영 기준 | 운영현황 `정상`과 `재개`를 운영 중으로 포함 | 실데이터 확인 결과 `재개` 75건은 폐지일이 없고 대부분 현원이 있는 운영 시설 |
| 어린이집 행별 기준일 | 원본 `DATASTDRDT`를 열로 두지 않고 최댓값을 Dataset 기준 시점으로만 기록 | 행별 값은 시설 정보 갱신일이라 기준일 필터로 오인되어, 실제 LLM이 정상 시설 45건을 제외하는 계획을 만들었음 |
| Plan Validator | `OUTPUT_METRIC_IS_RANK` 추가 | 실제 LLM이 순위 결과를 지도 지표로 지정하는 오류를 반복해, 고칠 방향을 담은 피드백이 필요했음 |
| Provenance | `plan_attempts`(횟수) 대신 `plan_history`(시도별 Plan·검증 결과) | 재생성 전후의 판단을 모두 추적 |
| Ollama | `OLLAMA_REASONING_EFFORT`(선택) → `reasoning_effort` | thinking 모델(qwen3.5:9b) 해석 단계가 130초→6초로 단축되어 로컬 E2E가 실용적이 됨 |
| 플래너·해석 프롬프트 | 요구되지 않은 필터(기준일·유형 전체 나열) 금지, 정책 정의를 가정으로 반복하지 않기 | 실제 LLM 실행에서 관찰된 과잉 조건·중복 가정 |
| 분석 단위 조기 확인 | 해석 프롬프트에 지역별 분석 가능한 단위를 표시하고 "사용자가 말한 단위를 바꾸지 않는다" 규칙 추가, 해석 직후 경계 데이터가 없는 단위는 `UNIT_NOT_SUPPORTED`로 종료 | 시군구 질문이 LLM 4회 이상 호출 뒤 `PLAN_INVALID`로 끝나던 것을 1회 호출로 줄임. 가능한 단위만 보여주면 모델이 '구별'을 행정동으로 바꿔버릴 수 있어 단위 목록은 유지 |
| 데이터 선택 근거 기록 | `AgentState.dataset_selection`에 LLM 선택 원본(근거 포함)을 검사 전에 저장 | 선택 근거가 버려져 Agent 판단을 추적할 수 없었음. 잘못된 선택으로 실패한 경우도 기록 |

