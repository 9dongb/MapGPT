# 백엔드 현황과 향후 과제 — 백엔드 담당자 전달 문서

- 작성일: 2026-10-09
- 기준 코드: `main` 브랜치 `7de2885`
- 대상: API, 실행 환경, 배포·운영을 맡을 백엔드 담당자

이 문서는 세 가지를 담는다.

1. 지금 백엔드가 어떻게 구성되어 요청을 처리하는지 (사실)
2. 운영하려면 비어 있는 부분과 개발 쪽 의견 (제안)
3. 백엔드 담당자가 결정해 줄 사항 (결정)

에이전트 내부 동작(질문 해석, 계획, 검증, GIS 실행)은 [에이전트 설계 개요](agent-design-overview.md)에, 데이터 수집·적재는 [데이터 담당자 전달 문서](data-handoff.md)에 있다. 이 문서는 그 바깥을 다룬다. 요청을 받아 에이전트를 실행하고, 결과를 돌려주고, 서비스를 운영하는 부분이다. 권장안은 개발 쪽 의견이며 결정은 담당자가 한다.

## 요약

- **현재:** FastAPI API는 4개이고, 그중 분석 요청(`POST /api/analyses`)이 요청 스레드 안에서 LangGraph 워크플로를 끝까지 실행한다. 분석 1건에 LLM을 4~5번, 임베딩을 1번 호출하고, gpt-4o-mini 기준 15~21초가 걸린다. 실행 기록은 분석이 끝난 뒤 PostgreSQL에 저장한다. Docker로는 DB만 띄우고, API와 화면은 개발 서버로 실행한다.
- **경계:** 백엔드는 `AnalysisWorkflow.run(question)` 호출의 바깥을 맡는 것을 제안한다. API, 실행 방식, 인증, 설정, DB 운영, 배포, 관측, CI가 여기에 든다. 이 함수와 응답 스키마가 에이전트·화면과의 계약이다.
- **비어 있는 것:** 비동기 실행·진행 상황·취소, 타임아웃 정책, 인증·요청 제한·비용 한도, 마이그레이션, 배포(API 컨테이너, 화면 서빙, 리버스 프록시), 로그·지표, CI, Python 의존성 고정.
- **결정 요청:** 10장. 먼저 정할 것은 실행 모델(비동기 여부와 작업 큐), 공개 범위와 인증, 마이그레이션 도구다.

## 목차

