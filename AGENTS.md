# AGENT.md

Behavioral guidelines to reduce common LLM coding mistakes. Merge with project-specific instructions as needed.

**Tradeoff:** These guidelines bias toward caution over speed. For trivial tasks, use judgment.

## 1. Think Before Coding

**Don't assume. Don't hide confusion. Surface tradeoffs.**

Before implementing:
- State your assumptions explicitly. If uncertain, ask.
- If multiple interpretations exist, present them - don't pick silently.
- If a simpler approach exists, say so. Push back when warranted.
- If something is unclear, stop. Name what's confusing. Ask.

## 2. Simplicity First

**Minimum code that solves the problem. Nothing speculative.**

- No features beyond what was asked.
- No abstractions for single-use code.
- No "flexibility" or "configurability" that wasn't requested.
- No error handling for impossible scenarios.
- If you write 200 lines and it could be 50, rewrite it.

Ask yourself: "Would a senior engineer say this is overcomplicated?" If yes, simplify.

## 3. Surgical Changes

**Touch only what you must. Clean up only your own mess.**

When editing existing code:
- Don't "improve" adjacent code, comments, or formatting.
- Don't refactor things that aren't broken.
- Match existing style, even if you'd do it differently.
- If you notice unrelated dead code, mention it - don't delete it.

When your changes create orphans:
- Remove imports/variables/functions that YOUR changes made unused.
- Don't remove pre-existing dead code unless asked.

The test: Every changed line should trace directly to the user's request.

## 4. Goal-Driven Execution

**Define success criteria. Loop until verified.**

Transform tasks into verifiable goals:
- "Add validation" → "Write tests for invalid inputs, then make them pass"
- "Fix the bug" → "Write a test that reproduces it, then make it pass"
- "Refactor X" → "Ensure tests pass before and after"

For multi-step tasks, state a brief plan:
```
1. [Step] → verify: [check]
2. [Step] → verify: [check]
3. [Step] → verify: [check]
```

Strong success criteria let you loop independently. Weak criteria ("make it work") require constant clarification.

---

**These guidelines are working if:** fewer unnecessary changes in diffs, fewer rewrites due to overcomplication, and clarifying questions come before implementation rather than after mistakes.

## 5. 가상환경 사용

**가상환경은 conda 환경을 사용하세요.**

가상환경명: mapgpt

## 6. 작업 완료 시 커밋 생성

**변경 사항을 검토하고, 가능한 검증을 수행한 뒤 하나의 커밋을 생성한다.**

코딩 작업이 완료된 경우:
- 커밋 전에 최종 diff를 검토한다.
- 가능한 경우 관련 테스트나 린트 명령을 실행한다.
- 검증 결과를 사용자에게 요약한다.
- 완료된 작업에 대해 하나의 커밋을 생성한다.

커밋 단위:
- 기본적으로 하나의 사용자 요청에서 발생한 변경은 하나의 커밋으로 정리한다.
- 단, 서로 독립적으로 이해되거나 되돌릴 수 있는 변경이 명확하고, 각각이 별도의 검증 가능한 목적을 가진 경우에는 논리적 단위별로 커밋을 나눌 수 있다.
- 단순한 구현 변경과 그에 필요한 테스트 추가는 같은 논리적 변경으로 보고 하나의 커밋에 포함한다.
- 리팩터링과 기능 변경은 가능한 경우 분리한다.
- 포맷 변경과 기능 변경은 가능한 경우 분리한다.
- 사용자가 하나의 커밋을 명시적으로 요청한 경우에는 가능한 한 하나의 커밋으로 정리한다.
- 사용자가 커밋 분리를 명시적으로 요청한 경우에는 요청한 기준에 따라 커밋을 나눈다.

커밋 규칙:
- 구현, 버그 수정, 리팩터링, 테스트 추가 등 코드 변경이 발생한 경우 커밋을 생성한다.
- 커밋 메시지는 변경 내용을 명확히 설명하는 한국어 문장으로 작성한다.
- 여러 독립적인 변경이 포함되었더라도, 사용자가 별도로 요청하지 않는 한 최종적으로 하나의 커밋으로 정리한다.
- 커밋을 만들 수 없는 상황이라면 그 이유를 명확히 설명하고, 커밋하지 않은 변경 사항을 요약한다.

