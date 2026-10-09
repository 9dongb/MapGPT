# 공간 분석 AI Agent 개발 전달 문서

## 0. 이 문서의 목적

이 문서는 현재 개발하려는 공간 분석 AI Agent의 전체 방향과 MVP 범위, 이미 결정된 설계 원칙, 첫 번째 Vertical Slice, 그리고 이후 확장 계획을 정의한다.

현재 단계에서는 모든 공간 분석 기능을 구현하는 것이 목적이 아니다.

우선 하나의 실제 공간 분석 질문을 처음부터 끝까지 처리하는 **첫 번째 Vertical Slice**를 완성하고, 이 과정에서 앞으로 재사용할 Core Domain Model과 실행 구조를 설계하는 것이 목표다.

이 문서를 현재 구현의 source of truth로 사용한다.

---

# 1. 서비스 전체 컨셉

사용자가 자연어로 공간 분석 질문을 입력하면 AI가 다음을 수행하는 서비스를 만든다.

예:

- "서울에서 어린이집이 부족한 동은 어디야?"
- "노인복지관 접근성이 낮은 지역을 찾아줘."
- "지하철역에서 500m 이상 떨어진 지역을 보여줘."
- "인구 대비 주차장이 부족한 지역을 찾아줘."

단순한 자연어 → SQL 서비스가 아니다.

최종적으로 다음 흐름을 목표로 한다.

```text
Natural Language Question

        ↓

Problem Interpretation

        ↓

Dataset Selection / Discovery

        ↓

Spatial Analysis Planning

        ↓

Plan Validation

        ↓

Deterministic GIS Execution

        ↓

Result Validation

        ↓

Map Visualization

        ↓

Natural Language Explanation
```

핵심 가치는 다음 질문을 AI가 판단하는 데 있다.

> "이 공간 질문에 답하려면 어떤 데이터를 사용하고, 어떤 분석 방법을 적용해야 하는가?"

실제 수치 계산과 공간 연산은 LLM이 직접 수행하지 않는다.

---

# 2. 핵심 설계 원칙

## 2.1 LLM과 GIS 연산 분리

LLM 역할:

- 자연어 질문 해석
- 분석 의도 파악
- 필요한 데이터셋 선택
- 분석 방법 결정
- 구조화된 Analysis Plan 생성
- 최종 결과 설명

GIS Engine 역할:

- 데이터 필터링
- 공간 Join
- Buffer
- 거리 계산
- 영역 집계
- 통계 계산
- Geometry 처리
- 실제 결과 생성

따라서 기본 구조는 다음과 같다.

```text
LLM

 ↓

Structured Analysis Plan

 ↓

Validator

 ↓

Operation Executor

 ↓

GIS Tools

 ↓

PostGIS / deterministic code
```

LLM이 임의의 Python 코드나 SQL을 자유롭게 생성해서 실행하도록 만들지 않는다.

---

# 3. 전체적으로 목표하는 아키텍처

장기적인 전체 그림은 다음과 같다.

```text
                        User
                          │
                          ▼
                 Query Interpreter
                          │
                          ▼
                  Spatial Planner
                          │
                          ▼
                   Analysis Plan
                          │
                          ▼
                    Plan Validator
                          │
              ┌───────────┴───────────┐
              ▼                       ▼
       Dataset Catalog           GIS Operations
              │                       │
              ▼                       ▼
         Data Broker            GIS Executor
              │                       │
              └──────────┬────────────┘
                         ▼
                      PostGIS
                         │
                         ▼
                 Result Validator
                         │
                         ▼
                    Map Layer
                         │
              ┌──────────┴──────────┐
              ▼                     ▼
         Map Visualization      Explanation
              │                     │
              └──────────┬──────────┘
                         ▼
                     Final Answer
```

현재 MVP에서는 이 모든 기능을 완전하게 구현하지 않는다.

---

# 4. 현재 MVP에서 구현할 범위

MVP의 목적은 다음 첫 번째 Use Case를 완전히 동작시키는 것이다.

> **서울특별시에서 0~5세 인구 대비 어린이집 수가 적은 행정동을 분석한다.**

대표 사용자 질문:

> "서울에서 어린이 인구 대비 어린이집이 부족한 행정동을 알려줘."

현재 MVP에서는 `"부족하다"`의 의미를 다음과 같이 정의한다.

