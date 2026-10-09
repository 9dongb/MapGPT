# MapGPT 공간 분석 AI Agent 설계 개요

> 팀 공유용 문서 · 기준: 2026-10-09, `main` 커밋 `0958c83`
>
> 구현된 코드를 기준으로 정리했습니다. 더 자세한 설계와 변경 이력은 [MVP 설계안](design/mvp-design.md), 데이터 수집·적재의 현황과 향후 방향은 [데이터 담당자 전달 문서](data-handoff.md), 백엔드 운영 과제는 [백엔드 담당자 전달 문서](backend-handoff.md), 화면의 향후 과제는 [프론트엔드 담당자 전달 문서](frontend-handoff.md), 요구사항 원문은 [개발 전달 문서](../공간%20분석%20AI%20Agent%20개발%20전달%20문서.md), 실행 명령 요약은 [README](../README.md)에 있습니다.

**목차**

1. 한눈에 보기
2. 전체 아키텍처
3. 에이전트 구조와 동작 흐름 (핵심)
4. 데이터베이스
5. 데이터 적재 파이프라인
6. 백엔드
7. 프론트엔드
8. 테스트와 개발 규칙
9. 로컬 실행 방법
10. 운영·디버깅 가이드
11. 성능·비용·보안·라이선스
12. 주요 설계 결정과 이유
13. 현재 한계와 로드맵
14. 자주 하는 변경: 어디를 고치나
15. 용어집

---

## 1. 한눈에 보기

### 1.1 무엇을 하는 시스템인가

자연어 공간 분석 질문을 받으면 LLM이 **구조화된 분석 계획(Analysis Plan)** 을 만들고, 결정론적 검증을 통과한 계획만 **PostGIS**에서 실행해 지도·순위·설명으로 돌려주는 AI Agent입니다.

| 구분 | 내용 |
|---|---|
| 질문 | "서울에서 어린이 인구 대비 어린이집이 부족한 행정동을 알려줘." |
| 계산 | 행정동별 `어린이집 수 ÷ 0~5세 인구 × 1,000`. 값이 작을수록 부족하므로 오름차순으로 순위를 매김 |
| 응답 | Choropleth 지도, 부족 순위, 지표 설명, 사용 데이터와 기준 시점, 계산 방법, 가정, 한계, 요약 문장 |

실제 데이터(서울 행정동 427개)로 실행한 결과의 상위 5개입니다.

| 순위 | 행정동 | 0~5세 1,000명당 어린이집 수 | 어린이집 수 | 0~5세 인구 |
|---|---|---|---|---|
| 1 | 송파구 잠실7동 | 0.00 | 0 | 248 |
| 2 | 송파구 오륜동 | 2.29 | 1 | 436 |
| 3 | 강동구 둔촌1동 | 3.42 | 7 | 2,048 |
| 4 | 강남구 개포2동 | 3.77 | 8 | 2,122 |
| 5 | 강남구 개포1동 | 4.00 | 4 | 1,001 |

### 1.2 핵심 원칙

1. **LLM은 판단만 하고 계산은 코드가 한다.** LLM은 질문 해석, 데이터 선택, 계획, 설명만 맡고 SQL이나 코드를 만들지 않습니다.
2. **LLM 출력은 검증을 통과해야 실행된다.** Structured Output(JSON Schema), Pydantic, Plan Validator 순서로 검사합니다.
3. **모든 공간 계산은 타입이 정해진 Operation으로 표현한다.** GIS Tool이 Operation을 parameterized SQL로 바꿔 PostGIS에서 실행합니다.
4. **실패와 결측을 숨기지 않는다.** 실패는 단계·코드·이유와 함께 돌려주고, 계산할 수 없는 값은 0이 아니라 null과 사유로 남깁니다.
5. **모든 실행을 기록한다(Provenance).** 성공·실패와 관계없이 LLM이 본 입력과 판단, 실행한 연산을 저장합니다.
6. **외부 데이터 형식은 Adapter 뒤에 숨긴다.** 분석 코드는 내부 표준 Dataset만 봅니다.

### 1.3 현재 범위 (MVP 첫 번째 Vertical Slice)

| 항목 | 현재 지원 |
|---|---|
| 분석 유형(intent) | `supply_demand_gap` 하나 (수요 인구 대비 시설 공급 부족) |
| 지역 | 서울특별시 |
| 분석 단위 | 행정동(`emd`) |
| 데이터 | 행정동 경계, 행정동별 연령별 인구, 어린이집 위치 (Trusted Dataset 3종) |
| 연산(Operation) | `aggregate_by_area`, `aggregate`, `calculate_ratio`, `rank` |
| 지도 | Choropleth 5분위 |
| LLM | OpenAI(Responses API) 또는 로컬 Ollama. `.env`로 전환 |
| Dataset 검색 | OpenAI 임베딩 + pgvector 코사인 유사도 |

---

## 2. 전체 아키텍처

```mermaid
flowchart TB
    subgraph Backend["백엔드 (FastAPI)"]
        API["REST API<br/>app/api"]
        WF["AnalysisWorkflow<br/>LangGraph StateGraph"]
        STEPS["LLM 단계<br/>해석 · 선택 · 계획 · 설명"]
        CAT["DatasetCatalog<br/>후보 검색"]
        VAL["Plan / Result<br/>Validator"]
        EXE["Operation Executor<br/>+ GIS Tools"]
        RESP["최종 응답 조립"]
        REPO["Run Repository<br/>Provenance"]
        API --> WF
        WF --> STEPS
        WF --> CAT
        WF --> VAL
        WF --> EXE
        WF --> RESP
        WF --> REPO
    end

    UI["브라우저<br/>React + MapLibre"] -->|"POST /api/analyses"| API
    STEPS --> LLM["LLM<br/>OpenAI 또는 Ollama"]
    CAT --> EMB["OpenAI 임베딩"]

    subgraph DB["PostgreSQL"]
        CATDB[("catalog<br/>메타데이터 · 임베딩")]
        DATA[("datasets<br/>내부 표준 데이터")]
        RUN[("analysis<br/>실행 기록 · 결과")]
    end

    CAT --> CATDB
    EXE --> DATA
    REPO --> RUN
```

CLI의 `analyze` 명령도 같은 Workflow를 호출합니다. 데이터를 채우는 적재 경로(CLI → Adapter → DB)는 5장에 있습니다.

| 계층 | 위치 | 책임 |
|---|---|---|
| domain | `app/domain` | 핵심 계약(Pydantic 모델, Enum, 분석 정책). I/O가 없고 다른 계층에 의존하지 않음 |
| llm | `app/llm` | LLM·임베딩 공급자 어댑터, LLM 호환 JSON Schema 변환 |
| agents | `app/agents` | LLM 4단계(해석·선택·계획·설명)의 프롬프트와 호출 |
| catalog | `app/catalog` | Trusted Dataset 메타데이터 정의, 임베딩 동기화, 후보 검색 |
| validation | `app/validation` | Plan / Result 결정론적 검증 |
| gis | `app/gis` | GIS Tool, CRS 정책, FilterExpression → SQL 컴파일 |
| executor | `app/executor` | Operation을 GIS Tool에 매핑해 순서대로 실행 |
| workflows | `app/workflows` | LangGraph 분석 그래프와 실행기, 최종 응답 조립. LangGraph 의존은 여기에만 둠 |
| repositories | `app/repositories` | `catalog`·`analysis` 스키마 읽기/쓰기 |
| data_sources | `app/data_sources` | 외부 원본을 내부 표준 Dataset으로 적재 |
| api / cli | `app/api`, `app/cli.py` | HTTP 경계, 운영 명령. 둘 다 같은 workflow를 호출 |

### 2.1 요청 하나의 생애

```mermaid
sequenceDiagram
    autonumber
    participant U as 브라우저
    participant API as FastAPI
    participant W as AnalysisWorkflow
    participant L as LLM
    participant E as OpenAI 임베딩
    participant DB as PostgreSQL
    U->>API: POST /api/analyses
    API->>W: run(question)
    W->>DB: 카탈로그 조회 (지역·분석 가능 단위)
    W->>L: 질문 해석 → InterpretedQuery
    W->>E: 검색어 임베딩
    W->>DB: pgvector 상위 10개 후보
    W->>L: Dataset 선택 → DatasetSelection
    W->>L: 분석 계획 → AnalysisPlan
    W->>W: Plan Validator (오류면 피드백 후 1회 재생성)
    W->>DB: 읽기 전용 트랜잭션에서 GIS Tool 실행
    W->>W: Result Validator
    W->>DB: Choropleth GeoJSON 생성
    W->>L: 결과 설명 → Explanation
    W->>DB: Provenance 저장 (analysis.run, analysis.result)
    W-->>API: AgentState
    API-->>U: run_id, status, result, errors
```

한 번의 분석에서 LLM은 4번(계획을 다시 만들면 5번), 임베딩 API는 1번 호출됩니다. API는 분석이 끝날 때까지 응답을 기다리는 동기 방식입니다.

---

## 3. 에이전트 구조와 동작 흐름

### 3.1 역할 분담: LLM과 결정론적 코드

| LLM이 하는 일 (Structured Output) | 코드가 하는 일 (결정론적) |
|---|---|
| ① 질문 해석: intent, 지역, 분석 단위, 핵심 개념, 가정 | 지원하는 지역·분석 단위인지 해석 직후 확인 |
| ② Dataset 선택: 후보 중 필요한 ID와 근거 | pgvector 후보 검색, 선택한 ID가 후보 안에 있는지 확인 |
| ③ 분석 계획: 필터, Operation 순서, 출력 지표 | Pydantic 스키마 검증, Plan Validator, 해석과의 일치 검사 |
| ④ 결과 설명: 3~5문장 요약 | GIS 실행(SQL), 결과 검증, 지도 생성, 방법·가정·한계·순위 조립, Provenance 저장 |

LLM이 쓴 문장 중 화면에 그대로 보이는 것은 요약(summary), 해석 가정(assumptions), Operation 라벨, 지원하지 않는 질문의 이유(unsupported_reason)뿐입니다. 수치, 순위, 계산 방법 문장, 한계는 모두 코드가 실행 기록에서 만듭니다.

### 3.2 LangGraph 워크플로

[`AnalysisWorkflow`](../app/workflows/analysis_workflow.py)는 LangGraph `StateGraph`로 구성한 그래프(`ANALYSIS_GRAPH`)를 실행합니다.

- **상태**: Provenance로 저장하는 `AgentState`를 그래프 상태로 그대로 씁니다. 노드는 바뀐 필드만 돌려줍니다.
- **노드**: `WorkflowStep` 9개가 곧 노드 이름입니다. 단계 함수는 결과를 기록하다가 실패하면 `WorkflowFailure`를 던지고, 노드 래퍼(`_node`)가 그때까지 기록한 값(해석·후보·계획 시도 등)을 남긴 채 오류를 `errors`에 더합니다.
- **엣지**: 모든 단계 뒤는 조건부 엣지입니다. `errors`가 있으면 END, 없으면 다음 단계로 갑니다.
- **의존성**: LLM, 카탈로그, 읽기 전용 DB 세션은 실행마다 Runtime context(`_RunContext`)로 주입합니다. 상태에는 Provenance로 남길 값만 둡니다.
- **프레임워크 경계**: LangGraph는 `app/workflows`에서만 씁니다. Domain·GIS·Validation 계층은 LangGraph를 모릅니다(전달 문서 25번).