커밋 전 확인:
- `git diff`를 확인하여 의도하지 않은 변경이 포함되지 않았는지 점검한다.
- 작업 과정에서 새로 발생한 미사용 import, 변수, 함수는 제거한다.
- 요청과 무관한 정리, 리팩터링, 포맷 변경은 포함하지 않는다.

## 7. 프로젝트 개요

**MapGPT는 자연어 공간 분석 질문을 LLM이 구조화된 분석 계획(`AnalysisPlan` JSON)으로 바꾸고, 코드가 그 계획을 검증한 뒤 PostGIS에서 실행해 지도·순위·설명으로 돌려주는 AI Agent다.**

- 현재 범위: 서울특별시, 행정동 단위, 분석 유형 1종(인구 대비 시설 공급 부족). 첫 Use Case는 어린이집이다.
- 스택: Python 3.12, FastAPI, Pydantic v2, psycopg 3, LangGraph, OpenAI·Ollama, PostgreSQL 17 + PostGIS + pgvector(Docker), React + TypeScript + Vite + MapLibre.
- 원 요구사항은 `docs/공간 분석 AI Agent 개발 전달 문서.md`다. 요구사항과 다르게 구현하려면 사용자와 합의하고 `docs/design/mvp-design.md` 부록 D에 기록한다.

## 8. 구조와 경계 규칙

| 경로 | 역할 |
|---|---|
| `app/domain` | 핵심 계약(Pydantic 모델, Enum, 분석 정책). I/O 없음 |
| `app/agents` | LLM 단계별 프롬프트와 호출 |
| `app/llm` | LLM·임베딩 어댑터, LLM용 JSON Schema 변환 |
| `app/catalog` | Dataset 정의, 임베딩 동기화, pgvector 후보 검색 |
| `app/validation` | 계획·결과 검증 |
| `app/gis`, `app/executor` | GIS Tool(parameterized SQL), Operation 실행 |
| `app/workflows` | LangGraph 워크플로, 최종 응답 조립 |
| `app/repositories` | DB 읽기·쓰기 |
| `app/data_sources` | 원본을 내부 표준 Dataset으로 적재 |
| `app/api`, `app/cli.py` | HTTP API, 운영 CLI |
| `app/db/schema.sql` | DDL |
| `frontend/` | 화면 |
| `tests/` | `unit`, `integration`(Docker DB), `e2e`(실제 데이터·LLM) |

다음은 어기지 않는다.

- LLM은 SQL이나 코드를 만들지 않는다. LLM 출력은 Pydantic 스키마와 Plan Validator를 통과한 `AnalysisPlan`이고, 실행은 GIS Tool이 한다.
- SQL의 테이블·컬럼 이름은 메타데이터로 확인한 뒤 `psycopg.sql.Identifier`로, 값은 파라미터로 넣는다. 문자열로 SQL을 조립하지 않는다.
- `app/domain`은 I/O를 하지 않고 `app/domain` 밖의 모듈을 import하지 않는다.
- LangGraph는 `app/workflows`에서만 쓴다.
- 수치·순위·분석 방법·한계는 코드가 만든다. 화면에 보이는 LLM 문장은 요약, 해석 가정, Operation 라벨, 지원하지 않는 이유뿐이다.
- 모든 분석 실행은 성공·실패와 관계없이 `analysis.run`에 기록한다.
- 화면은 LLM이 만든 문자열을 HTML로 넣지 않는다. 텍스트로 렌더링하거나 이스케이프한다.

## 9. 실행·검증 명령

```bash
conda activate mapgpt
pip install -e ".[dev]"
docker compose up -d --build                         # PostgreSQL + PostGIS + pgvector
python -m app.cli init-db                            # 스키마 적용 (반복 실행 가능)
pytest                                               # unit + integration
ruff check app tests && ruff format --check app tests
cd frontend && npm run typecheck && npm run build
```

- integration 테스트는 Docker DB의 `mapgpt_test`를 쓴다(없으면 자동 생성). DB에 연결할 수 없으면 integration 테스트가 skip되므로, skip을 통과로 보고하지 않는다.
- ruff 설정은 `pyproject.toml`에 있다. 바꾼 파일만 포맷하고, 관계없는 파일의 포맷은 바꾸지 않는다.
- 데이터 적재(`download`, `ingest`)와 API·화면 실행 방법은 `README.md`에 있다.
- `pytest -m e2e`는 적재된 개발 DB와 실제 LLM이 필요하다. 로컬 LLM으로 돌릴 때는 `.env`를 고치지 말고 환경 변수로 덮어쓴다. 예: `LLM_PROVIDER=ollama OLLAMA_MODEL=qwen3.5:9b OLLAMA_REASONING_EFFORT=none pytest -m e2e` (thinking 모델은 `none`으로 꺼야 실용적인 속도가 나온다).
- 프롬프트나 LLM 단계를 바꾸면 가짜 LLM을 쓰는 unit·integration 테스트만으로는 부족하다. 실제 모델로 확인한다. 모델마다 실수 양상이 다르다.