```text
행정동별 어린이집 수
÷
행정동별 0~5세 인구
×
1,000
```

즉,

```text
어린이 1,000명당 어린이집 수
```

를 계산한다.

값이 작을수록 상대적으로 어린이집 공급이 부족한 것으로 판단한다.

현재 MVP에서 이 정의는 명시적인 분석 정책으로 사용한다.

---

# 5. 첫 번째 Vertical Slice

첫 Vertical Slice 전체 흐름은 다음과 같다.

```text
사용자 질문

"서울에서 어린이 인구 대비
어린이집이 부족한 행정동을 알려줘."

        ↓

Query Interpretation

        ↓

Dataset Selection

        ↓

Analysis Plan 생성

        ↓

Plan Validation

        ↓

필요 데이터 조회

        ↓

0~5세 인구 필터링 및 집계

        ↓

어린이집 Point → 행정동 Spatial Join

        ↓

행정동별 어린이집 Count

        ↓

인구 데이터와 결합

        ↓

어린이집 수 / 어린이 인구 × 1000

        ↓

오름차순 Ranking

        ↓

Result Validation

        ↓

Choropleth용 GeoJSON 생성

        ↓

지도 + Ranking + 분석 설명 반환
```

---

# 6. 첫 번째 Vertical Slice에서 필요한 데이터

MVP에서는 3종류의 Dataset만 사용한다.

## 6.1 행정동 경계

Dataset ID:

```text
emd_boundary
```

역할:

- 분석 공간 단위
- 행정동 Polygon
- 어린이집 Point Spatial Join 대상
- 최종 Choropleth Geometry

필수 정보:

```text
행정동 코드
행정동명
Geometry
CRS
```

---

## 6.2 연령별 인구

Dataset ID:

```text
population_by_age
```

역할:

- 행정동별 0~5세 인구 계산

필수 정보:

```text
행정동 코드
연령
인구
기준 시점
```

---

## 6.3 어린이집

Dataset ID:

```text
daycare_facility
```

역할:

- 행정동별 어린이집 시설 수 계산

필수 정보:

```text
시설 식별자
시설명
위도
경도
기준 시점
```

실제 공공데이터 공급자와 API endpoint는 Adapter 계층 뒤에 숨긴다.

공급자별 응답 형식이 Domain Logic에 직접 노출되어서는 안 된다.

---

# 7. MVP에서 Dataset을 선택하는 방법

현재 MVP에서는 pgvector 또는 별도의 Vector DB를 사용하지 않는다.

Dataset 수가 적기 때문에 등록된 Dataset Catalog의 후보 정보를 LLM에게 제공하고, LLM이 필요한 Dataset ID를 선택하게 한다.

예:

```text
사용 가능한 Dataset

emd_boundary
- 행정동 경계

population_by_age
- 행정동별 연령 인구

daycare_facility
- 어린이집 위치
```

사용자의 질문에 대해 LLM이 다음과 같이 선택한다.

```json
{
  "datasets": [
    "emd_boundary",
    "population_by_age",
    "daycare_facility"
  ]
}
```

중요:

Planner 내부에서 Dataset 검색 방식을 직접 구현하지 않는다.

Dataset Catalog/Search 계층을 분리한다.

개념적인 인터페이스:

```python
class DatasetCatalog:
    def search(
        self,
        query: str,
        limit: int = 10,
    ) -> list[DatasetMetadata]:
        ...
```

현재 구현은 전체 목록 또는 단순 검색을 사용해도 된다.

향후 내부 구현을 pgvector semantic search로 교체할 수 있어야 한다.

---

# 8. Data Catalog Schema

Agent가 Dataset을 이해하기 위한 공통 Metadata Model을 정의한다.

최소 다음 정보를 표현할 수 있어야 한다.

```text
dataset_id
title
description

category
semantic_tags

provider
source

spatial information
temporal information

columns
join keys
```

개념 예시:

```json
{
  "dataset_id": "population_by_age",
  "title": "행정동별 연령 인구",
  "description": "행정동 단위의 연령별 인구 통계",

  "category": "population",

  "semantic_tags": [
    "인구",
    "연령",
    "어린이",
    "수요"
  ],

  "provider": "provider_name",

  "spatial": {
    "level": "emd",
    "geometry_type": null,
    "crs": null
  },

  "temporal": {
    "reference_date": "2025-12-31",
    "update_cycle": "yearly"
  },

  "columns": [
    {
      "name": "adm_cd",
      "description": "행정동 코드",
      "data_type": "string",
      "semantic_type": "administrative_code",
      "nullable": false
    },
    {
      "name": "age",
      "description": "만 나이",
      "data_type": "integer",
      "semantic_type": "age",
      "unit": "year",
      "nullable": false
    },
    {
      "name": "population",
      "description": "해당 연령의 인구",
      "data_type": "integer",
      "semantic_type": "population",
      "unit": "person",
      "nullable": false
    }
  ],

  "join_keys": [
    {
      "field": "adm_cd",
      "semantic_type": "administrative_code"
    }
  ]
}
```

이를 실제 Pydantic Model로 정의한다.

---

# 9. Column Metadata

Column 이름만 LLM에게 제공하지 않는다.

각 컬럼의 의미를 명시한다.

예:

```json
{
  "name": "population",
  "description": "해당 연령의 주민 인구",
  "data_type": "integer",
  "semantic_type": "population",
  "unit": "person",
  "nullable": false
}
```

향후 Dataset RAG를 적용할 때 이 설명도 embedding source로 사용할 수 있어야 한다.

---

# 10. Analysis Plan

LLM은 Python이나 SQL 코드를 생성하는 대신 반드시 구조화된 `AnalysisPlan`을 생성한다.

기본 구조는 다음 개념을 포함한다.

```text
intent

region

analysis_unit

datasets

filters

operations

output
```

대표 예:

```json
{
  "intent": "supply_demand_gap",

  "region": {
    "name": "서울특별시",
    "level": "sido"
  },

  "analysis_unit": "emd",

  "datasets": [
    "emd_boundary",
    "population_by_age",
    "daycare_facility"
  ],

  "filters": {
    "population_by_age": {
      "logic": "and",
      "conditions": [
        {
          "field": "age",
          "operator": "between",
          "value": [0, 5]
        }
      ]
    }
  },

  "operations": [
    {
      "type": "aggregate_by_area",
      "input": "daycare_facility",
      "boundary": "emd_boundary",
      "aggregation": "count",
      "output": "daycare_count"
    },
    {
      "type": "aggregate",
      "input": "population_by_age",
      "group_by": [
        "adm_cd"
      ],
      "aggregation": {
        "field": "population",
        "function": "sum"
      },
      "output": "child_population"
    },
    {
      "type": "calculate_ratio",
      "numerator": "daycare_count",
      "denominator": "child_population",
      "scale": 1000,
      "output": "daycare_per_1000_children"
    },
    {
      "type": "rank",
      "input": "daycare_per_1000_children",
      "order": "asc",
      "output": "shortage_rank"
    }
  ],

  "output": {
    "map_type": "choropleth",
    "metric": "daycare_per_1000_children",

    "ranking": {
      "enabled": true,
      "limit": 10
    }
  }
}
```

AnalysisPlan 전체를 Pydantic으로 검증한다.

---

# 11. Analysis Intent

MVP 첫 Use Case에서 사용하는 Intent:

```text
supply_demand_gap
```

장기적으로 다음과 같은 Intent를 추가할 예정이지만 지금 구현하지 않는다.

```text
facility_density
proximity
coverage
spatial_relationship
area_aggregation
ranking
accessibility
```

Enum 등으로 확장 가능한 구조를 사용한다.

---

# 12. Spatial Level

현재 지원할 기본 공간 단위 표현은 다음을 사용한다.

```text
sido
sigungu
emd
```

첫 MVP는:

```text
emd
```

분석만 실제로 사용한다.

---

# 13. Filter 설계

Filter는 특정 도메인에 종속된 형태로 만들지 않는다.

예를 들어 다음처럼 만들지 않는다.

```text
age_min
age_max
```

대신 범용적인 Filter Expression DSL을 만든다.

---

## 13.1 기본 Condition

```json
{
  "field": "age",
  "operator": "between",
  "value": [0, 5]
}
```

다른 예:

```json
{
  "field": "facility_type",
  "operator": "eq",
  "value": "어린이집"
}
```

---

## 13.2 복합 조건