```mermaid
stateDiagram-v2
    [*] --> interpret_query
    interpret_query --> select_datasets
    select_datasets --> build_analysis_plan
    build_analysis_plan --> validate_plan
    build_analysis_plan --> build_analysis_plan: 스키마 불일치 시 재생성 (최대 1회)
    validate_plan --> build_analysis_plan: 검증 오류 시 피드백 후 재생성 (최대 1회)
    validate_plan --> load_data: 오류 없음
    load_data --> execute_operations
    execute_operations --> validate_result
    validate_result --> create_map_layer
    create_map_layer --> generate_explanation
    generate_explanation --> [*]
```

그림에서는 생략했지만 모든 단계에서 END로 가는 실패 엣지가 있습니다. 예상하지 못한 예외는 `INTERNAL_ERROR`로 기록합니다. 그래프가 끝나면 실행기가 `errors` 유무로 `succeeded`/`failed`를 정하고, 성공·실패와 관계없이 Provenance를 저장합니다. 계획 단계의 분기는 라우터 두 개가 정합니다.

- `build_analysis_plan` 뒤: 계획이 나오면 `validate_plan`, 스키마 불일치로 계획이 없으면 다시 `build_analysis_plan`
- `validate_plan` 뒤: 오류가 없으면 `load_data`, 있으면 다시 `build_analysis_plan`. 두 번째 시도도 실패하면 노드가 `PLAN_INVALID`를 기록하고 END로 갑니다

그래프 구조는 코드에서 `ANALYSIS_GRAPH.get_graph().draw_mermaid()`로 바로 그릴 수 있습니다.

| # | 단계 (`WorkflowStep`) | 주체 | 입력 → 출력 | 대표 실패 코드 |
|---|---|---|---|---|
| 1 | `interpret_query` | LLM + 검사 | 질문, 분석 정책, 지역별 분석 가능 단위 → `InterpretedQuery` | `UNSUPPORTED_QUESTION`, `INCOMPLETE_INTERPRETATION`, `REGION_NOT_SUPPORTED`, `UNIT_NOT_SUPPORTED` |
| 2 | `select_datasets` | pgvector + LLM | 검색어 → 후보(최대 10개) → `DatasetSelection` | `CATALOG_INDEX_STALE`, `EMBEDDING_FAILED`, `INVALID_DATASET_SELECTION` |
| 3 | `build_analysis_plan` | LLM | 해석 + 선택 Dataset 상세 메타데이터 (+ 이전 오류) → `AnalysisPlan` | `LLM_FAILED` (스키마 불일치는 재생성) |
| 4 | `validate_plan` | 코드 | Plan + 메타데이터 → `ValidationReport` | `PLAN_INVALID` |
| 5 | `load_data` | GIS | Plan → 경계 View, 필터를 적용한 Dataset View | `DATASET_TABLE_MISSING`, `DATASET_EMPTY`, `FILTER_EMPTY_RESULT`, `REGION_NOT_FOUND`, `INVALID_GEOMETRY` 등 |
| 6 | `execute_operations` | GIS | Operation 순차 실행 → `ExecutionResult` | `NON_FINITE_RESULT` 등 GIS Tool 코드 |
| 7 | `validate_result` | 코드 | 실행 결과 → `ValidationReport` | `RESULT_INVALID` |
| 8 | `create_map_layer` | GIS | 결과 행 → GeoJSON + 분위 구간 | `OUTPUT_CRS_INVALID`, `GEOMETRY_MISSING` |
| 9 | `generate_explanation` | 코드 + LLM | 응답 조립 → 설명용 사실 → 요약 | `LLM_FAILED` |

LLM 호출 실패(API 오류, 거절, 길이 초과로 잘림, 스키마 불일치)는 `LLM_FAILED`로 끝납니다. 예외는 계획 단계의 스키마 불일치 하나로, 이때는 계획을 다시 만듭니다. 워크플로 차원의 재시도는 이 계획 재생성 1회뿐입니다.

### 3.3 단계별 상세

#### ① interpret_query: 질문 해석

- 코드가 먼저 카탈로그에서 지역(`coverage`)과 지역별 분석 가능 단위를 계산합니다. 분석 가능 단위는 "그 지역을 범위로 가진 Polygon 경계 Dataset의 단위"입니다. 프롬프트에는 `- 서울특별시 (sido): emd(행정동)`처럼 들어갑니다.
- 프롬프트에는 분석 정책(intent 정의, 해석, 개념 정의), 공간 단위 목록, 지역 목록, 규칙 5개가 들어갑니다.
  1. 지원하는 분석 유형으로 표현되지 않으면 intent·region·analysis_unit을 null로 두고 이유를 씁니다.
  2. `region.name`은 공식 명칭('서울' → '서울특별시'), `region.level`은 지역 자체의 단위(서울특별시 → sido)입니다. 결과를 나눌 단위는 `analysis_unit`에 쓰고, 사용자가 말한 지역을 바꾸지 않습니다.
  3. `analysis_unit`은 결과를 보여줄 단위('동별' → emd, '구별' → sigungu)입니다. 사용자가 말한 단위를 바꾸지 않고, 말하지 않았으면 그 지역에서 분석 가능한 단위를 씁니다.
  4. assumptions에는 정책 정의를 반복하지 않고, 추가로 둔 가정만 씁니다.
  5. key_concepts에는 분석에 필요한 데이터 개념을 짧은 명사구로 씁니다(검색어로 쓰임).
- 출력 `InterpretedQuery`: `intent`, `unsupported_reason`, `region{name, level}`, `analysis_unit`, `restated_question`, `key_concepts`, `assumptions`
- 검사는 다음 순서로 진행합니다. 계획을 만들기 전에 끝내서 불필요한 LLM 호출을 줄입니다.
  1. intent가 없으면 `UNSUPPORTED_QUESTION`
  2. 지역이나 단위가 없으면 `INCOMPLETE_INTERPRETATION`
  3. 지역의 이름과 단위가 모두 일치하는 coverage가 없으면 `REGION_NOT_SUPPORTED`. 메시지 예: `'서울특별시'(emd) 데이터가 없습니다. 분석 가능한 지역: 서울특별시(sido)`
  4. 그 지역에 해당 단위의 경계 데이터가 없으면 `UNIT_NOT_SUPPORTED`. 메시지 예: `분석 가능한 단위: 행정동(emd)`

#### ② select_datasets: 후보 검색과 선택

pgvector는 후보를 찾고, LLM은 최종 선택을 하고, Validator는 실제로 쓸 수 있는지 검증합니다(전달 문서 33번 구조).

1. 검색어 = `restated_question` + `key_concepts`
2. 카탈로그 임베딩이 최신인지 확인합니다. 임베딩이 없거나, 모델이 다르거나, 임베딩한 문서가 현재 메타데이터로 만든 문서와 다르면 `CATALOG_INDEX_STALE`로 멈춥니다. 임베딩이 빠진 Dataset이 후보에서 조용히 사라지는 것을 막기 위해서입니다.
3. 검색어를 임베딩하고 pgvector 코사인 거리로 상위 10개를 고릅니다(`SEARCH_LIMIT = 10`). 지금은 Dataset이 3개라 모두 후보가 되고, 유사도는 순서만 정합니다.
4. LLM에 후보 요약(제목, 설명, 분류, 태그, 공간·시간 정보, 컬럼 설명)을 주고 `DatasetSelection{datasets, rationale}`을 받습니다.
5. 선택 원본을 **검사 전에** 기록합니다. 잘못된 선택도 근거와 함께 추적하기 위해서입니다. 후보에 없는 ID를 골랐거나 아무것도 고르지 않았으면 `INVALID_DATASET_SELECTION`입니다. 통과한 선택은 중복을 제거해 `selected_datasets`에 둡니다.

실제 실행 기록 예시(`dataset_search`): `daycare_facility` 0.571, `population_by_age` 0.560, `emd_boundary` 0.362

#### ③ build_analysis_plan: 분석 계획 생성

- 입력은 해석 결과 JSON과 **선택된 Dataset의 상세 메타데이터**입니다. 상세 메타데이터에는 컬럼 타입·의미 유형, join key, 공간·시간 정보가 들어가고, bbox와 feature 수는 빠집니다.
- 프롬프트에는 분석 정책, Operation 의미, 작성 규칙 7개가 들어갑니다.
  1. intent·region·analysis_unit은 해석 결과를 그대로 씁니다.
  2. 사용하는 Dataset을 `datasets`에 모두 선언하고, 주어진 Dataset만 씁니다.
  3. 질문이나 정책이 요구하는 행 조건만 필터로 둡니다(기준일·유형 나열 같은 요구되지 않은 조건 금지). 경계 Dataset에는 필터를 두지 않습니다.
  4. Operation은 실행 순서대로 쓰고, 앞에서 만든 output만 참조합니다.
  5. output 이름은 snake_case로 쓰고, 서로는 물론 Dataset ID·컬럼명과도 겹치지 않게 합니다.
  6. `output.metric`은 지도에 칠할 지표입니다. 순위(rank) 결과는 쓸 수 없습니다.
  7. ranking을 켜면 해당 지표의 rank Operation이 있어야 합니다.
- 재생성할 때는 이전 계획과 검증 오류 목록(`[코드] 경로: 메시지`)을 함께 보냅니다.
- 응답이 스키마를 통과하지 못하면(`LLMOutputError`) 실행하지 않고 `PLAN_SCHEMA_INVALID` 시도로 기록한 뒤 재생성합니다.

#### ④ validate_plan: 계획 검증과 재생성

- [Plan Validator](../app/validation/plan_validator.py)는 DB 없이 메타데이터만으로 판정하는 순수 함수입니다. 규칙 목록은 3.6절에 있습니다.
- Plan Validator에 더해, 계획이 해석 결과(intent·지역·단위)를 바꾸지 않았는지 검사합니다(`PLAN_INTERPRETATION_MISMATCH`). LLM이 지원 범위로 몰래 바꾸는 것을 막기 위해서입니다.
- 결과에 따라 다음으로 진행합니다.
  - 오류가 없으면 `load_data`로 갑니다.
  - 첫 시도에 오류가 있으면 피드백과 함께 계획을 다시 만듭니다(`MAX_PLAN_ATTEMPTS = 2`).
  - 두 번째 시도도 실패하면 `PLAN_INVALID`로 끝나고, `issues`에 오류 목록이 담깁니다.
- 모든 시도는 `plan_history`에 계획과 검증 결과가 함께 남습니다.

#### ⑤ load_data: 데이터 바인딩

- 연결 풀에서 연결 하나를 받아 `REPEATABLE READ, READ ONLY` 트랜잭션을 시작합니다. ⑤~⑧ 단계가 같은 스냅샷을 보고, 실수로라도 쓰기가 일어나지 않습니다.
- 분석 단위 경계 Dataset을 정합니다. `plan.datasets` 중 Polygon이면서 단위가 `analysis_unit`인 Dataset이 정확히 1개여야 합니다.
- `get_boundary`가 하는 일:
  - 지역 이름 컬럼(예: `sido_nm = '서울특별시'`)으로 경계를 거릅니다.
  - 단위 목록(코드, 동 이름, 자치구 이름)을 만들고, 키가 유일한지 검사합니다.
  - Geometry 유효성(`ST_IsValid`, `ST_IsEmpty`)을 검사하고 bbox를 계산합니다.
- 나머지 Dataset은 `get_dataset`(테이블 존재, 행 수 > 0)으로 가져오고, 필터가 있으면 `filter_dataset`(결과 > 0)을 적용합니다.
- View는 메타데이터와 필터 참조일 뿐 데이터를 옮기지 않습니다. 실제 계산은 SQL 한 번으로 PostGIS 안에서 일어납니다.

#### ⑥ execute_operations: GIS 실행