## 10. 함께 고쳐야 하는 것

| 바꾸는 것 | 함께 할 일 |
|---|---|
| API 응답 모델 (`app/api/schemas.py`, `app/domain/results.py`, `app/domain/state.py`의 `WorkflowError`) | `frontend/src/types.ts`를 함께 고친다. 타입 코드 생성이 없다 |
| 워크플로 단계 (`WorkflowStep`) | `app/workflows/analysis_workflow.py`의 `_STEPS`와 엣지, `frontend/src/components/ErrorPanel.tsx`의 `STEP_NAMES` |
| DB 스키마 (`app/db/schema.sql`) | `CREATE ... IF NOT EXISTS`라 기존 DB의 테이블 변경은 반영되지 않는다. 개발 DB를 바꾸는 방법은 사용자와 정한다. 테스트 DB는 테스트 세션마다 새로 만들어진다 |
| Dataset 메타데이터 (`app/catalog/definitions.py`) | `python -m app.cli ingest <dataset>`으로 카탈로그와 검색 임베딩을 갱신한다. 하지 않으면 분석이 `CATALOG_INDEX_STALE`로 멈춘다 |
| 프롬프트 (`app/agents/prompts.py`) | 실제 모델로 확인한다. 모델·Enum 타입 필드(`$ref`)의 description은 LLM용 스키마에서 빠지므로, 모델이 지켜야 할 규칙은 프롬프트에 적는다 |
| 새 Operation | `docs/agent-design-overview.md` 14장의 순서를 따른다 |
| 동작·계약·설계 결정 | `docs/design/mvp-design.md` 부록 D에 기록하고, 관련 문서(개요, 전달 문서)를 갱신한다 |

## 11. 비용·보안·외부 반영 (팀 공통)

- `.env`의 값(API 키 등)을 출력·기록·커밋하지 않는다. 필요하면 키 이름과 설정 여부만 말한다. 사용자의 `.env`는 고치지 않는다.
- 원본 데이터(`data/`)는 커밋하지 않는다. 용량과 라이선스(어린이집은 공공누리 제4유형) 때문이다.
- OpenAI LLM을 호출하는 실행(분석 실행, e2e, 프롬프트 검증 등)은 사용자에게 먼저 확인한다. 검증은 가능하면 로컬 LLM(Ollama)으로 한다. 검색 임베딩(분석 1회당 1번, `embed-catalog`)은 비용이 매우 작아 확인 없이 쓴다.
- `git push`, PR 생성, 외부 서비스 게시는 사용자가 요청할 때만 한다.
- 개발 DB의 데이터를 지우거나 테이블을 다시 만드는 작업은 사용자에게 먼저 확인한다.

## 12. 작업 전에 읽을 문서

| 작업 | 먼저 읽을 곳 |
|---|---|
| 처음 참여 | `README.md`, `docs/agent-design-overview.md` 1~3장 |
| 에이전트 흐름·프롬프트·검증 | `docs/agent-design-overview.md` 3장 |
| API·실행 모델·운영 | `docs/backend-handoff.md` 2·4·5·9장 |
| 화면 | `docs/agent-design-overview.md` 7장, `docs/frontend-handoff.md` 2장 |
| 데이터 적재·DB 구조 | `docs/data-handoff.md` 2·3·6장 |
| 자주 하는 변경의 수정 위치 | `docs/agent-design-overview.md` 14장 |
| 설계 결정의 이유와 변경 이력 | `docs/design/mvp-design.md` 부록 D |
| 원 요구사항 | `docs/공간 분석 AI Agent 개발 전달 문서.md` (설계 원칙 2번, Analysis Plan 10번, 워크플로 25번, 확장 31~37번) |

문서와 코드가 다르면 코드를 기준으로 하고, 문서를 고치거나 사용자에게 알린다.