```json
{
  "logic": "and",
  "conditions": [
    {
      "field": "age",
      "operator": "between",
      "value": [0, 5]
    },
    {
      "field": "region_code",
      "operator": "starts_with",
      "value": "11"
    }
  ]
}
```

---

## 13.3 구조

개념적으로 다음 구조를 갖는다.

```text
FilterExpression

├── FilterCondition
│
│   ├── field
│   ├── operator
│   └── value
│
└── FilterGroup

    ├── logic
    └── conditions[]
```

재귀적으로 Group 안에 Group을 포함할 수 있도록 설계해도 된다.

---

## 13.4 지원 Operator

초기 지원 범위:

```text
eq
neq

gt
gte
lt
lte

between

in
not_in

contains
starts_with

is_null
is_not_null
```

논리 연산:

```text
and
or
not
```

LLM은 이 구조만 생성한다.

LLM이 직접 SQL WHERE 절을 생성하지 않는다.

Backend가 검증된 FilterExpression을 parameterized SQL 또는 내부 DataFrame/GIS operation으로 변환한다.

---

# 14. Operation 설계

Operation은 자유 형식 JSON이나 문자열 리스트로 만들지 않는다.

다음과 같은 형태는 사용하지 않는다.

```json
{
  "type": "operation",
  "params": {}
}
```

또는:

```json
[
  "aggregate",
  "ratio",
  "rank"
]
```

대신 **Operation Type별 별도의 Typed Schema를 정의하고 Discriminated Union으로 묶는다.**

예:

```python
Operation = (
    SpatialJoinOperation
    | AggregateByAreaOperation
    | AggregateOperation
    | CalculateRatioOperation
    | RankOperation
)
```

각 Operation은 반드시 자신의 type을 Literal discriminator로 가진다.

예:

```python
type: Literal["calculate_ratio"]
```

---

# 15. 첫 MVP Operation

첫 Vertical Slice에서 필요한 Operation만 먼저 구현한다.

## AggregateByAreaOperation

예:

```json
{
  "type": "aggregate_by_area",
  "input": "daycare_facility",
  "boundary": "emd_boundary",
  "aggregation": "count",
  "output": "daycare_count"
}
```

역할:

Point 데이터를 Polygon 단위로 집계한다.

---

## AggregateOperation

예:

```json
{
  "type": "aggregate",
  "input": "population_by_age",
  "group_by": [
    "adm_cd"
  ],
  "aggregation": {
    "field": "population",
    "function": "sum"
  },
  "output": "child_population"
}
```

---

## CalculateRatioOperation

```json
{
  "type": "calculate_ratio",
  "numerator": "daycare_count",
  "denominator": "child_population",
  "scale": 1000,
  "output": "daycare_per_1000_children"
}
```

---

## RankOperation

```json
{
  "type": "rank",
  "input": "daycare_per_1000_children",
  "order": "asc",
  "output": "shortage_rank"
}
```

향후 새로운 Operation을 추가할 때 기존 Operation Schema를 변경하지 않고 새로운 Union Member를 추가하는 형태를 우선한다.

---

# 16. Analysis Operation과 GIS Tool은 분리한다

중요한 설계 원칙이다.

Analysis Plan의 Operation:

> 무엇을 분석해야 하는지 표현

GIS Tool:

> 그 분석을 실제로 수행

예:

```text
Analysis Plan

AggregateByAreaOperation

        ↓

Operation Executor

        ↓

GIS Tool / Repository

        ↓

PostGIS

        ↓

ST_Intersects / ST_Contains
GROUP BY
COUNT
```

LLM이 PostGIS 함수 이름까지 직접 결정할 필요는 없다.

---

# 17. 첫 MVP GIS Tool

현재는 첫 Vertical Slice에 필요한 Tool만 구현한다.

데이터:

```text
get_dataset
get_boundary
```

필터:

```text
filter_dataset
```

공간 / 집계:

```text
aggregate_by_area
aggregate
```

계산:

```text
calculate_ratio
rank
```

결과:

```text
create_choropleth_layer
```

내부 지원:

```text
transform_crs
validate_geometry
```

지금 단계에서 다음 Tool은 구현하지 않는다.

```text
buffer
nearest_distance
network_distance
isochrone
coverage
raster
```

두 번째 이후 Vertical Slice에서 추가한다.