- [Executor](../app/executor/operation_executor.py)가 `HANDLERS[op.type]`으로 각 Operation을 GIS Tool에 매핑해 순서대로 실행합니다. 결과(`MetricValues`)는 `output` 이름으로 등록해 뒤의 Operation이 참조합니다.
- Operation마다 `OperationLog`(파라미터, 통계, 소요 ms)를 남깁니다.
  - 통계 예: `input_points`, `assigned_points`, `unassigned_points`, `group_count`, `computed`, `denominator_zero`, `ranked`
- **결과 조립**: 경계의 단위 목록(서울 427개 행정동)을 결과 프레임으로 삼고, 각 metric을 단위 코드로 결합해 `UnitRow`를 만듭니다. 값이 없으면 null과 사유를 남깁니다. 경계에 없는 코드(예: 경계에 없는 인구 행정동 코드)는 `unmatched_keys`에 기록합니다.

| Operation | GIS Tool | 계산 | 결측·특수 처리 |
|---|---|---|---|
| `aggregate_by_area` | `aggregate_by_area` | Point를 경계 Polygon 안에서 셈(`ST_Covers`) | 시설이 없으면 0. 경계선 위 점은 코드가 가장 작은 단위 하나에만 배정. 지역 밖 점은 `unassigned_points`로 기록 |
| `aggregate` | `aggregate` | 그룹 키(join key 1개)별 `sum` 또는 `count` | 행이 없는 단위는 null(`no_matching_records`) |
| `calculate_ratio` | `calculate_ratio` | `numerator ÷ denominator × scale` | 분모 0은 null(`denominator_zero`), 분모 없음은 null(`denominator_missing`). 0으로 대체하지 않음 |
| `rank` | `rank` | 표준 경쟁 순위(1, 2, 2, 4) | null은 순위에서 제외(`input_null`) |

`aggregate_by_area`의 SQL 요지입니다. CRS가 다르면 Point를 경계 CRS로 변환합니다.

```sql
WITH units AS NOT MATERIALIZED (
    SELECT adm_cd::text AS unit_key, geom FROM datasets.emd_boundary WHERE sido_nm = %s
),
points AS NOT MATERIALIZED (
    SELECT ctid AS point_id, geom FROM datasets.daycare_facility WHERE TRUE
),
assigned AS (
    SELECT DISTINCT ON (p.point_id) p.point_id, u.unit_key
    FROM points p JOIN units u ON ST_Covers(u.geom, p.geom)
    ORDER BY p.point_id, u.unit_key          -- 경계선 위 점은 코드가 작은 단위 하나에만
)
SELECT u.unit_key, count(a.point_id) FROM units u LEFT JOIN assigned a USING (unit_key) GROUP BY u.unit_key;
```

#### ⑦ validate_result: 결과 검증

[Result Validator](../app/validation/result_validator.py)가 지도·설명으로 넘기기 전에 결과를 검사합니다(규칙은 3.6절). 오류가 있으면 `RESULT_INVALID`로 멈추고, 경고는 최종 응답의 "한계"에 들어갑니다.

#### ⑧ create_map_layer: 지도 레이어

- 결과 행마다 Geometry를 EPSG:4326 GeoJSON으로 만듭니다. `properties`에는 `unit_key`, `unit_name`, `parent_name`, 모든 metric 값, `null_reason`이 들어갑니다.
- 출력 지표의 값으로 5분위 경계값(`breaks`, 최대 4개)과 min·max·null 수를 계산합니다.
- 경위도 범위를 벗어나거나 Geometry가 없는 단위가 있으면 실패합니다.
- 이 단계가 끝나면 읽기 전용 연결을 반납합니다.

#### ⑨ generate_explanation: 응답 조립과 설명

1. [`compose_response`](../app/workflows/response.py)가 최종 응답을 결정론적으로 조립합니다. LLM이 쓰는 칸은 `summary`뿐입니다.
   - `metric`: 지표 이름, 라벨, 해석(정책). `metric_labels`는 output별 라벨, `rank_metric`은 순위 output입니다.
   - `ranking`: rank 결과 순서로 상위 `ranking.limit`개(기본 10)
   - `analysis_method`: 실행한 계획을 문장으로 바꾼 것. 예: `필터 — 행정동별 연령별 주민등록 인구(population_by_age): age 0~5`
   - `datasets`: 제목, 제공자, 출처, 라이선스, 기준 시점
   - `assumptions`: 정책 정의 + 해석 가정
   - `limitations`: 정책 한계 + 기준 시점 차이 + Dataset 품질 기록 + 결과 검증 경고
2. `explanation_facts`가 설명용 사실 JSON을 만듭니다. 질문, 지표, 상위 순위와 구성 값, 요약 통계(단위 수, 값 있는 단위 수, 최소·중앙·최대), 데이터 기준 시점, 한계가 들어갑니다.
3. LLM은 이 JSON에 있는 수치만 써서 3~5문장 요약을 씁니다. 이것은 프롬프트 지시이고, 요약 문장 속 수치를 코드가 다시 검증하지는 않습니다.

#### ⑩ Provenance 저장

[`save_run`](../app/repositories/run_repository.py)이 `analysis.run`에 실행 기록을, 성공했으면 `analysis.result`에 최종 응답을 저장합니다(4.2절). 큰 GeoJSON은 `analysis.result`에만 저장하고 `run.state`에서는 뺍니다. `GET /api/analyses/{run_id}`로 조회할 수 있습니다.

### 3.4 AgentState: 실행 상태

[`AgentState`](../app/domain/state.py)는 한 번의 실행에서 각 단계의 입력과 판단을 모두 담고, 그대로 Provenance가 됩니다.

| 필드 | 내용 |
|---|---|
| `run_id`, `question` | 실행 ID(UUID), 원래 질문 |
| `status`, `current_step` | `running` / `succeeded` / `failed`, 현재(또는 실패한) 단계 |
| `interpreted_query` | 질문 해석 결과 |
| `dataset_search` | 검색어, 임베딩 모델, 후보별 유사도 |
| `dataset_candidates` | LLM에 보여준 후보 메타데이터 전체 |
| `dataset_selection` | LLM 선택 원본(근거 포함, 검사 전에 기록) |
| `selected_datasets` | 검사를 통과한 선택 |
| `analysis_plan`, `plan_validation` | 마지막 계획과 검증 결과 |
| `plan_history` | 재생성을 포함한 모든 계획 시도와 각 검증 결과 |
| `execution_results` | 단위별 결과 행, metric 정보, Operation 로그, 미매칭 코드 |
| `result_validation` | 결과 검증 보고서 |
| `map_layer`, `final_response` | 지도 레이어, 최종 응답 |
| `errors` | 실패 단계, 코드, 메시지, 세부 issues |
| `llm_provider`, `llm_model`, `started_at`, `finished_at` | 실행 환경과 시각 |

### 3.5 핵심 계약 (Core Contracts)

모든 계약은 `StrictModel`(Pydantic, `extra="forbid"`)이라 정의되지 않은 필드가 오면 거부합니다.

#### AnalysisPlan