1. [용어](#1-용어)
2. [역할 경계와 인터페이스](#2-역할-경계와-인터페이스)
3. [현재 구성](#3-현재-구성)
4. [API 계약](#4-api-계약)
5. [요청 처리와 실행 모델](#5-요청-처리와-실행-모델)
6. [DB와 실행 기록](#6-db와-실행-기록)
7. [보안·운영 현황](#7-보안운영-현황)
8. [과제와 개발 쪽 의견](#8-과제와-개발-쪽-의견)
9. [지켜야 할 계약](#9-지켜야-할-계약)
10. [백엔드 담당자 결정 사항](#10-백엔드-담당자-결정-사항)
11. [참고](#11-참고)

## 1. 용어

| 용어 | 뜻 |
|---|---|
| 워크플로 | 질문 하나를 처리하는 에이전트의 실행 흐름. LangGraph `StateGraph`로 만든 9단계 그래프다 |
| 단계 (`WorkflowStep`) | 그래프의 노드. `interpret_query`, `select_datasets`, `build_analysis_plan`, `validate_plan`, `load_data`, `execute_operations`, `validate_result`, `create_map_layer`, `generate_explanation`. 오류 응답의 `step`과 화면의 단계 이름이 이 값을 쓴다 |
| `AgentState` | 실행 1회의 상태 전체 (질문, 해석, 후보, 계획 시도, 결과, 오류). 그래프의 상태이자 실행 기록의 형식이다 |
| 실행 기록 (Provenance) | `analysis.run`에 저장하는 실행 1회의 기록. 성공·실패와 관계없이 남긴다 (개발 전달 문서 24번) |
| `FinalResponse` | 성공한 분석의 응답. 요약, 지표, 순위, GeoJSON 지도, 방법·가정·한계를 담고 `analysis.result`에 저장한다 |
| `run_id` | 실행 1회의 ID (UUID). 화면의 "실행 기록" 링크와 장애 추적에 쓴다 |

## 2. 역할 경계와 인터페이스

### 2.1 담당 영역 (제안)

팀에서 합의한 분담이 있으면 그에 맞게 고친다.

| 영역 | 담당 | 코드 |
|---|---|---|
| 에이전트: 질문 해석, 데이터 선택, 계획, 검증, GIS 실행, 응답 조립, 프롬프트, LLM 어댑터 | 에이전트 설계 담당 | `app/agents`, `app/llm`, `app/domain`, `app/validation`, `app/gis`, `app/executor`, `app/catalog/catalog.py`, `app/workflows` |
| 데이터: 수집·적재, 카탈로그 메타데이터 | 데이터 담당 | `app/data_sources`, `app/catalog/definitions.py` |
| 백엔드: API, 실행 방식, 인증, 설정, DB 운영(마이그레이션·보존), 배포, 관측, CI | 백엔드 담당 | `app/api`, `app/config.py`, `app/db`, `docker-compose.yml`, `docker/`, 배포·CI 설정 |
| 실행 기록 저장, 운영 CLI | 백엔드 + 에이전트 | `app/repositories/run_repository.py`, `app/cli.py` |
| 화면 | 프론트엔드 담당 | `frontend/` |

### 2.2 인터페이스

백엔드가 에이전트를 부르는 지점은 하나다. API와 CLI의 `analyze` 명령이 모두 이 함수를 부른다.

```python
from app.workflows.analysis_workflow import AnalysisWorkflow

state = AnalysisWorkflow(llm, pool, embedder).run(question)  # -> AgentState
```

- **동기·블로킹:** LLM 호출이 모두 끝날 때까지 돌아오지 않는다(5장).
- **실패도 값으로 돌려준다:** 단계 안에서 난 오류는 예외로 던지지 않고 `state.status == "failed"`와 `state.errors`로 돌려준다. 예외로 올라오는 것은 실행 기록 저장 실패처럼 단계 밖에서 난 오류뿐이다.
- **실행 기록을 스스로 저장한다:** 돌아오기 직전에 `analysis.run`을 저장하고, 성공했으면 `analysis.result`도 저장한다.
- **의존성은 호출하는 쪽이 만든다:**
  - LLM: `create_llm(settings)`. OpenAI 또는 Ollama
  - 임베딩: `create_embedder(settings)`. 항상 OpenAI
  - psycopg 연결 풀
  - 생성 함수는 [app/llm/factory.py](../app/llm/factory.py)에 있다.
- **그래프는 한 번만 컴파일한다:** 모듈을 불러올 때 `ANALYSIS_GRAPH`를 만들어 모든 요청이 함께 쓰고, 요청별 의존성은 LangGraph Runtime context로 넘긴다.

## 3. 현재 구성

### 3.1 기술 스택 (검증 버전)

| 구분 | 사용 기술 |
|---|---|
| 언어·환경 | Python 3.12, conda 환경 `mapgpt` |
| API | FastAPI 0.142 (Starlette 1.7), uvicorn 0.54 |
| 계약·설정 | Pydantic 2.13, pydantic-settings 2.15 |
| DB 드라이버 | psycopg 3.3 + psycopg_pool 3.3. ORM 없이 SQL을 직접 쓴다 |
| 워크플로 | LangGraph 1.2 |
| LLM·임베딩 | OpenAI Python SDK 3.26. Ollama도 OpenAI 호환 API로 호출한다 |
| DB | PostgreSQL 17.6 + PostGIS 3.5.3 + pgvector 0.8.7 (Docker) |
| 화면 | Vite 8, React 19, TypeScript, MapLibre GL 6 |
| 테스트 | pytest, httpx |

### 3.2 백엔드 관련 파일

| 파일 | 내용 |
|---|---|
| [app/api/main.py](../app/api/main.py) | FastAPI 앱, 라우트 4개, 의존성(연결 풀, LLM, 임베딩), 앱 수명 동안 쓰는 연결 풀 |
| [app/api/schemas.py](../app/api/schemas.py) | 요청·응답 모델 |
| [app/config.py](../app/config.py) | 설정 (`.env` → `Settings`) |
| [app/db/schema.sql](../app/db/schema.sql), [app/db/\_\_init\_\_.py](../app/db/__init__.py) | DDL과 적용 함수 |
| [app/repositories/run_repository.py](../app/repositories/run_repository.py) | 실행 기록 저장·조회 |
| [app/workflows/analysis_workflow.py](../app/workflows/analysis_workflow.py) | LangGraph 그래프와 실행기 |
| [app/cli.py](../app/cli.py) | 운영 CLI (`init-db`, `download`, `ingest`, `embed-catalog`, `analyze`) |
| [docker-compose.yml](../docker-compose.yml), [docker/postgres/Dockerfile](../docker/postgres/Dockerfile) | DB 컨테이너 (PostGIS 이미지에 pgvector 추가) |
| [pyproject.toml](../pyproject.toml) | Python 의존성 (하한만 지정) |
| [.env.example](../.env.example) | 설정 예시 |
| [frontend/vite.config.ts](../frontend/vite.config.ts) | 화면 개발 서버, `/api` 프록시 |

### 3.3 실행 방법

```bash
conda activate mapgpt
pip install -e ".[dev]"
cp .env.example .env                 # 키를 채움
docker compose up -d --build         # PostgreSQL + PostGIS + pgvector
python -m app.cli init-db
python -m app.cli download
python -m app.cli ingest all         # 끝나면 검색 임베딩도 동기화
```

```bash
uvicorn app.api.main:app --reload    # API :8000, API 문서 :8000/docs
```

```bash
cd frontend && npm install && npm run dev   # 화면 :5173, /api는 :8000으로 프록시
```

FastAPI가 만드는 API 문서(`/docs`, `/redoc`, `/openapi.json`)를 그대로 쓸 수 있다.

### 3.4 설정

pydantic-settings가 저장소 루트의 `.env`를 읽고, 같은 이름의 환경 변수가 있으면 환경 변수를 우선한다. 설정은 앱을 불러올 때 한 번 읽는다(`get_settings()` 캐시).

| 변수 | 기본값 | 설명 |
|---|---|---|
| `DATABASE_URL` | `postgresql://mapgpt:mapgpt@localhost:5432/mapgpt` | DB 주소 |
| `LLM_PROVIDER` | `openai` | `openai` 또는 `ollama` |
| `OPENAI_API_KEY` | 없음 | OpenAI LLM과 검색 임베딩에 함께 쓴다. Ollama를 써도 임베딩 때문에 필요하다 |
| `OPENAI_MODEL` | `gpt-6.1-sol` | OpenAI LLM 모델 |
| `OPENAI_EMBEDDING_MODEL` | `text-embedding-3-small` | 검색 임베딩 모델 |
| `OLLAMA_BASE_URL`, `OLLAMA_MODEL`, `OLLAMA_REASONING_EFFORT` | `http://localhost:11434/v1`, 없음, 없음 | 로컬 LLM |
| `SEOUL_OPEN_API_KEY` | 없음 | 어린이집 수집. 적재 CLI에서만 쓴다 |
| `RAW_DATA_DIR` | `data/raw` | 원본 파일 위치. 적재 CLI에서만 쓴다 |

테스트 DB는 `.env`가 아니라 셸 환경 변수 `TEST_DATABASE_URL`로 정한다. 기본값은 로컬 `mapgpt_test`다.

### 3.5 테스트

| 종류 | 개수 | 내용 | 환경 |
|---|---|---|---|
| Unit | 116 | 스키마, 검증 규칙, LLM·임베딩 어댑터 요청 형식(HTTP mock) 등 | DB·네트워크 없음 |
| Integration | 40 | GIS 정답 비교, 적재, 워크플로 전체(FakeLLM·FakeEmbedder), API(`TestClient`) | Docker DB의 `mapgpt_test`. 세션마다 스키마를 새로 만들고, 테스트마다 테이블을 비운다 |
| E2E | 3 | 실제 데이터와 실제 LLM·임베딩으로 성공 기준 확인 (`pytest -m e2e`) | 개발 DB 적재, LLM 설정, `OPENAI_API_KEY` |

API 테스트([tests/integration/test_api.py](../tests/integration/test_api.py))는 `dependency_overrides`로 `get_llm`과 `get_embedder`를 가짜로 바꿔서, 실제 LLM 없이 돈다. CI는 아직 없다.

## 4. API 계약

| Method | Path | 요청 | 응답 |
|---|---|---|---|
| `POST` | `/api/analyses` | `{"question": "..."}` (1~500자) | 200 `{run_id, status, result, errors}`. 분석이 실패해도 200 + `status: "failed"`. 형식 오류 422, LLM·임베딩 설정 누락 503, 단계 밖 예외 500 |
| `GET` | `/api/analyses/{run_id}` | `run_id`는 UUID | 200 `{run_id, status, question, provenance, result}`. 없으면 404 |
| `GET` | `/api/datasets` | 없음 | 200 `DatasetMetadata[]` (카탈로그) |
| `GET` | `/api/health` | 없음 | 200 `{status, database, llm_provider, llm_model, embedding_model}`. `status`는 `ok` 또는 `degraded` |

- **실행 기록 조회:** `provenance`는 `AgentState`에서 지도와 최종 응답을 뺀 것이다. `result`는 `FinalResponse`이고, 실패한 실행이면 null이다. 이 엔드포인트에는 `response_model`이 없어 OpenAPI 문서의 스키마가 느슨하다.
- **헬스 체크:** DB 연결만 실제로 확인하고, LLM·임베딩은 설정값만 보여준다.
- **응답 크기:** 성공 응답은 행정동 427개의 GeoJSON을 포함해 JSON으로 약 590KB다. 지금은 압축하지 않는다.
- **오류 형식:**
  - `errors[]`의 각 항목은 `{step, code, message, issues[]}`이다. 화면은 `step`을 단계 이름으로 바꿔 보여준다([ErrorPanel.tsx](../frontend/src/components/ErrorPanel.tsx)).
  - 오류 코드 목록은 에이전트 설계 개요 3.7절, 증상별 조치는 10.2절에 있다.
  - 성공 응답의 전체 예시는 같은 문서 6.3절에 있다.
- **화면과의 짝:**
  - 화면의 타입([frontend/src/types.ts](../frontend/src/types.ts))은 `app/api/schemas.py`, `app/domain/results.py`, `app/domain/state.py`를 손으로 옮긴 것이다.
  - 코드 생성을 쓰지 않으므로, 응답 형식을 바꾸면 화면 타입도 함께 바꿔야 한다.
- **화면 요청 방식:**
  - 화면은 `POST`를 한 번 보내고 응답을 기다린다.
  - 진행 표시는 경과 시간과 고정된 단계 목록일 뿐, 실제 진행 상황이 아니다.
  - 개발 서버 프록시의 타임아웃은 300초다.

## 5. 요청 처리와 실행 모델

### 5.1 분석 요청 하나의 처리

1. FastAPI가 요청 본문을 검증한다. 실패하면 422.
2. 의존성을 만든다.
   - 연결 풀: 앱 수명 동안 하나(최소 1, 최대 5)를 함께 쓴다.
   - LLM과 임베딩 클라이언트: **요청마다 새로 만든다.**
   - 설정이 없으면 503.
3. 엔드포인트가 동기 함수라 Starlette 스레드풀에서 실행된다. 스레드풀은 anyio 기본값인 40개이고 다른 동기 처리와 함께 쓴다. 그래서 프로세스 하나가 동시에 처리하는 분석은 최대 약 40건이고, 나머지는 스레드를 기다린다.
4. `AnalysisWorkflow.run`이 그래프를 실행한다.
   - LLM: 해석, 선택, 계획(재생성하면 2번), 설명으로 4~5번 호출한다.
   - 임베딩: 검색어로 1번 호출한다.
5. 실행 기록을 한 트랜잭션으로 저장하고(성공이면 결과도), 응답을 돌려준다.

### 5.2 DB 연결 사용

| 시점 | 연결 | 붙잡는 시간 |
|---|---|---|
| 해석 전 카탈로그 조회 | 풀에서 1개 | 짧음 |
| 후보 검색 (임베딩 최신 여부 확인, 유사도 검색) | 풀에서 1개씩 2번 | 짧음 |
| GIS 단계 (`load_data` ~ `create_map_layer`) | 1개. `REPEATABLE READ, READ ONLY` 트랜잭션 | 개발 DB 실측 39~58ms (행정동 427개, 어린이집 3,895곳) |
| 실행 기록 저장 | 1개 | 짧음 |

LLM을 기다리는 동안에는 연결을 붙잡지 않는다. 그래서 동시 처리량은 DB 풀(5)보다 스레드 수, LLM 응답 시간, LLM 호출 한도에서 먼저 막힌다. 풀에서 연결을 기다리는 최대 시간은 psycopg_pool 기본값인 30초다.

### 5.3 소요 시간

개발 DB의 실행 기록 기준이며, 표본이 적다.

| 경우 | 시간 |
|---|---|
| gpt-4o-mini, 성공 (3건) | 14.8~20.7초, 중앙값 16.8초 |
| gpt-4o-mini, 해석 단계에서 실패 (3건) | 2.6~3.8초 |
| qwen3.5:9b 로컬, 성공 (9건) | 66~194초, 중앙값 120초 |
| GIS 단계 전체 | 39~58ms |

시간의 대부분은 LLM 호출이다.

### 5.4 타임아웃과 재시도

- API 수준의 분석 시간 제한은 없다.
- LLM·임베딩 호출은 OpenAI SDK 기본값을 쓴다. 연결 5초, 읽기 600초, 재시도 2회다. 호출 하나가 최악의 경우 10분씩 3번까지 걸릴 수 있다.
- 화면 개발 서버의 프록시는 300초에 연결을 끊는다. 끊겨도 서버는 분석을 끝까지 실행하고 기록을 남기지만, 화면은 결과를 받지 못한다.
- 취소 기능은 없다.

### 5.5 진행 상황을 내보낼 수 있는 지점

그래프의 각 단계가 LangGraph 노드다. 그래서 `ANALYSIS_GRAPH.stream(..., stream_mode="updates")`를 쓰면 단계가 끝날 때마다 이벤트를 받을 수 있다.

지금 `run()`은 `invoke`로 끝까지 실행한다. 진행 상황을 화면에 보내려면 에이전트 쪽에 스트리밍용 실행 함수를 추가해야 하므로, 에이전트 담당과 협의가 필요하다. 그래프 구조는 `ANALYSIS_GRAPH.get_graph().draw_mermaid()`로 그려 볼 수 있다.

## 6. DB와 실행 기록

전체 구조와 테이블 관계도는 [데이터 담당자 전달 문서 2장](data-handoff.md#2-현재-db-구조)에 있다. 백엔드가 직접 다루는 것은 `analysis` 스키마다.

| 테이블 | 컬럼 | 비고 |
|---|---|---|
| `analysis.run` | `run_id` PK, `question`, `status`, `analysis_plan`, `datasets`(ID·기준 시점), `operations`, `crs`, `result_id`, `llm_provider`, `llm_model`, `errors`, `state`(지도·최종 응답을 뺀 `AgentState`), `started_at`, `finished_at` | 모든 실행. 인덱스는 PK뿐 |
| `analysis.result` | `result_id` PK, `run_id` FK, `response`(GeoJSON을 포함한 `FinalResponse`), `created_at` | 성공한 실행만. 인덱스는 PK뿐(`run_id`에도 없음). 1건의 저장 크기는 평균 약 217KB (JSON 텍스트 594KB, TOAST 압축) |

특징은 다음과 같다.

- **끝난 뒤 한 번 저장한다:**
  - 실행 중에는 행이 없다. `running` 상태를 저장하지 않고, 저장은 INSERT뿐이다.
  - 실행 도중 프로세스가 죽으면 기록이 남지 않는다.
  - 비동기 실행으로 바꾸려면 시작할 때 행을 만들고 끝날 때 갱신하도록 바꿔야 한다.
- **보존 정책이 없다:** 결과 1건이 약 217KB라서 1만 건이면 약 2GB다.
- **사용자 구분이 없다:** 인증을 붙이면 실행 기록에 사용자 식별자가 필요하다.
- **조회용 인덱스가 없다:** 실행 기록 조회(`GET /api/analyses/{run_id}`)는 `analysis.result`를 `run_id`로 찾는데 인덱스가 없다. 실행 목록이나 통계를 보려면 `started_at`, `status` 등에도 인덱스가 필요하다.
- **마이그레이션 도구가 없다:**
  - `schema.sql`은 `CREATE ... IF NOT EXISTS`라 새 테이블만 만들고, 기존 테이블의 컬럼 변경은 반영하지 못한다.
  - 검색 임베딩 테이블의 구조를 바꿀 때 테이블을 직접 지우고 다시 만든 적이 있다.
- **확장:** `postgis`와 `vector`가 필요하다. 관리형 DB를 쓰면 두 확장의 지원 여부와 버전을 확인해야 한다.
- **계정:** compose의 DB 계정(`mapgpt`/`mapgpt`)은 개발용이다.

DB에 쓰는 경로는 셋이다.

- 적재 CLI: `datasets.*`, `catalog.dataset`
- 임베딩 동기화: `catalog.dataset_embedding`
- 분석 실행 기록: `analysis.*`

API 요청은 `datasets`와 `catalog`를 읽기만 한다. 현재 개발 DB 크기는 약 27MB다.

## 7. 보안·운영 현황

| 항목 | 현재 |
|---|---|
| 인증·권한 | 없음 |
| 요청 제한·비용 한도 | 없음. 분석 1건이 LLM 4~5회와 임베딩 1회를 호출한다 |
| 비밀 | `.env`(git 제외)의 `OPENAI_API_KEY`, `SEOUL_OPEN_API_KEY`. 서버에서만 쓰고 화면에는 내려가지 않는다. 서울 OpenAPI는 `http` 주소의 경로에 인증키를 넣어 호출하므로, 키가 암호화되지 않은 채 전송된다 |
| CORS | 설정 없음. 개발 중에는 Vite 프록시로 같은 출처에서 호출한다 |
| 압축 | 없음. 성공 응답은 약 590KB다 |
| 로그 | 앱 로그 설정이 없다. 예상하지 못한 예외(`INTERNAL_ERROR`)만 `logger.exception`으로 남는데, 설정이 없어 파이썬 기본 처리로 stderr에 출력된다. 접근 로그는 uvicorn 기본값이다 |
| 지표·알림 | 없음. 실행 기록의 시작·종료 시각, 모델, 오류 코드가 사실상 유일한 운영 데이터다 |
| 헬스 체크 | `/api/health`. DB 연결만 확인한다 |
| SQL 안전성 | LLM은 SQL을 만들지 않는다. 테이블·컬럼 이름은 메타데이터로 확인한 뒤 `Identifier`로, 값은 파라미터로 넣는다. 분석 SQL은 읽기 전용 트랜잭션에서 실행한다 |
| LLM 데이터 보존 | OpenAI Responses 호출은 `store=False`로 보낸다 |
| 배포 | 없음. compose에는 DB만 있고, API와 화면은 개발 서버로 실행한다. 화면 빌드 결과(`npm run build` → `frontend/dist`)를 서빙하는 곳도 없다 |
| CI | 없음. 린트·포맷은 `pyproject.toml`의 ruff 설정만 있다 |
| 의존성 고정 | Python은 `pyproject.toml`에 하한만 있고 lock 파일이 없다. 화면은 `package-lock.json`이 있다. LangGraph를 설치할 때 의존성 제약 때문에 `websockets`가 17.2에서 16.1.1로 내려간 적이 있다 |

## 8. 과제와 개발 쪽 의견

### 8.1 비동기 실행과 진행 상황 (먼저)

지금의 문제는 다음과 같다.
- 15초에서 3분 걸리는 동기 요청이다.
- 연결이 끊겨도 서버는 계속 실행하고, 화면은 결과를 잃는다.
- 진행 상황과 취소가 없고, 실행 중에는 기록도 없다.

권장 구조는 다음과 같다.

```text
POST /api/analyses              → 실행 기록을 running으로 만들고 202 + run_id
작업자                          → AnalysisWorkflow 실행, 단계마다 진행 상황 기록, 끝나면 갱신
GET  /api/analyses/{run_id}     → 상태·결과 조회 (폴링)
GET  /api/analyses/{run_id}/events → 단계 이벤트 (SSE, 선택)
```

- **큐:**
  - 이미 있는 PostgreSQL로 시작하는 것을 권한다. `SELECT ... FOR UPDATE SKIP LOCKED`로 작업을 가져가면 인프라를 늘리지 않고, 서버가 재시작돼도 작업이 남는다.
  - 처리량이 커지면 Redis 기반 큐(Celery, RQ, Arq 등)를 검토한다.
  - FastAPI `BackgroundTasks`는 프로세스와 함께 작업이 사라지므로 권하지 않는다.
- **에이전트 쪽 변경과 협의:** 단계 이벤트는 LangGraph `stream`으로 받을 수 있다(5.5절). 다만 에이전트 쪽에 두 가지가 필요하므로 에이전트 담당과 함께 진행한다.
  - 스트리밍 실행 함수
  - 시작할 때 `running`으로 기록하고 끝날 때 갱신하는 저장 방식
- **취소:** 단계 사이에서 취소 여부를 확인하는 방식이 현실적이다. 진행 중인 LLM 호출은 바로 끊기 어렵다.

### 8.2 타임아웃·재시도 정책 (먼저)

- LLM·임베딩 호출마다 타임아웃과 재시도 횟수를 명시한다. 지금은 SDK 기본값(읽기 600초, 재시도 2회)이다.
- 분석 전체의 시간 예산을 정하고, 넘으면 실패로 기록한다.
- 리버스 프록시와 화면의 타임아웃을 이 예산에 맞춘다. 비동기로 바꾸면 요청 자체는 짧아진다.

### 8.3 인증·요청 제한·비용 한도 (외부 공개 전 필수)

- 공개 범위에 따라 인증 방식을 정한다. 내부 전용이면 리버스 프록시 수준의 접근 제한으로도 충분할 수 있다.
- 사용자별 요청 제한과 일일 비용 한도를 둔다. 분석 1건의 호출 수가 거의 정해져 있어(LLM 4~5회, 임베딩 1회) 건수로 비용을 묶기 쉽다.
- 실행 기록에 사용자 식별자를 넣는다.

### 8.4 DB 마이그레이션 (데이터 담당 D9와 함께)

- 데이터 담당이 저장 구조(계열별 정규 스키마, 부가 컬럼, 이력)를 바꿀 예정이라, 그 전에 도구가 있어야 한다.
- 코드가 ORM 없이 SQL을 직접 쓰므로 SQL 파일 기반 도구(dbmate, yoyo-migrations 등)가 잘 맞는다. Alembic도 쓸 수 있지만 SQLAlchemy가 함께 필요하다.
- 지금의 `schema.sql`을 첫 마이그레이션으로 삼고, 테스트 DB도 같은 마이그레이션으로 만든다.

### 8.5 배포

- **API 컨테이너:**
  - Python 3.12 이미지에 `pip install .`을 하고 `uvicorn app.api.main:app`으로 실행한다.
  - 여러 프로세스(`--workers`)로 띄우면 프로세스마다 연결 풀(최대 5)이 생기므로, DB 최대 연결 수와 맞춘다.
- **화면:**
  - `npm run build` 결과를 리버스 프록시(nginx, Caddy 등)가 서빙하고, `/api`를 API로 넘긴다.
  - 같은 출처가 되어 CORS가 필요 없고, 압축과 타임아웃도 여기서 설정한다.
- **DB:** compose를 그대로 쓰거나 관리형 DB를 쓴다. 관리형이면 PostGIS·pgvector 지원을 확인한다.
- **OpenAI 키:** 운영 환경에 필요하다. LLM을 Ollama로 해도 임베딩은 OpenAI다.
- **적재 CLI 실행 환경:** `ingest`와 `embed-catalog`를 실행할 곳도 필요하다(8.8절).

### 8.6 관측

- `run_id`를 넣은 구조화 로그를 남긴다.
- 단계별 소요 시간, LLM 호출 수, 토큰·비용을 기록한다. 지금 실행 기록에는 전체 시작·종료 시각만 있다. 단계별 시간은 LangGraph 이벤트로 얻을 수 있다.
- 오류 코드별로 집계하고 알림을 둔다 (예: `LLM_FAILED`, `INTERNAL_ERROR` 급증).

### 8.7 CI와 의존성 고정

- unit·integration 테스트를 CI에서 돌린다. integration은 PostGIS·pgvector DB가 필요하므로 `docker/postgres` 이미지를 서비스로 띄운다.
- E2E는 실제 LLM 키가 필요하므로 수동으로 돌리거나 별도 일정으로 돌린다.
- Python lock 파일(uv, pip-tools 등)을 추가하고, CI에서 `ruff check app tests`와 `ruff format --check app tests`도 돌린다.

### 8.8 적재 작업 실행 환경 (데이터 담당 D18·D23과 함께)

- 지금 적재와 임베딩 동기화는 사람이 CLI로 실행한다. 데이터 담당이 갱신 주기와 도구를 정하면, 백엔드가 스케줄 실행 환경과 키 관리를 제공한다.
- 메타데이터를 바꾼 뒤 `embed-catalog`를 하지 않으면 분석이 `CATALOG_INDEX_STALE`로 멈춘다. 그래서 임베딩 동기화를 적재 작업의 마지막 단계로 묶는다. 지금도 `ingest`가 끝에 자동으로 실행한다.

### 8.9 바로 개선할 수 있는 것

작고 위험이 낮아 먼저 해도 되는 것이다.

- **클라이언트 재사용:** LLM·임베딩 클라이언트를 요청마다 만들지 않고, 앱 시작 때 한 번 만든다.
- **응답 압축:** `GZipMiddleware`나 리버스 프록시로 압축한다. DB 저장 압축만으로도 594KB가 217KB로 줄어든다.
- **타임아웃 명시:** OpenAI 호출의 타임아웃과 재시도 횟수를 명시한다.
- **조회 인덱스:** `analysis.result(run_id)`와 `analysis.run(started_at)`에 인덱스를 둔다.

## 9. 지켜야 할 계약

1. **인터페이스:** `AnalysisWorkflow(llm, pool, embedder).run(question) -> AgentState`. 바꾸려면 에이전트 담당과 협의한다.
2. **응답 스키마:** `AnalysisResponse`, `FinalResponse`, `WorkflowError`는 화면 타입과 짝이다. 바꾸면 화면도 함께 바꾼다.
3. **실패 표현:** 분석 실패는 HTTP 오류가 아니라 `status: "failed"`와 `errors[]`(`step`, `code`, `message`, `issues`)로 돌려준다. 비동기로 바꿔도 이 형태는 유지하는 것을 권한다.
4. **실행 기록:** 성공·실패와 관계없이 모든 실행을 남긴다(개발 전달 문서 24번). `state`는 실패 원인 추적에 쓰이므로 임의로 줄이지 않는다.
5. **SQL 안전성:** LLM이 만든 값은 SQL 문자열에 직접 들어가지 않는다. 분석 SQL은 읽기 전용 트랜잭션에서 실행한다. 새 경로를 추가할 때도 지킨다.
6. **프레임워크 경계:** LangGraph는 `app/workflows`에서만 쓴다. Domain·GIS·검증 계층은 LangGraph를 모른다(개발 전달 문서 25번).
7. **임베딩:** `LLM_PROVIDER`와 관계없이 OpenAI 임베딩을 쓴다. 운영 환경에 `OPENAI_API_KEY`가 있어야 하고, 카탈로그 메타데이터가 바뀌면 `embed-catalog`가 필요하다.

## 10. 백엔드 담당자 결정 사항

"우선"에 "먼저"라고 표시한 항목은 다음 개발을 시작하기 전에 정해야 하는 것이다. 권장은 개발 쪽 의견이다.

| # | 결정 사항 | 선택지 | 권장 | 우선 |
|---|---|---|---|---|
| B1 | 실행 모델 | 동기 유지(현재) / 비동기 작업 + 폴링 / 비동기 작업 + SSE | 비동기 작업으로 바꾸고, 진행 상황은 SSE로 보낸다. 폴링으로 먼저 시작해도 된다 | 먼저 |
| B2 | 작업 큐 | `BackgroundTasks` / PostgreSQL 기반 / Redis 기반(Celery, RQ, Arq 등) | PostgreSQL 기반으로 시작한다 | 먼저 |
| B3 | 공개 범위와 인증 | 내부 전용 / 팀 로그인 / 외부 공개 | 공개 범위를 먼저 정한다. 외부에 공개하면 인증과 요청 제한이 필수다 | 먼저 |
| B4 | 마이그레이션 도구 | 수동(현재) / SQL 파일 기반 / Alembic | SQL 파일 기반. 데이터 담당 D9와 함께 정한다 | 먼저 |
| B5 | 타임아웃·재시도 | SDK 기본(현재) / 호출별 명시 + 전체 예산 | 호출별 타임아웃·재시도와 분석 전체 시간 예산을 정하고 프록시와 맞춘다 | |
| B6 | 요청 제한·비용 한도 | 없음(현재) / 사용자·IP별 제한 / 일일 비용 한도 | 사용자별 제한과 일일 비용 한도를 함께 둔다 | |
| B7 | 배포 형태 | 단일 서버 compose / 컨테이너 플랫폼 | API·화면·DB를 compose로 묶어 시작하고, 필요할 때 옮긴다 | |
| B8 | 화면 서빙 | 리버스 프록시로 같은 출처 / CORS 허용 | 리버스 프록시. 압축과 타임아웃도 여기서 설정한다 | |
| B9 | DB 운영 | compose 볼륨(현재) / 관리형 DB | 운영은 백업이 있는 구성으로 한다. 관리형이면 PostGIS·pgvector 지원을 확인한다 | |
| B10 | 비밀 관리 | `.env`(현재) / 비밀 저장소 | 비밀 저장소. 데이터 담당 D22와 함께 정한다 | |
| B11 | 로그·지표 | 없음(현재) / 구조화 로그 + 지표 | `run_id`를 넣은 구조화 로그, 단계별 시간·LLM 호출·비용 지표 | |
| B12 | 실행 기록 보존 | 무기한(현재) / 기간 제한 | 결과(GeoJSON 포함)는 보존 기간을 두고, 실행 기록은 오래 보존한다 | |
| B13 | CI와 의존성 고정 | 없음(현재) / CI + lock 파일 | unit·integration을 DB 서비스와 함께 CI에서 돌리고, Python lock 파일을 둔다 | |
| B14 | 적재 작업 실행 | 수동 CLI(현재) / 스케줄러 | 데이터 담당 D18·D23 결정에 맞춰 실행 환경을 제공한다 | |

## 11. 참고

### 11.1 코드 위치

| 내용 | 위치 |
|---|---|
| API | [app/api/main.py](../app/api/main.py), [app/api/schemas.py](../app/api/schemas.py) |
| 설정 | [app/config.py](../app/config.py), [.env.example](../.env.example) |
| LLM·임베딩 생성 | [app/llm/factory.py](../app/llm/factory.py), [app/llm/openai_llm.py](../app/llm/openai_llm.py), [app/llm/ollama_llm.py](../app/llm/ollama_llm.py), [app/llm/embeddings.py](../app/llm/embeddings.py) |
| 워크플로 | [app/workflows/analysis_workflow.py](../app/workflows/analysis_workflow.py) |
| 응답·상태 모델 | [app/domain/results.py](../app/domain/results.py), [app/domain/state.py](../app/domain/state.py) |
| 실행 기록 | [app/repositories/run_repository.py](../app/repositories/run_repository.py) |
| DB 스키마 | [app/db/schema.sql](../app/db/schema.sql) |
| DB 이미지 | [docker/postgres/Dockerfile](../docker/postgres/Dockerfile), [docker-compose.yml](../docker-compose.yml) |
| CLI | [app/cli.py](../app/cli.py) |
| API 테스트 | [tests/integration/test_api.py](../tests/integration/test_api.py) |
| 화면의 API 호출·타입 | [frontend/src/api.ts](../frontend/src/api.ts), [frontend/src/types.ts](../frontend/src/types.ts) |

### 11.2 관련 문서

- [에이전트 설계 개요](agent-design-overview.md): 전체 구조, 단계별 동작, 오류 코드, 디버깅
- [데이터 담당자 전달 문서](data-handoff.md): DB 구조와 관계도, 적재 방식, 데이터 결정 사항 D1~D24
- [프론트엔드 담당자 전달 문서](frontend-handoff.md): 화면이 쓰는 API, 진행 상황 표시(F3), 결과 URL(F4), 타입 동기화(F10)
- [설계 문서](design/mvp-design.md)
- [개발 전달 문서](공간%20분석%20AI%20Agent%20개발%20전달%20문서.md): 원 요구사항. Provenance는 24번, 워크플로는 25번, 백엔드 기술 방향은 26번