---

# 18. GIS Tool 명세 규칙

각 Tool에는 최소 다음을 정의한다.

1. Tool 이름
2. 목적
3. Input Schema
4. Output Schema
5. Validation
6. 실패 조건

예:

```text
aggregate_by_area
```

목적:

```text
Point 또는 Geometry Dataset을
Boundary Polygon 기준으로 집계한다.
```

입력:

```json
{
  "input_dataset": "...",
  "boundary_dataset": "...",
  "aggregation": "count"
}
```

출력:

```json
{
  "result_ref": "..."
}
```

실패 조건 예:

```text
Geometry 없음
CRS 불일치
Boundary가 Polygon이 아님
지원하지 않는 aggregation
```

---

# 19. CRS 정책

CRS 선택을 LLM에게 맡기지 않는다.

CRS Policy를 Backend에 구현한다.

원칙:

```text
지도 반환:
EPSG:4326
```

대한민국에서 거리/면적 계산이 필요한 경우:

```text
적절한 projected CRS 사용
```

기본 후보:

```text
EPSG:5179
```

단, 분석 목적에 따라 더 적절한 CRS가 있다면 Policy 계층에서 결정한다.

첫 Vertical Slice는 주로 Point-in-Polygon과 집계이므로 거리 계산은 아직 없다.

그래도 Dataset Metadata에 CRS를 반드시 명시하고 필요하면 연산 전에 정규화한다.

---

# 20. Plan Validator

LLM이 생성한 AnalysisPlan을 바로 실행하지 않는다.

실행 전 검증한다.

최소 검증 항목:

```text
Dataset ID가 실제 존재하는가

필요 Dataset이 모두 있는가

Filter에서 참조한 field가 실제 존재하는가

Operation에서 참조한 input이 존재하는가

Operation output 이름 충돌이 없는가

공간 분석에 필요한 Geometry가 있는가

Geometry type이 적절한가

CRS를 처리할 수 있는가

Join 가능한 키 또는 공간 관계가 존재하는가

Ratio denominator가 유효한가

지원하지 않는 Operation이 포함되어 있지 않은가

Output metric이 실제 계산되는 값인가
```

가능한 검증은 LLM이 아니라 deterministic code로 구현한다.

---

# 21. Result Validator

분석이 끝난 뒤에도 결과를 검증한다.

최소 검증:

```text
결과가 비어있지 않은가

행정동 Geometry가 유효한가

행정동 중복이 없는가

인구가 음수가 아닌가

denominator가 0인 경우가 처리되었는가

NULL 비율이 비정상적으로 높지 않은가

결과가 서울 범위 안에 있는가

계산 결과가 NaN / Infinity가 아닌가

예상 행정동 수와 지나치게 큰 차이가 없는가
```

0 인구 지역에 대한 ratio 정책은 명시적으로 처리한다.

무조건 0으로 바꾸지 말고 `null / unavailable` 등 의미적으로 적절한 값을 사용한다.

---

# 22. 결과 출력

첫 MVP의 최종 결과는 최소 다음을 제공한다.

```text
지도

어린이집 공급 부족 Ranking

분석 Metric

사용 데이터

데이터 기준 시점

분석 방법

가정

한계
```

API 응답 개념 예:

```json
{
  "summary": "...",

  "metric": {
    "name": "daycare_per_1000_children",
    "description": "0~5세 어린이 1,000명당 어린이집 수"
  },

  "ranking": [],

  "map_layer": {},

  "analysis_method": "...",

  "datasets": [],

  "assumptions": [],

  "limitations": []
}
```

---

# 23. 지도 출력

초기 MVP에서는 결과 Geometry를 GeoJSON으로 반환한다.

Frontend:

```text
React
+
MapLibre GL JS
```

기본 지도 표현:

```text
Choropleth
```

색상은:

```text
daycare_per_1000_children
```

값에 따라 표현한다.

대용량 지도 처리와 Vector Tile/MVT는 현재 범위가 아니다.

---

# 24. Provenance

모든 분석 실행에 대해 최소한 다음 정보는 기록한다.

```text
run_id

원본 사용자 질문

사용 Dataset ID

Dataset 기준 시점

Analysis Plan

실행 Operation

CRS

실행 시각

결과 ID
```

개념 예:

```json
{
  "run_id": "...",
  "question": "...",

  "datasets": [
    {
      "dataset_id": "population_by_age",
      "reference_date": "..."
    }
  ],

  "analysis_plan": {},

  "operations": [],

  "crs": "...",

  "result_id": "..."
}
```

목적:

- 결과 재현성
- 디버깅
- 데이터 변경 추적
- Agent 판단 추적

---

# 25. Agent Workflow

MVP는 Multi-Agent로 만들지 않는다.

하나의 Orchestrator Workflow를 사용한다.

권장 State:

```text
question

interpreted_query

dataset_candidates

selected_datasets

analysis_plan

plan_validation

execution_results

result_validation

map_layer

final_response

errors
```

Workflow:

```text
interpret_query

        ↓

select_datasets

        ↓

build_analysis_plan

        ↓

validate_plan

        ↓

fetch/load_data

        ↓

execute_operations

        ↓

validate_result

        ↓

create_map_layer

        ↓

generate_explanation
```

상태 머신 형태로 구현한다.

LangGraph를 사용할 수 있지만 필수는 아니다.

Core Domain과 GIS Logic이 특정 Agent Framework에 강하게 종속되지 않도록 한다.

---

# 26. Backend 기술 방향

권장:

```text
Python

FastAPI

Pydantic

PostgreSQL

PostGIS
```

GIS 관련 필요시:

```text
GeoPandas
Shapely
PyProj
```

단, 핵심 공간 데이터 저장과 서버측 주요 공간 연산은 PostGIS를 중심으로 한다.

---

# 27. Repository / Data Source 분리

외부 공공데이터 형식을 Domain Model에 직접 노출하지 않는다.

예:

```text
SGISAdapter
DataGoKrAdapter
기타 Provider Adapter
```

공통적으로 내부 Dataset 형태로 변환한다.

개념적인 구조:

```text
External API

    ↓

Provider Adapter

    ↓

Normalized Internal Dataset

    ↓

GIS / Domain Logic
```

---

# 28. 권장 프로젝트 구조

초기 예:

```text
app/

  api/

  agents/

  workflows/

  domain/
    models/
    enums/

  catalog/

  data_sources/
    adapters/

  gis/
    operations/
    tools/
    crs/
    validation/

  executors/

  repositories/

  services/

  prompts/

  config/

  tests/
```

정확한 폴더 이름은 더 적절한 구조가 있다면 변경 가능하다.

다만 다음 관심사 분리는 유지한다.

```text
LLM / Agent

Domain Model

Dataset Catalog

External Data Adapter

GIS Execution

Database Access

Validation

API
```

---

# 29. 현재 구현해야 하는 것

현재 해야 할 작업은 다음이다.

## Phase 1 - Core Schema

다음을 먼저 설계/구현한다.

```text
DatasetMetadata

ColumnMetadata

JoinKey

SpatialMetadata

TemporalMetadata

FilterExpression

AnalysisPlan

Operation Schemas

OutputSpec

Agent State

Execution Result
```

모두 가능한 범위에서 Pydantic을 사용한다.

---

## Phase 2 - 첫 Dataset

다음 Dataset 3개를 준비한다.

```text
emd_boundary

population_by_age

daycare_facility
```

실제 데이터를 로드하고 내부 표준 형태로 정규화한다.

---

## Phase 3 - 첫 GIS Execution

구현:

```text
Filter

행정동별 Population Aggregate

어린이집 Point → 행정동 Spatial Aggregation

Ratio

Ranking

GeoJSON
```

---

## Phase 4 - LLM Integration

LLM에게 다음 역할만 부여한다.

```text
Query Interpretation

Dataset Selection

Analysis Plan 생성

Result Explanation
```

Structured Output을 사용한다.

Pydantic Schema 검증에 실패하면 실행하지 않는다.

---

## Phase 5 - Validation

구현:

```text
Plan Validator

Result Validator

Geometry Validation

CRS Validation
```

---

## Phase 6 - API / UI 연결

FastAPI endpoint와 React + MapLibre UI를 연결한다.

---

# 30. 현재 구현하지 않을 것

현재 MVP에서는 다음을 구현하지 않는다.