LLM이 만드는 유일한 "실행 지시"입니다. 첫 Use Case의 기대 계획([tests/fixtures/plan_daycare.json](../tests/fixtures/plan_daycare.json)):

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
    {"type": "calculate_ratio", "label": "0~5세 어린이 1,000명당 어린이집 수", "numerator": "daycare_count",
     "denominator": "child_population", "scale": 1000, "output": "daycare_per_1000_children"},
    {"type": "rank", "label": "부족 순위", "input": "daycare_per_1000_children", "order": "asc",
     "output": "shortage_rank"}
  ],
  "output": {"map_type": "choropleth", "metric": "daycare_per_1000_children",
             "ranking": {"enabled": true, "limit": 10}}
}
```

output 이름과 라벨은 LLM이 정하므로 실행마다 다를 수 있습니다(예: `child_population` 대신 `total_children_population`). 화면과 응답은 이름이 아니라 `metric_labels`, `rank_metric`으로 열을 찾습니다.

#### Operation (discriminated union, `type`으로 구분)

| type | 주요 필드 | 의미 |
|---|---|---|
| `aggregate_by_area` | `input`(Point Dataset), `boundary`(Polygon Dataset), `aggregation: "count"` | 경계 단위별 점 개수 |
| `aggregate` | `input`, `group_by`(join key 1개), `aggregation{field, function: sum\|count}` | 속성 그룹 집계 |
| `calculate_ratio` | `numerator`, `denominator`(앞선 output), `scale`(> 0) | 비율 |
| `rank` | `input`(앞선 output), `order: asc\|desc` | 순위 |

모든 Operation에는 공통으로 `label`(짧은 한국어 이름)과 `output`(snake_case, 고유 이름)이 있습니다.

#### FilterExpression

- `FilterCondition{field, operator, value}` 하나이거나, `FilterGroup{logic: and|or|not, conditions[]}` 1단계 그룹입니다. 그룹은 중첩할 수 없습니다.
- 연산자 13개: `eq`, `neq`, `gt`, `gte`, `lt`, `lte`, `between`, `in`, `not_in`, `contains`, `starts_with`, `is_null`, `is_not_null`
- 값 형태 검증: `between`은 `[최소, 최대]`, `in`은 비어 있지 않은 목록, null 검사는 값이 null이어야 합니다. 컬럼 타입과의 호환(숫자·날짜 비교, 문자열 검색)은 메타데이터로 확인합니다.
- [SQL 컴파일](../app/gis/filter_sql.py): 컬럼명은 메타데이터에 있는지 확인한 뒤 `sql.Identifier`로 넣고, 값은 항상 파라미터로 넘깁니다. LIKE 특수문자는 이스케이프합니다.

#### DatasetMetadata

카탈로그의 단위이자 LLM·Validator·GIS Tool·검색이 모두 참조하는 계약입니다([app/domain/catalog.py](../app/domain/catalog.py), 정의는 [app/catalog/definitions.py](../app/catalog/definitions.py)).

| 필드 | 내용 |
|---|---|
| `dataset_id` | ID이자 테이블 이름(`datasets.<dataset_id>`) |
| `title`, `description`, `category`, `semantic_tags` | 의미 정보(LLM 선택·임베딩 검색에 사용) |
| `provider`, `source`, `license` | 출처와 라이선스(응답에 표시) |
| `spatial` | `level`(단위), `geometry_type`, `crs`, `coverage`(범위 지역), `bbox`·`feature_count`(적재 시 계산) |
| `temporal` | `reference_date`(적재 시 계산), `update_cycle` |
| `columns[]` | `name`, `description`, `data_type`, `semantic_type`, `unit`, `nullable` |
| `join_keys[]` | `field`, `semantic_type`, `code_system`(예: 행안부 10자리 행정기관코드) |
| `quality_notes[]` | 적재 시 품질 규칙으로 제외한 내역 등(응답의 "한계"에 표시) |

#### 분석 정책 (IntentPolicy)

[app/domain/policies.py](../app/domain/policies.py)에 intent마다 하나씩 있고, 세 곳에서 쓰입니다.

- **프롬프트**: 해석과 계획 단계에 들어갑니다.
- **Plan Validator**: `POLICY_VIOLATION`으로 준수 여부를 검사합니다.
- **최종 응답**: 정의는 "가정"에, 한계는 "한계"에 들어갑니다.

| 항목 | `supply_demand_gap` |
|---|---|
| 계산 | 시설 수 ÷ 수요 인구 × 1,000 (`ratio_scale = 1000`) |
| 순위 | 오름차순(`rank_order = asc`), 값이 작을수록 부족 |
| 정의 | '부족' = 1,000명당 시설 수가 상대적으로 작음, '어린이 인구' = 만 0~5세 |
| 한계 | 정원·현원 미반영, 경계를 넘는 이용 미반영, 수요가 적은 동은 지표 변동이 큼 |

### 3.6 검증 계층

LLM 출력은 세 겹으로 검사합니다.

1. **Pydantic 스키마**: 필드·타입, Operation union 구분, 필터 값 형태, output 이름 패턴(`^[a-z][a-z0-9_]{0,62}$`)
2. **Plan Validator**: 메타데이터 기준 의미 검사(아래 표)
3. **Result Validator**: 실행 결과 검사(아래 표)

**Plan Validator 규칙** (오류가 하나라도 있으면 실행하지 않음)

| 범주 | 코드 |
|---|---|
| Dataset 참조 | `UNKNOWN_DATASET`(후보에 없음), `DATASET_NOT_DECLARED`(참조했지만 `datasets`에 없음), `DATASET_NOT_SELECTED`(선택 단계에서 고르지 않음), `UNUSED_DATASET`(경고) |
| 지역·분석 단위 | `REGION_NOT_COVERED`, `UNIT_BOUNDARY_MISSING`, `UNIT_BOUNDARY_AMBIGUOUS`, `CRS_UNSUPPORTED` |
| 필터 | `FILTER_FIELD_UNKNOWN`, `FILTER_TYPE_MISMATCH`, `DUPLICATE_FILTER`, `BOUNDARY_FILTER_UNSUPPORTED` |
| Operation | `GEOMETRY_REQUIRED`, `GEOMETRY_TYPE_INVALID`, `BOUNDARY_NOT_ANALYSIS_UNIT`, `JOIN_KEY_INCOMPATIBLE`(의미 유형·코드 체계·단위 일치), `FIELD_UNKNOWN`, `FIELD_NOT_NUMERIC`, `RATIO_OPERAND_INVALID`, `OPERATION_INPUT_UNKNOWN`, `OUTPUT_NAME_CONFLICT` |
| 출력 | `OUTPUT_METRIC_NOT_COMPUTED`, `OUTPUT_METRIC_IS_RANK`, `RANKING_NOT_DEFINED` |
| 분석 정책 | `POLICY_VIOLATION`(출력 지표가 scale 1,000인 비율이고 오름차순 순위가 켜져 있어야 함) |
| 워크플로가 추가 | `PLAN_SCHEMA_INVALID`(스키마 불일치), `PLAN_INTERPRETATION_MISMATCH`(해석과 다른 intent·지역·단위) |

**Result Validator 규칙**

| 구분 | 코드 |
|---|---|
| 오류 → `RESULT_INVALID` | `RESULT_EMPTY`, `DUPLICATE_UNITS`, `INVALID_GEOMETRY`, `NEGATIVE_VALUE`(개수·인구), `ZERO_DENOMINATOR_UNHANDLED`, `NON_FINITE_VALUE`, `HIGH_NULL_RATE`(출력 지표 null > 20%), `OUT_OF_REGION`(bbox ±0.01° 초과), `UNIT_COUNT_MISMATCH`(예상 단위 수와 10% 넘게 차이) |
| 경고 → 응답의 "한계" | `NULL_VALUES`, `UNMATCHED_KEYS`, `UNASSIGNED_POINTS`, `UNIT_COUNT_MISMATCH`(작은 차이), `REGION_CHECK_SKIPPED`, `UNIT_COUNT_CHECK_SKIPPED` |

### 3.7 실패 코드 모음 (`WorkflowError.code`)

| 단계 | 코드 |
|---|---|
| 해석 | `UNSUPPORTED_QUESTION`, `INCOMPLETE_INTERPRETATION`, `REGION_NOT_SUPPORTED`, `UNIT_NOT_SUPPORTED` |
| 검색·선택 | `CATALOG_INDEX_STALE`, `EMBEDDING_FAILED`, `INVALID_DATASET_SELECTION` |
| 계획 | `PLAN_INVALID` (`issues`에 Plan Validator 코드) |
| GIS 실행 | GIS Tool 코드가 그대로 올라옴: `UNIT_BOUNDARY_MISSING`, `REGION_NOT_COVERED`, `DATASET_TABLE_MISSING`, `DATASET_EMPTY`, `FILTER_INVALID`, `FILTER_EMPTY_RESULT`, `NOT_POLYGON`, `BOUNDARY_METADATA_INCOMPLETE`, `REGION_NOT_FOUND`, `DUPLICATE_UNIT_KEY`, `INVALID_GEOMETRY`, `CRS_UNSUPPORTED`, `NO_GEOMETRY`, `NOT_POINT`, `UNSUPPORTED_AGGREGATION`, `MULTI_GROUP_UNSUPPORTED`, `FIELD_UNKNOWN`, `FIELD_NOT_NUMERIC`, `NON_FINITE_RESULT`, `OUTPUT_CRS_INVALID`, `GEOMETRY_MISSING` |
| 결과 | `RESULT_INVALID` (`issues`에 Result Validator 코드) |
| 공통 | `LLM_FAILED`(API 오류·거절·잘림·스키마 불일치), `INTERNAL_ERROR`(예상하지 못한 예외, 서버 로그에 스택 기록) |

분석이 실패해도 실행 기록이 남으므로 HTTP 응답은 200이고, `status: "failed"`와 `errors`로 구분합니다.

### 3.8 LLM 연동

| 구성 | 내용 |
|---|---|
| 포트 | `StructuredLLM.generate(system, user, output_type) -> output_type` ([app/llm/base.py](../app/llm/base.py)). 공급자 차이는 어댑터 안에 숨김 |
| OpenAI | [`OpenAIResponsesLLM`](../app/llm/openai_llm.py): Responses API, `text.format = json_schema(strict)`, `store=False`. 미완료·거절 응답은 `LLMError` |
| Ollama | [`OllamaChatLLM`](../app/llm/ollama_llm.py): OpenAI SDK의 `base_url`을 Ollama `/v1`로 지정, Chat Completions `response_format=json_schema`, `temperature=0`, 스키마를 시스템 프롬프트에도 포함, `reasoning_effort` 선택, 길이 초과로 잘리면 `LLMError` |
| 스키마 변환 | [`to_llm_json_schema`](../app/llm/schema.py): 모든 object에 `additionalProperties=false`와 전 필드 required, `oneOf`→`anyOf`, `const`→`enum`, 수치·길이·패턴 제약과 default 제거. 제거한 제약은 응답 수신 후 Pydantic이 다시 검증 |
| 응답 검증 | 응답 JSON을 `model_validate_json`으로 다시 검증하고, 실패하면 `LLMOutputError`(계획 단계에서는 재생성 대상) |
| 전환 | `.env`의 `LLM_PROVIDER=openai\|ollama` ([factory.py](../app/llm/factory.py)) |
| 임베딩 | [`OpenAIEmbedder`](../app/llm/embeddings.py): `OPENAI_EMBEDDING_MODEL`(기본 `text-embedding-3-small`), `dimensions=1536`. `LLM_PROVIDER`와 관계없이 항상 OpenAI라서 Ollama로 실행해도 `OPENAI_API_KEY`가 필요 |

**주의**: OpenAI strict 모드는 `$ref` 옆에 다른 키워드를 허용하지 않아서, 변환할 때 `$ref` 필드의 `description`을 지웁니다. 예를 들어 `Region.level`의 의미는 스키마로는 LLM에 전달되지 않으므로 프롬프트 규칙으로 설명해야 합니다.

**검증한 모델과 알려진 특성**

코드 기본값은 `gpt-6.1-sol`이지만, 실제로 검증한 모델은 아래 두 개입니다.

| 모델 | 결과 | 특성 |
|---|---|---|
| OpenAI `gpt-4o-mini` | 화면에서 실행 성공(2회), 15~21초 | `region.level`에 분석 단위(emd)를 넣는 혼동이 있었음(10회 중 8회). 프롬프트 규칙 추가 후 10회 모두 정상(커밋 `0958c83`) |
| Ollama `qwen3.5:9b` | E2E 성공 기준 1~12 통과, 실행 성공 8회, 66~194초 | thinking 모델이라 `OLLAMA_REASONING_EFFORT=none`이 필요(해석 단계 130초 → 6초). 첫 계획에서 순위를 `output.metric`에 넣는 실수(`OUTPUT_METRIC_IS_RANK`)가 잦지만, 피드백 재생성으로 복구됨 |

---

## 4. 데이터베이스

### 4.1 구성

| 항목 | 내용 |
|---|---|
| DBMS | PostgreSQL 17.6 |
| 확장 | PostGIS 3.5.3(공간 연산), pgvector 0.8.7(임베딩 유사도 검색) |
| 이미지 | [docker/postgres/Dockerfile](../docker/postgres/Dockerfile): `imresamu/postgis:17-3.5`(multi-arch PostGIS)에 `postgresql-17-pgvector`를 설치해 빌드 |
| 실행 | `docker compose up -d --build` (서비스 `db`, 포트 5432, 볼륨 `pgdata`, 계정·DB `mapgpt`) |
| 스키마 | [app/db/schema.sql](../app/db/schema.sql), `python -m app.cli init-db`로 적용. `CREATE ... IF NOT EXISTS`라 반복 실행할 수 있음 |
| 드라이버 | psycopg 3 + psycopg_pool (API 풀 최소 1, 최대 5) |

### 4.2 스키마와 테이블

스키마 3개로 역할을 나눕니다.

- **`catalog`**: 무엇이 있는가 (메타데이터, 검색 임베딩)
- **`datasets`**: 분석할 데이터 (내부 표준 Dataset)
- **`analysis`**: 무엇을 했는가 (실행 기록, 결과)

| 테이블 | 주요 컬럼 | 용도·인덱스 |
|---|---|---|
| `catalog.dataset` | `dataset_id` PK, `metadata` jsonb, `loaded_at` | `DatasetMetadata` 전체(적재 통계·품질 기록 포함) |
| `catalog.dataset_embedding` | `dataset_id` PK·FK(`ON DELETE CASCADE`), `model`, `source_text`, `embedding vector(1536)`, `embedded_at` | Dataset당 임베딩 1개. HNSW 인덱스(`vector_cosine_ops`). `source_text`는 임베딩한 문서이며 최신 여부 판단에 씀 |
| `datasets.emd_boundary` | `adm_cd` PK, `adm_nm`, `sido_cd`, `sido_nm`, `sigungu_cd`, `sigungu_nm`, `geom MultiPolygon(4326)` | 행정동 경계. GiST 인덱스 |
| `datasets.population_by_age` | (`adm_cd`, `age`) PK, `population`, `reference_date` | 행정동별 1세 단위 인구(long 형식). 음수 금지 CHECK |
| `datasets.daycare_facility` | `facility_id` PK, `name`, `facility_type`, `latitude`, `longitude`, `geom Point(4326)` | 운영 중 어린이집 위치. GiST 인덱스 |
| `analysis.run` | `run_id` PK, `question`, `status`, `analysis_plan`, `datasets`, `operations`, `crs`, `result_id`, `llm_provider`, `llm_model`, `errors`, `state`, `started_at`, `finished_at` | 모든 실행 기록(성공·실패). `state`는 `AgentState` 전체(`map_layer`·`final_response` 제외) |
| `analysis.result` | `result_id` PK, `run_id` FK, `response` jsonb, `created_at` | 성공한 실행의 `FinalResponse`(GeoJSON 포함) |

**규약**: GIS Tool은 `datasets.<dataset_id>` 테이블을 찾고, 컬럼 의미는 메타데이터로 판단합니다. 새 Dataset도 이 규약만 지키면 GIS 코드를 고치지 않고 쓸 수 있습니다.

`analysis.run`의 컬럼은 전달 문서 24번의 Provenance 항목에 1:1로 대응합니다.

| Provenance 항목 | 컬럼 |
|---|---|
| 실행 ID, 질문 | `run_id`, `question` |
| Dataset ID와 기준 시점 | `datasets` |
| 분석 계획 | `analysis_plan` |
| 실행한 Operation | `operations` |
| 분석 CRS | `crs` |
| 실행 시각 | `started_at`, `finished_at` |
| 결과 ID | `result_id` |

### 4.3 데이터를 읽고 쓰는 방식

| 시점 | 대상 | 방식 |
|---|---|---|
| 적재 (`cli ingest`) | `datasets.*`, `catalog.dataset` | Dataset마다 한 트랜잭션에서 테이블을 비우고(TRUNCATE) 다시 채움(INSERT/COPY) → 통계 계산 → 카탈로그 upsert |
| 적재 후 (`embed-catalog`) | `catalog.dataset_embedding` | 문서가 바뀐 Dataset만 다시 임베딩해 upsert |
| 분석 ① | `catalog.dataset` | 전체 메타데이터 조회(지역·단위 계산) |
| 분석 ② | `catalog.dataset_embedding` | 최신 여부 검사 후 KNN: `ORDER BY embedding <=> 검색어 LIMIT 10` |
| 분석 ⑤~⑧ | `datasets.*` | 연결 1개, `REPEATABLE READ, READ ONLY` 트랜잭션, parameterized SQL |
| 분석 종료 | `analysis.run`, `analysis.result` | 성공·실패 모두 한 트랜잭션에 저장 |
| API 조회 | `analysis.run` ⟕ `analysis.result` | `GET /api/analyses/{run_id}` |

**SQL 안전성**: LLM은 SQL을 만들지 않습니다. GIS Tool이 쓰는 테이블·컬럼 이름은 메타데이터로 확인한 뒤 `psycopg.sql.Identifier`로 넣고, 값은 모두 파라미터로 넘깁니다.

### 4.4 현재 적재된 데이터

| Dataset | 행 수 | 기준 시점 | 비고 |
|---|---|---|---|
| `emd_boundary` | 427 | 2026-07-01 | 서울 행정동 |
| `population_by_age` | 47,397 | 2026-09-30 | 427개 동 × 111개 연령(0~110세 이상). 0~5세 합계 250,170명 |
| `daycare_facility` | 3,895 | 2026-10-07 | 운영 중이고 품질 규칙을 통과한 시설 |

어린이집 품질 규칙으로 제외한 내역(`quality_notes`, 응답의 "한계"에 표시):

- 운영 중(정상·재개)이 아닌 시설 5,575건: 폐지 5,504, 휴지 68, 미기재 3
- 서로 다른 자치구 시설이 같은 좌표를 공유하는 지점 1곳의 시설 18건(기본값 좌표로 판단)
- 좌표가 신고 자치구가 아닌 다른 자치구에 있는 시설 6건
- 좌표가 서울 경계 밖에 있는 시설 1건

### 4.5 테스트 DB

통합 테스트는 같은 Docker DB의 `mapgpt_test`를 씁니다. DB가 없으면 테스트가 만듭니다. 테스트 세션마다 스키마를 지우고 최신 DDL로 다시 만들고, 테스트마다 테이블을 비운 뒤 합성 데이터를 넣습니다.

---

## 5. 데이터 적재 파이프라인

외부 원본 → Provider Adapter → 내부 표준 Dataset → 카탈로그 갱신 → 검색 임베딩 동기화 순서입니다([app/data_sources/ingest.py](../app/data_sources/ingest.py)).

```mermaid
flowchart LR
    SRC["외부 원본<br/>파일 · OpenAPI"] --> AD["Adapter<br/>파싱 · 정규화"]
    AD --> QR["형식 검사 ·<br/>품질 규칙"]
    QR --> DATA[("datasets.*<br/>테이블 교체")]
    DATA --> META[("catalog.dataset<br/>메타데이터 + 적재 통계")]
    META --> SYNC["임베딩 동기화<br/>바뀐 문서만"]
    SYNC --> VEC[("catalog.dataset_embedding")]
```

| Dataset | 출처 | 수집 형식 | 라이선스 |
|---|---|---|---|
| `emd_boundary` | 통계청 SGIS 기반 [vuski/admdongkor](https://github.com/vuski/admdongkor) `ver20260701` | GeoJSON 파일 다운로드 | CC BY 4.0 (출처: 통계청 SGIS) |
| `population_by_age` | 행정안전부, [공공데이터포털 15097972](https://www.data.go.kr/data/15097972/fileData.do) | CSV 파일 다운로드(cp949, 연령이 열인 wide 형식) | 이용허락범위 제한 없음 |
| `daycare_facility` | 서울 열린데이터광장 `ChildCareInfo` (OA-20300) | OpenAPI, 1,000건 단위 페이지. 원본 JSON을 `data/raw/`에 캐시 | 공공누리 제4유형 (출처표시·상업적 이용금지·변경금지) |

```bash
python -m app.cli download              # 경계 GeoJSON, 인구 CSV → data/raw/
python -m app.cli ingest all            # 경계 → 인구 → 어린이집 순서 (어린이집 위치 검증에 경계가 필요)
python -m app.cli embed-catalog         # 바뀐 Dataset만 다시 임베딩 (ingest 끝에 자동 실행됨)
```

Dataset별 처리:

- **행정동 경계**
  - 서울(sido `11`)만 남기고 CRS(CRS84/EPSG:4326)를 확인합니다.
  - `adm_cd2`(행안부 10자리)를 `adm_cd`로 쓰고, 동 이름은 `adm_nm`의 마지막 토큰을 씁니다.
  - 코드 형식과 중복을 검사하고, `ST_MakeValid`로 보정한 뒤 MultiPolygon으로 저장합니다. 보정 개수는 품질 기록에 남깁니다.
  - 기준 시점은 파일 버전(`ver20260701`)입니다.
- **연령별 인구**
  - 인코딩(UTF-8/cp949)을 판별하고 서울만 남깁니다.
  - 0~110세(110세 이상)의 남+여를 `(adm_cd, age, population)` long 형식으로 바꿉니다.
  - 행마다 "계 = 연령별 합"인지, 기준일이 하나뿐인지 검사합니다.
- **어린이집**
  - API로 전체를 수집하고 건수를 검증합니다.
  - 품질 규칙 4개를 적용합니다(아래). 좌표 위치 규칙(4번)으로 제외되는 비율이 20%를 넘으면 코드 체계나 좌표계 문제로 보고 적재를 중단합니다.
  - 기준 시점은 원본 데이터기준일자의 최댓값입니다. 행별 기준일 컬럼은 저장하지 않습니다(LLM이 기준일 필터로 오인한 적이 있음).

어린이집 품질 규칙(결정론적):

1. 운영현황 `정상`·`재개`만 포함
2. 좌표가 없거나 대한민국 범위 밖이면 제외
3. 서로 다른 자치구 시설들이 같은 좌표를 공유하면 기본값 좌표로 보고 모두 제외
4. 좌표가 신고 자치구(시설 코드 앞 5자리) 경계 안에 없으면 제외 (SQL로 판정)

**새 Dataset 추가**: 지금은 사람이 데이터를 찾아 검증한 뒤 코드로 등록합니다. 전달 문서 30번은 자동 공공데이터 검색을 MVP 범위 밖으로 두었고, 36번은 "처음 발견한 데이터를 검증 없이 분석에 쓰지 않는다"고 정했습니다. pgvector 검색은 **등록된** Dataset 중에서 후보를 고를 뿐, 외부에서 새 데이터를 찾지 않습니다. 절차는 14장을 참고하세요.

**다른 출처(공공데이터포털 API 등)로 바꿀 때**: 같은 내부 표준 레코드를 돌려주는 Adapter를 새로 만들면, 품질 규칙·테이블·분석·화면은 그대로 둘 수 있습니다. Adapter에서 흡수해야 하는 차이는 다음과 같습니다.

| 항목 | 내용 |
|---|---|
| 인증·호출 | 서울 API는 키를 URL 경로에 넣음. 공공데이터포털은 `serviceKey` 파라미터를 쓰고 Encoding/Decoding 키를 구분해야 함 |
| 페이지 | 서울은 `/{start}/{end}/`. 공공데이터포털은 보통 `pageNo`·`numOfRows` |
| 응답 형식 | XML이 기본인 API가 많고, JSON을 요청하는 파라미터 이름이 API마다 다름 |
| 호출 한도 | 일일 호출 한도가 있으므로 원본을 `data/raw/`에 캐시 |
| 인코딩 | 관공서 CSV는 cp949가 많음 |
| 좌표계 | TM 좌표(예: EPSG:5179)를 주는 출처가 있음. 메타데이터 `crs`에 적으면 GIS Tool이 변환함(현재 지원: 4326, 5179) |
| 코드 체계 | 행정동 코드가 행안부 10자리인지 통계청 8자리인지 확인. 섞이면 `JOIN_KEY_INCOMPATIBLE`이므로 Adapter에서 변환 |
| 좌표 없음 | 주소만 있으면 지오코딩이 필요함(현재 범위 밖) |
| 라이선스·갱신 | 공공누리 유형을 메타데이터에 기록. 파일 데이터는 갱신 때 다운로드 링크가 바뀌므로, 지금 인구 파일은 2026-09-30판에 고정되어 있음 |

여러 공공데이터를 범용으로 수집하기 위한 조사 결과와 권장 구조, 데이터 담당자가 결정할 사항은 [데이터 담당자 전달 문서](data-handoff.md)에 있습니다.

---

## 6. 백엔드

### 6.1 기술 스택

| 구분 | 사용 기술 (검증 버전) |
|---|---|
| 언어 | Python 3.12 (conda 환경 `mapgpt`) |
| API | FastAPI 0.142, uvicorn 0.54 |
| 계약·설정 | Pydantic 2.13, pydantic-settings 2.15 |
| DB | psycopg 3.3 + psycopg_pool 3.3 |
| LLM·임베딩 | OpenAI Python SDK 3.26 (Ollama도 OpenAI 호환 API로 호출) |
| 워크플로 | LangGraph 1.2 (`StateGraph`) |
| 테스트 | pytest, httpx |

### 6.2 디렉터리 구조

```text
app/
├── config.py                  # 설정 (.env → Settings)
├── cli.py                     # 운영 CLI: init-db, download, ingest, embed-catalog, analyze
├── api/
│   ├── main.py                # FastAPI 앱, 라우트, 의존성(DB 풀·LLM·임베딩)
│   └── schemas.py             # 요청/응답 모델
├── workflows/
│   ├── analysis_workflow.py   # LangGraph 분석 그래프(노드·라우터)와 실행기
│   └── response.py            # 최종 응답 조립, 설명용 사실 추출
├── agents/
│   ├── prompts.py             # 단계별 시스템/사용자 프롬프트
│   └── steps.py               # LLM 4단계 호출
├── llm/
│   ├── base.py                # StructuredLLM 포트, LLMError
│   ├── schema.py              # Pydantic → LLM 호환 JSON Schema
│   ├── openai_llm.py          # OpenAI Responses API
│   ├── ollama_llm.py          # Ollama (OpenAI 호환 Chat Completions)
│   ├── embeddings.py          # Embedder 포트, OpenAI 임베딩
│   └── factory.py             # 설정으로 LLM·임베딩 생성
├── catalog/
│   ├── definitions.py         # Trusted Dataset 3종 정적 메타데이터
│   └── catalog.py             # 임베딩 문서·동기화, DatasetCatalog.search
├── domain/
│   ├── base.py                # StrictModel
│   ├── enums.py               # intent, 공간 단위, 연산자, 단계 등
│   ├── catalog.py             # DatasetMetadata, ColumnMetadata, JoinKey, RegionRef
│   ├── filters.py             # FilterCondition, FilterGroup
│   ├── operations.py          # Operation 4종
│   ├── plan.py                # AnalysisPlan, Region, 지역·단위 해석 함수
│   ├── policies.py            # 분석 정책
│   ├── results.py             # 실행 결과, 검증 보고서, MapLayer, FinalResponse
│   └── state.py               # AgentState, LLM 출력 모델
├── validation/
│   ├── plan_validator.py
│   └── result_validator.py
├── executor/
│   └── operation_executor.py  # Operation → GIS Tool 핸들러, 결과 조립
├── gis/
│   ├── tools.py               # GIS Tool (PostGIS SQL)
│   ├── filter_sql.py          # FilterExpression → parameterized SQL
│   └── crs.py                 # CRS 정책
├── data_sources/
│   ├── adapters/              # admdongkor.py, mois_population.py, seoul_childcare.py
│   └── ingest.py              # 정규화 → 품질 규칙 → 적재 → 카탈로그 갱신
├── repositories/
│   ├── catalog_repository.py  # 메타데이터, 임베딩, KNN 검색
│   └── run_repository.py      # Provenance 저장·조회
└── db/
    ├── __init__.py            # 연결, 스키마 적용
    └── schema.sql             # DDL