```text
pgvector 기반 RAG

전용 Vector DB

자동 공공데이터 검색

Dynamic Dataset Discovery

Multi-Agent

MCP Server

OGC API Server

Apache Sedona

Raster 분석

위성영상 분석

Network Routing

보행 시간 분석

Isochrone

입지 최적화

Knowledge Graph

arbitrary Python execution

arbitrary SQL generation

Dynamic Plugin System

Kubernetes 기반 대규모 운영 구조
```

미래 확장성을 이유로 위 기능들을 미리 구현하지 않는다.

---

# 31. 이후 1차 확장: 두 번째 Vertical Slice

첫 번째 Vertical Slice가 완성된 후에는 첫 번째와 다른 공간 연산을 사용하는 Use Case를 추가한다.

추천:

> "지하철역에서 500m 이상 떨어진 지역을 찾아줘."

이 Use Case를 통해 다음 Operation을 추가한다.

```text
buffer

difference 또는 uncovered_area

spatial_relationship

coverage
```

목적은 첫 번째 Vertical Slice에서 만든 Generic Core가 실제로 재사용 가능한지 검증하는 것이다.

첫 번째 사례에 과도하게 하드코딩되어 있다면 이 시점에서 Core Schema를 보완한다.

---

# 32. 이후 2차 확장: 접근성 분석

다음 단계:

```text
nearest_distance

network_distance

travel_time

isochrone

service_area
```

예:

> "노인복지관까지 도보 15분 이상 걸리는 고령인구 밀집 지역"

이 단계에서는 도로망 및 Routing Engine 도입을 검토한다.

---

# 33. 이후 3차 확장: Dataset RAG

Dataset 수가 많아지면 모든 Dataset Metadata를 LLM Context에 넣지 않는다.

이때:

```text
PostgreSQL + pgvector
```

를 사용한다.

구조:

```text
User Query

      ↓

Embedding

      ↓

pgvector

      ↓

Relevant Dataset Top-K

      ↓

LLM Dataset Selector

      ↓

Plan Validator
```

pgvector는 LLM의 Dataset 판단을 대체하는 것이 아니다.

역할:

```text
pgvector:
관련 Dataset 후보 검색

LLM:
최종 Dataset 선택

Validator:
실제로 사용 가능한지 검증
```

---

# 34. 향후 pgvector에 저장할 것

주요 Embedding 대상:

```text
Dataset title

Dataset description

semantic tags

Column description

Column semantic type
```

향후 추가 가능:

```text
Analysis Knowledge

성공한 Analysis Plan Example

Metric description
```

반대로 다음 공간 데이터를 단순 RAG 목적으로 임베딩하지 않는다.

```text
행정동 Polygon 하나하나

어린이집 Point 하나하나

시설 위치 Raw Spatial Data
```

이 데이터는 PostGIS에서 처리한다.

---

# 35. 이후 4차 확장: Semantic Analysis Knowledge

자연어 표현을 공간 분석 개념으로 연결하는 Knowledge Layer를 만든다.

예:

```text
"부족하다"

→ facility_shortage
```

가능 Metric:

```text
facility_per_population

capacity_per_population

nearest_distance

coverage_ratio
```

예:

```text
"접근성이 낮다"

→ accessibility
```

가능 Metric:

```text
euclidean_distance

network_distance

travel_time

coverage_ratio
```

처음에는 JSON/YAML 또는 DB Table로 충분하다.

복잡한 Knowledge Graph는 필요성이 확인된 후 검토한다.

---

# 36. 이후 5차 확장: Dynamic Dataset Discovery

Trusted Dataset만으로 질문을 해결하기 어려운 시점에 추가한다.

흐름:

```text
Dataset Search

       ↓

Metadata 확인

       ↓

Schema 확인

       ↓

Sample Fetch

       ↓

Spatial Unit 확인

       ↓

Join Key 확인

       ↓

Temporal Compatibility 확인

       ↓

Quality Validation

       ↓

사용 가능 판정
```

Agent가 처음 발견한 데이터를 검증 없이 바로 분석에 사용하지 않는다.

---

# 37. 장기 확장

필요성이 확인된 이후에 다음을 고려한다.

```text
MCP

OGC API Processes

Multi-Agent

Raster

Satellite

대규모 Spatial Processing

Vector Tile

분산 처리

입지 최적화

다중 기준 의사결정
```

현재 구조는 이런 기능을 나중에 붙일 수 있을 정도로만 확장 가능하게 만들고, 미리 구현하지 않는다.