```

저장소 루트: `docker-compose.yml`, `docker/postgres/`(DB 이미지), `pyproject.toml`, `.env.example`, `docs/`, `tests/`, `frontend/`, `data/raw/`(원본, git 제외)

### 6.3 REST API

| Method | Path | 설명 | 응답 |
|---|---|---|---|
| `POST` | `/api/analyses` | `{"question": "..."}`(1~500자)로 워크플로를 동기 실행 | 200 `{run_id, status, result, errors}`. 분석 실패도 200 + `status: "failed"`. 형식 오류 422, LLM·임베딩 설정 누락 503 |
| `GET` | `/api/analyses/{run_id}` | 실행 기록과 결과 조회 | `{run_id, status, question, provenance, result}`. 없으면 404 |
| `GET` | `/api/datasets` | 카탈로그 메타데이터 목록 | `DatasetMetadata[]` |
| `GET` | `/api/health` | 상태 확인 | `{status, database, llm_provider, llm_model, embedding_model}` |

성공 응답의 `result`(`FinalResponse`) 구조:

```json
{
  "run_id": "…", "result_id": "…", "question": "…",
  "summary": "LLM이 쓴 3~5문장 요약",
  "metric": {"name": "daycare_per_1000_children", "label": "…", "interpretation": "값이 작을수록 …"},
  "metric_labels": {"daycare_count": "어린이집 수", "child_population": "0~5세 인구", "…": "…"},
  "rank_metric": "shortage_rank",
  "ranking": [{"rank": 1, "unit_key": "…", "unit_name": "…", "parent_name": "…", "value": 0.0, "values": {}}],
  "map_layer": {"type": "choropleth", "metric": "…", "metric_label": "…", "crs": "EPSG:4326",
                "classification": {"method": "quantile", "class_count": 5, "breaks": [], "min": 0, "max": 0},
                "feature_count": 427, "null_count": 0, "geojson": {"type": "FeatureCollection", "features": []}},
  "analysis_method": ["분석 범위: …", "필터 — …", "…"],
  "datasets": [{"dataset_id": "…", "title": "…", "provider": "…", "source": "…", "license": "…", "reference_date": "…"}],
  "assumptions": ["…"],
  "limitations": ["…"]
}
```

실패 응답 예:

```json
{
  "run_id": "…", "status": "failed", "result": null,
  "errors": [{"step": "interpret_query", "code": "REGION_NOT_SUPPORTED",
              "message": "'부산광역시'(sido) 데이터가 없습니다. 분석 가능한 지역: 서울특별시(sido)", "issues": []}]
}
```

**실행 모델**: 엔드포인트는 동기 함수라 FastAPI 스레드풀에서 실행됩니다. 요청마다 설정으로 LLM·임베딩 클라이언트를 만들고, DB 연결 풀은 앱 수명 동안 하나를 공유합니다. 분석 한 건이 GIS 단계(⑤~⑧) 동안 연결 하나를 점유합니다.

### 6.4 CLI

| 명령 | 설명 |
|---|---|
| `python -m app.cli init-db` | 스키마 적용 (반복 실행 가능) |
| `python -m app.cli download` | 경계 GeoJSON, 인구 CSV를 `data/raw/`로 다운로드 |
| `python -m app.cli ingest <all / emd_boundary / population_by_age / daycare_facility> [--refresh]` | 적재. 어린이집은 API 캐시를 쓰고, `--refresh`면 다시 수집. 끝나면 임베딩 동기화 |
| `python -m app.cli embed-catalog [--refresh]` | 카탈로그 임베딩 동기화 (`--refresh`면 전부 다시) |
| `python -m app.cli analyze "질문"` | 터미널에서 워크플로 실행, 순위와 한계 출력 |

### 6.5 설정 (`.env`)

[.env.example](../.env.example)을 복사해 씁니다. `.env`는 git에서 제외되어 있습니다.

| 변수 | 기본값 | 설명 |
|---|---|---|
| `DATABASE_URL` | `postgresql://mapgpt:mapgpt@localhost:5432/mapgpt` | 개발 DB |
| `TEST_DATABASE_URL` | `…/mapgpt_test` | 통합 테스트 DB. 테스트는 셸 환경 변수에서 읽음 |
| `LLM_PROVIDER` | `openai` | `openai` 또는 `ollama` |
| `OPENAI_API_KEY` | 없음 | OpenAI LLM과 임베딩에 공용 |
| `OPENAI_MODEL` | `gpt-6.1-sol` | OpenAI LLM 모델 |
| `OPENAI_EMBEDDING_MODEL` | `text-embedding-3-small` | 검색 임베딩 모델(1536차원으로 요청) |
| `OLLAMA_BASE_URL` | `http://localhost:11434/v1` | Ollama 주소 |
| `OLLAMA_MODEL` | 없음 | 예: `qwen3.5:9b` |
| `OLLAMA_REASONING_EFFORT` | 없음 | thinking 모델의 추론 강도. `none`이면 thinking을 끔 |
| `SEOUL_OPEN_API_KEY` | 없음 | 서울 열린데이터광장 인증키(어린이집 수집) |
| `RAW_DATA_DIR` | `data/raw` | 원본 파일 저장 위치 |

운영에 필요한 과제(비동기 실행, 타임아웃, 인증, 마이그레이션, 배포 등)와 백엔드 담당자가 결정할 사항은 [백엔드 담당자 전달 문서](backend-handoff.md)에 있습니다.

---

## 7. 프론트엔드

### 7.1 기술 스택

| 구분 | 사용 기술 |
|---|---|
| 빌드·개발 서버 | Vite 8.3 (`:5173`, `/api`는 FastAPI `:8000`으로 프록시, 타임아웃 300초) |
| UI | React 19.3, TypeScript 7.0 (strict) |
| 지도 | MapLibre GL 6.13 |
| 배경지도 | [OpenFreeMap](https://openfreemap.org) positron(라이트) / dark(다크) 스타일. API 키 불필요 |

별도 상태 관리·UI 라이브러리 없이 React state와 CSS만 씁니다.

### 7.2 디렉터리 구조

```text
frontend/
├── index.html
├── vite.config.ts             # dev 서버, /api 프록시
└── src/
    ├── main.tsx               # 진입점
    ├── App.tsx                # 화면 구성, 질문 제출, 상태 관리
    ├── api.ts                 # POST /api/analyses 호출
    ├── types.ts               # 백엔드 응답 계약 (app/api/schemas.py, app/domain/results.py와 같음)
    ├── theme.ts               # 색 램프, 배경지도 스타일, 값 포맷, 결측 사유 문구, 다크 모드 감지
    ├── styles.css             # 레이아웃, 카드, 표, 범례, 라이트/다크 토큰
    └── components/
        ├── ChoroplethMap.tsx  # MapLibre 지도, 툴팁, hover 연동
        ├── Legend.tsx         # 분위 구간 범례
        ├── RankingTable.tsx   # 순위 표 (상위 N / 전체)
        ├── ResultDetails.tsx  # 데이터·기준 시점, 분석 방법, 가정, 한계, 실행 기록 링크
        └── ErrorPanel.tsx     # 실패 단계·코드·세부 issues
```

### 7.3 화면 구성

| 영역 | 내용 |
|---|---|
| 상단 헤더 | 질문 입력(최대 500자, 예시 질문이 기본값), 분석 버튼 |
| 왼쪽 패널(440px) | 진행 상태(경과 초, 단계 목록), 요청 오류, 분석 실패 패널, 요약과 지표, 순위 표, 사용 데이터·기준 시점, 분석 방법, 가정, 한계, 실행 기록 링크 |
| 오른쪽 지도 | Choropleth 지도, hover 툴팁, 범례 |
| 좁은 화면(860px 미만) | 헤더와 패널, 지도를 세로로 쌓음 |

### 7.4 상태와 데이터 흐름

1. `App`이 `question`, `loading`, `response`, `requestError`, `hoveredKey` 상태를 가집니다.
2. 제출하면 `requestAnalysis`가 `POST /api/analyses`를 호출합니다.
   - 응답이 오기 전까지 경과 시간과 고정된 단계 목록을 보여줍니다. API가 동기 방식이라 실시간 단계 진행은 아닙니다.
   - 이전 결과가 있으면 흐리게 표시합니다.
3. 응답에 따라 화면을 그립니다.
   - `status: "failed"`면 `ErrorPanel`이 단계 이름, 코드, 메시지, issues, 실행 기록 링크를 보여줍니다.
   - HTTP 오류(422, 503 등)는 "요청을 처리하지 못했습니다" 카드에 표시합니다.
4. 성공하면 요약·지표, `RankingTable`, `ResultDetails`, `ChoroplethMap`, `Legend`를 그립니다.
   - 표와 지도는 `hoveredKey`를 공유해 양방향으로 강조됩니다.
   - 순위 표는 기본으로 상위 N개를 보여주고, "전체 표 보기"를 누르면 지도와 같은 전체 단위를 순위순으로 보여줍니다(값 없는 단위는 맨 뒤).

### 7.5 지도 렌더링

- **데이터**: `map_layer.geojson`을 GeoJSON source로 올립니다(`promoteId: unit_key`). 레이어는 채움(투명도 0.85), 경계선, hover 강조선 3개입니다.
- **레이어 순서**: Choropleth를 배경지도의 도로·면 위, 마지막 레이블 묶음 아래에 넣어 지명이 가려지지 않게 합니다.
- **색**: 백엔드가 계산한 분위 경계값으로 MapLibre `step` 식을 만듭니다.
  - 단일 색상(blue) 5단계 ordinal 램프입니다. 라이트 모드는 진할수록, 다크 모드는 밝을수록 공급이 부족합니다. dataviz 팔레트 검사(ordinal)를 통과했습니다.
  - 값이 없는 단위는 회색입니다.
  - 동일 값이 많아 구간이 5개보다 적으면 램프 양 끝을 유지하도록 색을 고릅니다.
- **범례**: 구간은 `[경계값 이상, 다음 경계값 미만)`으로 `step` 식과 같습니다. "← 공급 부족 / 여유 →"와 값 없음 개수를 표시합니다.
- **툴팁**: 자치구·동 이름, 지표 값(없으면 결측 사유), 다른 지표 값을 보여줍니다. 라벨은 LLM이 만든 문자열이므로 HTML 이스케이프 후 넣습니다.
- **테마**: `prefers-color-scheme`을 따르고, 배경지도 스타일이 다르므로 테마가 바뀌면 지도를 다시 만듭니다.
- **MapLibre v6 참고**: 번들러 환경에서는 worker 경로를 직접 지정해야 해서 `maplibre-gl-worker.mjs?worker&url` + `setWorkerUrl`을 씁니다.

`types.ts`는 백엔드 계약을 손으로 옮긴 것입니다. `FinalResponse`나 `WorkflowError`를 바꾸면 함께 고쳐야 합니다.

지도 라이브러리 결정(MapLibre와 카카오맵), 첫 분석 주제에 묶인 문구, 아직 없는 기능과 프론트엔드 담당자가 결정할 사항은 [프론트엔드 담당자 전달 문서](frontend-handoff.md)에 있습니다.

---

## 8. 테스트와 개발 규칙

### 8.1 테스트 구성

| 계층 | 개수 | 범위 | 환경 |
|---|---|---|---|
| Unit | 116 | 도메인 스키마, LLM JSON Schema 변환, Filter SQL 컴파일(주입 시도 포함), Plan Validator 규칙별 음성 케이스, ratio·rank, Result Validator, Adapter 파싱, LLM·임베딩 어댑터 요청 형식(HTTP mock), Executor 핸들러가 Operation 전 종류를 커버하는지, 임베딩 문서 | DB·네트워크 없음 |
| Integration | 40 | 합성 데이터로 GIS Tool 정답 비교(경계선 위 점, 지역 밖 점, EPSG:5179 점 변환, 분모 0·결측), 적재 파이프라인, Workflow 전체(FakeLLM), pgvector 순위·임베딩 동기화·오래된 임베딩 거부, API | Docker DB의 `mapgpt_test`. 연결할 수 없으면 skip |
| E2E (opt-in) | 3 | 실제 데이터 + 실제 LLM·임베딩으로 전달 문서 40번 성공 기준 1~12 확인. 계산 결과를 독립 SQL과 비교 | `pytest -m e2e`. 개발 DB 적재, LLM 설정, `OPENAI_API_KEY` 필요 |

- **FakeLLM**: 단계별 구조화 출력을 미리 정해 두고, 받은 프롬프트를 기록합니다.
- **FakeEmbedder**: 단어 해싱으로 만든 결정론적 1536차원 벡터를 씁니다.
- **합성 데이터**([tests/integration/synthetic.py](../tests/integration/synthetic.py)): 손으로 정답을 계산할 수 있는 서울 10개 단위와 지역 밖 1개 단위입니다.
- "LLM이 올바르게 해석·선택·계획하는가"는 E2E에서만 확인합니다.

```bash
pytest                    # unit + integration
pytest -m e2e             # .env의 LLM으로 실행 (LLM 비용 없이 돌리려면 아래처럼 Ollama 지정)
LLM_PROVIDER=ollama OLLAMA_MODEL=qwen3.5:9b OLLAMA_REASONING_EFFORT=none pytest -m e2e
cd frontend && npm run typecheck
```

### 8.2 개발 규칙 (AGENTS.md 요약)

- 구현 전에 가정을 밝히고, 모호하면 묻습니다. 요청 범위 밖의 기능·추상화는 만들지 않습니다.
- 바꾼 모든 줄이 요청과 직접 연결되게 합니다. 관련 없는 리팩터링이나 포맷 변경은 섞지 않습니다.
- Python 가상환경은 conda `mapgpt`를 씁니다.
- 작업이 끝나면 diff를 검토하고 가능한 검증(테스트, 린트)을 한 뒤 **한국어 커밋 메시지**로 커밋합니다. 요청 하나에 커밋 하나가 기본입니다.
- 포맷과 린트는 `ruff format --line-length 120`, `ruff check --select E,W,F,B --line-length 120`으로 확인해 왔습니다. 프롬프트 문자열의 긴 줄(E501)은 예외로 두고 있으며, 아직 `pyproject.toml`에 ruff 설정이 없습니다.

---

## 9. 로컬 실행 방법

준비물: conda(Python 3.12), Docker, Node.js 20+, OpenAI API 키(임베딩 필수), 서울 열린데이터광장 인증키(어린이집 수집 시), 로컬 LLM을 쓰려면 Ollama(선택)

```bash
conda activate mapgpt
pip install -e ".[dev]"
cp .env.example .env                 # 키를 채움
docker compose up -d --build         # PostgreSQL + PostGIS + pgvector
python -m app.cli init-db
python -m app.cli download
python -m app.cli ingest all         # 끝나면 검색 임베딩도 동기화됨
```

```bash
uvicorn app.api.main:app --reload    # API :8000
cd frontend && npm install && npm run dev   # 화면 http://localhost:5173
```

```bash
python -m app.cli analyze "서울에서 어린이 인구 대비 어린이집이 부족한 행정동을 알려줘."
```

---

## 10. 운영·디버깅 가이드

### 10.1 실패한 실행 추적

화면의 "실행 기록" 링크(`/api/analyses/{run_id}`)나 SQL로 상태 전체를 볼 수 있습니다. 아래 순서로 보면 대부분 원인이 드러납니다.

```sql
SELECT status, llm_model, errors,
       state->'interpreted_query'  AS interpreted,   -- ① 해석이 맞는가
       state->'dataset_search'     AS search,        -- ② 후보와 유사도
       state->'dataset_selection'  AS selection,     -- ② 선택과 근거
       state->'plan_history'       AS plans          -- ③④ 계획 시도와 검증 오류
FROM analysis.run WHERE run_id = '<run_id>';
```

모델별 결과 분포를 볼 때:

```sql
SELECT llm_model, status, errors->0->>'code' AS error, count(*)
FROM analysis.run GROUP BY 1, 2, 3 ORDER BY 1, 2;
```

### 10.2 자주 보는 오류

| 증상 | 원인과 조치 |
|---|---|
| 분석 요청이 503, 메시지에 `OPENAI_API_KEY` | 임베딩용 키가 없음. Ollama로 실행해도 필요 |
| 503, 메시지에 `OLLAMA_MODEL` | `LLM_PROVIDER=ollama`인데 모델이 지정되지 않음 |
| `CATALOG_INDEX_STALE` | 메타데이터가 바뀌었거나 임베딩 모델이 바뀜 → `python -m app.cli embed-catalog` |
| `DATASET_TABLE_MISSING`, `DATASET_EMPTY` | 적재 전 → `init-db`, `download`, `ingest all` |
| `REGION_NOT_SUPPORTED` | 서울 밖 지역이거나, LLM이 지역 단위를 잘못 채움(메시지의 `(단위)`와 `state.interpreted_query` 확인) |
| `UNIT_NOT_SUPPORTED` | 행정동 외 단위(예: 구별) 요청. 현재 경계 데이터는 행정동뿐 |
| `PLAN_INVALID` | `errors[0].issues`와 `plan_history`에서 어떤 규칙에 걸렸는지 확인. 반복되면 프롬프트 규칙 보강 검토 |
| `LLM_FAILED` | API 키·네트워크·모델 이름 확인, Ollama라면 `ollama serve` 실행 여부 확인 |
| Ollama 실행이 매우 느림 | thinking 모델이면 `OLLAMA_REASONING_EFFORT=none` |
| 지도가 비어 있음 | 브라우저 콘솔 확인. 배경지도는 OpenFreeMap 접속이 필요 |

---

## 11. 성능·비용·보안·라이선스

### 11.1 성능 (실측, `analysis.run` 기록 기준)

| 항목 | 값 |
|---|---|
| 전체 실행, `gpt-4o-mini` | 15~21초 (성공 2회) |
| 전체 실행, `qwen3.5:9b` (로컬 Mac, thinking 끔) | 66~194초, 평균 114초 (성공 8회, 계획 재생성 포함) |
| GIS 실행 (Operation 4개, 427개 행정동, 어린이집 3,895곳) | 22~53 ms |
| 해석 단계에서 끝나는 실패 | 약 3초 |

시간 대부분은 LLM 호출입니다. 프론트 dev 프록시 타임아웃은 300초입니다.

### 11.2 비용

- 분석 1건당 LLM 4~5회, 임베딩 1회(검색어)를 호출합니다.
- 카탈로그 임베딩은 Dataset 문서가 바뀔 때만 다시 만듭니다. 적재 통계(feature 수, 기준일)는 문서에 넣지 않으므로 다시 적재해도 임베딩이 바뀌지 않습니다.
- 로컬 검증은 Ollama로 비용 없이 할 수 있습니다. 다만 임베딩은 OpenAI입니다.

### 11.3 보안

- API 키는 `.env`(git 제외)에만 둡니다. 서울 API 키는 로그·예외 메시지에 남기지 않습니다.
- LLM은 SQL을 만들지 않습니다. 이름은 메타데이터로 확인 후 Identifier로, 값은 파라미터로 넣습니다. 분석 SQL은 읽기 전용 트랜잭션에서 실행합니다.
- OpenAI Responses 호출은 `store=False`입니다.
- 화면 툴팁은 LLM이 만든 라벨을 HTML 이스케이프합니다.
- **인증·권한·요청 제한이 없습니다.** 외부에 공개하기 전에 반드시 추가해야 합니다.

### 11.4 데이터 라이선스

- 어린이집 데이터는 공공누리 제4유형이라 **상업적 이용과 변경이 금지**됩니다. 상업 서비스에 쓰려면 이용 조건을 따로 확인해야 합니다.
- 행정동 경계는 CC BY 4.0(출처: 통계청 SGIS), 인구는 이용허락범위 제한이 없습니다.
- 배경지도는 OpenFreeMap(© OpenMapTiles, OpenStreetMap)입니다.

---

## 12. 주요 설계 결정과 이유

| 결정 | 이유 |
|---|---|
| LLM은 계획(JSON)만 만들고 실행은 GIS Tool이 한다 | 재현성·검증 가능성·SQL 주입 차단. 같은 계획이면 같은 결과 |
| Operation은 타입 있는 discriminated union, 필터는 1단계 그룹까지만 | LLM 출력 공간을 좁혀 검증 가능하게 유지. 거대한 GIS DSL은 만들지 않음(전달 문서 39번) |
| 데이터는 PostGIS에 두고 View(메타데이터 + 필터)만 전달 | 큰 데이터를 Python으로 옮기지 않고 SQL 한 번에 계산 |
| 워크플로는 LangGraph `StateGraph`, 상태는 `AgentState` 그대로 | 단계와 분기가 그래프로 드러나 새 단계·분기를 더하기 쉬움. 상태가 곧 Provenance 계약이라 기록 형식이 바뀌지 않고, LangGraph 의존은 `app/workflows`에 한정함(전달 문서 25번). 처음에는 직접 만든 상태 머신이었고 사용자 요청으로 전환함 |
| 계획 재생성은 검증 오류 피드백과 함께 1회 | 작은 모델도 피드백으로 복구되는 경우가 많고, 무한 반복과 비용 폭증을 막음 |
| 해석 직후 지역·단위를 확인 | 지원하지 않는 질문을 LLM 1회 호출로 끝냄. 프롬프트에는 가능한 단위만이 아니라 전체 단위 목록도 보여줘, 모델이 '구별' 요청을 가능한 단위인 '행정동'으로 바꿔버리지 않게 함 |
| 계획이 해석과 다르면 거부 (`PLAN_INTERPRETATION_MISMATCH`) | LLM이 지원 범위로 몰래 바꾸는 것을 결정론적으로 차단 |
| 결측은 0이 아니라 null + 사유, 경계선 위 점은 한 단위에만 | "자료 없음"과 "0"을 구분하고 이중 집계를 막음 |
| 최종 응답은 코드가 조립하고 LLM은 요약만 | 수치·방법·한계의 정확성을 보장하고 환각 범위를 요약 문장으로 한정 |
| 상태 전체를 JSONB로 저장 (`plan_history`, `dataset_search`, `dataset_selection` 포함) | "LLM이 무엇을 보고 무엇을 판단했는가"를 재현·디버깅 |
| GIS 단계는 `REPEATABLE READ, READ ONLY` 트랜잭션 하나 | 단계 사이 데이터 일관성, 쓰기 차단 |
| CRS는 정책이 결정 (지도 4326, 위상 연산은 경계 CRS) | LLM이 CRS를 고르지 않게 함. 거리·면적 연산은 추가될 때 확장 |
| pgvector 후보 검색 + 오래된 임베딩이면 중단 | 전달 문서 33번 구조를 앞당겨 적용(사용자 요청). 임베딩 누락으로 후보가 조용히 빠지는 것을 막음 |
| 임베딩 최신 여부는 메타데이터 해시가 아니라 임베딩 문서 비교 | 다시 적재해 통계만 바뀌면 재임베딩하지 않음 |
| 어린이집 품질 규칙(기본값 좌표·자치구 불일치 제외)을 적재 시 적용 | 실제 데이터의 좌표 오류가 집계를 왜곡함. 제외 건수는 응답의 한계로 공개 |
| 행별 기준일 컬럼을 저장하지 않음 | 실제 LLM이 이를 기준일 필터로 오인해 정상 시설 45곳을 빼는 계획을 만들었음 |

전체 변경 이력과 이유는 [MVP 설계안 부록 D](design/mvp-design.md)에 있습니다.

---

## 13. 현재 한계와 로드맵

### 13.1 현재 한계

- **범위**
  - 지역은 서울, 단위는 행정동, 분석 유형은 1종, Operation은 4종뿐입니다.
  - "강남구의 행정동별 …"처럼 서울 안 일부 지역을 묻는 질문은 지역 계층 해석이 없어 지원하지 않습니다.
- **처리 방식**
  - 분석이 동기 HTTP 요청이라 15초~3분이 걸립니다.
  - 진행 상황 스트리밍, 비동기 Job, 취소 기능이 없습니다.
- **운영**
  - 인증·요청 제한이 없습니다.
  - 마이그레이션 도구가 없습니다. `schema.sql` 재실행은 새 테이블만 만들기 때문에, 기존 테이블 컬럼 변경은 수동으로 처리해야 합니다.
- **개념 검증**: "어린이 = 0~5세" 같은 개념 정의를 계획이 지키는지는 프롬프트에만 의존합니다. 필터 값을 결정론적으로 검증하는 기능(전달 문서 35번 Semantic Analysis Knowledge)은 보류 중입니다.
- **검색**: Dataset이 3개라 pgvector 검색은 아직 순서만 바꿉니다. 유사도 하한(threshold)은 없습니다.
- **데이터 갱신**
  - 인구 파일 링크가 2026-09-30판에 고정되어 있어 월별 갱신은 수동입니다.
  - 어린이집은 `ingest daycare_facility --refresh`로 다시 수집합니다.
- **분석 정책 한계**: 시설 규모(정원·현원)와 경계를 넘는 이용을 반영하지 않습니다(응답의 "한계"에 표시).
- **첫 Use Case에 맞춘 문구**: 다른 단위·의미로 확장할 때 아래를 고쳐야 합니다.
  - 화면: 순위 표의 "행정동", 범례의 "공급 부족 / 여유"
  - 설명: 설명 프롬프트의 "부족한 행정동", `explanation_facts`의 "자치구/행정동" 키
  - 검증: Result Validator 메시지의 "행정동"
- **LLM 비결정성**: 모델마다 실수 양상이 다릅니다. 프롬프트를 바꾸면 실제 모델로 E2E를 확인해야 합니다. 요약 문장 속 수치는 코드로 검증하지 않습니다.

### 13.2 로드맵 (전달 문서 31~37번)

| 단계 | 내용 | 상태 |
|---|---|---|
| 첫 번째 Vertical Slice | 서울 어린이집 공급 부족 분석 | ✅ 완료 (성공 기준 1~12) |
| 1차: 두 번째 Vertical Slice | "지하철역에서 500m 이상 떨어진 지역" — buffer, difference/uncovered_area, spatial_relationship, coverage. Generic Core 재사용성 검증 | 예정 |
| 2차: 접근성 분석 | nearest_distance, network_distance, travel_time, isochrone, service_area. 도로망·Routing Engine 검토 | 예정 |
| 3차: Dataset RAG | 임베딩 → pgvector Top-K → LLM 선택 → Validator | ✅ 후보 검색 구현(사용자 요청으로 앞당김) |
| pgvector 저장 대상 확장 | Analysis Knowledge, 성공한 Analysis Plan 예시, Metric 설명 | 예정 |
| 4차: Semantic Analysis Knowledge | "부족하다" → facility_shortage 같은 개념·지표 매핑(JSON/YAML 또는 DB 테이블) | 예정 (개념 검증 보류 항목과 연결) |
| 5차: Dynamic Dataset Discovery | 검색 → 메타데이터·스키마 확인 → 샘플 → 단위·키·시점 확인 → 품질 검증 → 사용 판정 | 예정 |
| 장기 | MCP, OGC API Processes, Multi-Agent, Raster, Vector Tile, 입지 최적화 등 | 필요성 확인 후 |

---

## 14. 자주 하는 변경: 어디를 고치나

처음 코드를 볼 때는 다음 순서를 권합니다.

1. `domain/`(계약)
2. `workflows/analysis_workflow.py`(흐름)
3. `agents/prompts.py`(LLM에게 주는 것)
4. `validation/`(LLM 출력의 관문)
5. `executor/`·`gis/`(실행)
6. `workflows/response.py`(응답)

| 하고 싶은 일 | 고칠 곳 |
|---|---|
| 새 Dataset 추가 | ① 데이터 확인(라이선스, 기준 시점, 좌표계, 코드 체계, 품질) ② Adapter `data_sources/adapters/<출처>.py` ③ 메타데이터 `catalog/definitions.py` → `TRUSTED_DATASETS` ④ 테이블 `db/schema.sql`(`datasets.<dataset_id>`, geometry면 GiST) ⑤ 적재 함수 `data_sources/ingest.py` ⑥ CLI `ingest` 선택지 `cli.py`(키가 필요하면 `config.py`·`.env.example`) ⑦ Adapter 단위 테스트·적재 통합 테스트 ⑧ `init-db` → `ingest` |
| 출처 교체 (예: 공공데이터포털 API) | 같은 내부 레코드를 돌려주는 새 Adapter, 메타데이터의 `provider`·`source`·`license`, 키 설정 |
| 새 Operation (예: `buffer`) | `domain/operations.py`(union에 추가) → `gis/tools.py`(Tool) → `executor/operation_executor.py`(`HANDLERS`) → `validation/plan_validator.py`(규칙) → `workflows/response.py`(`_method` 문장) → `agents/prompts.py`(Operation 의미) → 테스트(`test_executor_registry`가 핸들러 누락을 잡음) |
| 새 분석 유형 (intent) | `domain/enums.py`(`AnalysisIntent`) → `domain/policies.py`(정책) → `plan_validator.check_policy` → 프롬프트 → 필요하면 화면 문구 |
| 새 개념 정의 (예: 노인 = 65세 이상) | `domain/policies.py`의 `definitions` |
| 검증 규칙 추가 | `validation/plan_validator.py` 또는 `result_validator.py` + 단위 테스트 |
| 새 워크플로 단계 | `domain/enums.py`(`WorkflowStep`) → `workflows/analysis_workflow.py`(단계 함수, `_STEPS`, `_build_graph()`의 엣지) → 화면 단계 이름 `frontend/src/components/ErrorPanel.tsx`(`STEP_NAMES`) |
| LLM 모델 교체 | `.env`의 `LLM_PROVIDER`, `OPENAI_MODEL`, `OLLAMA_MODEL`. 새 공급자는 `llm/`에 어댑터를 추가하고 `factory.py`에 연결 |
| 임베딩 모델 교체 | `OPENAI_EMBEDDING_MODEL` 변경 → `embed-catalog`(모델 변경은 자동 감지). 차원을 바꾸려면 `schema.sql`의 `vector(1536)`과 `EMBEDDING_DIMENSIONS`를 함께 변경 |
| 프롬프트 수정 | `agents/prompts.py` → 실제 모델로 E2E 확인. `$ref` 필드는 스키마 설명이 전달되지 않으니 프롬프트에 적을 것 |
| 지원 CRS 추가 | `gis/crs.py`의 `SUPPORTED_SRIDS` |
| 응답에 필드 추가 | `domain/results.py`(`FinalResponse`) → `workflows/response.py` → `frontend/src/types.ts` → 컴포넌트 |
| 화면 수정 | `frontend/src/components/*`, 색·포맷은 `theme.ts` |

---

## 15. 용어집

| 용어 | 뜻 |
|---|---|
| Vertical Slice | 하나의 실제 질문을 처음부터 끝까지(해석→실행→지도) 동작하게 만든 단위 |
| Trusted Dataset | 사람이 출처·품질·의미를 확인해 등록한 Dataset. 현재 3종 |
| 내부 표준 Dataset | 외부 원본을 Adapter가 정규화해 `datasets` 스키마에 저장한 형태 |
| Adapter | 외부 원본 형식(API, 파일)을 내부 표준 레코드로 바꾸는 모듈 |
| DatasetMetadata | Dataset의 의미·컬럼·공간·시간·출처 정보. LLM, 검증, GIS Tool, 검색이 모두 참조 |
| semantic_type | 컬럼의 의미 유형(예: `administrative_code`, `population`, `latitude`) |
| join key / code_system | 다른 Dataset과 결합할 키와 그 코드 체계(예: 행안부 10자리 행정기관코드) |
| coverage | Dataset이 다루는 지역(예: 서울특별시, sido) |
| intent | 분석 유형. 현재 `supply_demand_gap` |
| region / analysis_unit | 분석할 지역 자체(예: 서울특별시, sido) / 결과를 나눌 공간 단위(예: 행정동, emd) |
| Analysis Plan | LLM이 만드는 실행 계획(JSON). 검증 후에만 실행 |
| Operation | 계획 안의 타입 있는 분석 단계(공간 집계, 집계, 비율, 순위) |
| GIS Tool | Operation을 PostGIS SQL로 실행하는 함수 |
| View | 데이터를 옮기지 않고 메타데이터 + 필터만 담은 Dataset 참조 |
| FilterExpression | 계획 안의 행 조건(조건 또는 1단계 그룹) |
| Plan / Result Validator | 실행 전 계획 검증 / 지도·설명 전 결과 검증 |
| Provenance | 실행의 입력·판단·연산·결과 기록(`analysis.run`, `analysis.result`) |
| Structured Output | LLM이 지정한 JSON Schema에 맞는 JSON만 내도록 하는 기능 |
| Choropleth / 분위(quantile) | 단위별 값을 색으로 칠한 지도 / 값을 개수가 비슷한 구간으로 나누는 방식 |
| CRS / SRID | 좌표계 / 좌표계 번호(예: EPSG:4326 경위도, EPSG:5179 UTM-K) |
| pgvector / 임베딩 | PostgreSQL 벡터 검색 확장 / 텍스트를 의미 벡터로 바꾼 값 |
| null_reason | 값을 계산할 수 없는 이유(`denominator_zero`, `denominator_missing`, `numerator_missing`, `no_matching_records`, `input_null`) |