---

# 38. 중요한 개발 원칙

## 반드시 지킬 것

```text
LLM reasoning과 실제 GIS execution 분리

Structured Output 사용

Pydantic 기반 validation

Typed Operation 사용

범용 Filter Expression 사용

Parameterized SQL 사용

공간 데이터 CRS 명시

외부 API Adapter 분리

분석 Provenance 저장

GIS Operation 단위 테스트

실패를 명시적으로 처리
```

---

# 39. 피해야 할 구현

다음과 같은 지나친 하드코딩은 피한다.

```python
analyze_seoul_daycare()
```

단, 반대 방향으로 지나치게 범용화하는 것도 피한다.

현재 필요한 정도는:

```text
Generic Core

        ↓

First Vertical Slice
```

이다.

처음부터 모든 공간연산을 표현하는 거대한 GIS DSL이나 Plugin Framework를 만들 필요는 없다.

---

# 40. 첫 번째 Vertical Slice의 성공 기준

다음 요청이 실제로 처음부터 끝까지 동작해야 한다.

```text
"서울에서 어린이 인구 대비
어린이집이 부족한 행정동을 알려줘."
```

성공 기준:

1. LLM이 질문을 올바르게 해석한다.

2. 다음 Dataset을 선택한다.

```text
emd_boundary
population_by_age
daycare_facility
```

3. 유효한 AnalysisPlan을 생성한다.

4. AnalysisPlan이 Pydantic Validation을 통과한다.

5. Plan Validator를 통과한다.

6. 0~5세 인구가 올바르게 계산된다.

7. 어린이집이 행정동에 올바르게 공간 집계된다.

8. 다음 Metric이 계산된다.

```text
어린이집 수 / 0~5세 인구 × 1000
```

9. 부족 순위가 계산된다.

10. 행정동별 Choropleth GeoJSON이 생성된다.

11. 사용자에게 다음이 반환된다.

```text
지도
Ranking
Metric
사용 Dataset
데이터 기준 시점
계산 방법
가정
한계
```

12. 전체 분석 실행 내역이 Provenance로 기록된다.

---

# 41. 첫 작업 지시

처음부터 코드를 대량 작성하지 말 것.

우선 현재 Repository를 확인한 뒤, 이 문서를 기준으로 다음을 제안한다.

1. 전체 MVP Architecture
2. Project Directory
3. Core Domain Model
4. DatasetMetadata Pydantic Schema
5. FilterExpression Pydantic Schema
6. AnalysisPlan Pydantic Schema
7. Operation Discriminated Union
8. Agent State
9. GIS Tool Interfaces
10. Plan Validator 구조
11. Operation Executor 구조
12. 첫 Vertical Slice Sequence
13. 필요한 DB Table
14. REST API
15. Test Strategy
16. 구현 순서

설계에서 불필요하게 복잡한 추상화를 추가하지 않는다.

명확하지 않은 부분은 합리적인 최소 가정을 명시하고 진행한다.

첫 번째 Vertical Slice 구현에 직접 필요하지 않은 기능은 추가하지 않는다.

---

# 42. 현재 핵심 요약

현재 만드는 것은:

```text
자연어 공간 질문

→ LLM 해석

→ 미리 등록된 Dataset 중 선택

→ Typed Analysis Plan 생성

→ Deterministic Validation

→ Typed GIS Operation 실행

→ PostGIS 공간 분석

→ Result Validation

→ GeoJSON

→ 지도 + 설명
```

이다.

현재 핵심 기술:

```text
Python
FastAPI
Pydantic
PostgreSQL
PostGIS
React
MapLibre
LLM Structured Output
```

현재 사용하지 않는 것:

```text
pgvector
Multi-Agent
MCP
Dynamic Dataset Discovery
```

향후 Dataset이 많아지면:

```text
PostgreSQL
├── 일반 Metadata
├── PostGIS
└── pgvector
```

구조로 확장한다.

가장 중요한 것은 현재 하나의 Vertical Slice를 완전하게 구현하면서도 다음 Vertical Slice에서 재사용할 수 있는

```text
DatasetMetadata
FilterExpression
AnalysisPlan
Operation
GIS Executor
Validator
```

를 Core Contract로 만드는 것이다.