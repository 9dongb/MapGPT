# MapGPT

자연어 공간 분석 질문을 LLM이 **구조화된 Analysis Plan**으로 바꾸고, 결정론적 검증을 거쳐 **PostGIS**에서 실행한 뒤 지도·순위·설명으로 돌려주는 공간 분석 AI Agent입니다 (MVP: 첫 번째 Vertical Slice).

> "서울에서 어린이 인구 대비 어린이집이 부족한 행정동을 알려줘."
> → 행정동별 `어린이집 수 ÷ 0~5세 인구 × 1,000`을 계산하고 값이 작은 순으로 순위를 매긴 Choropleth 지도

- 설계: [docs/design/mvp-design.md](docs/design/mvp-design.md)
- 요구사항 원문: [공간 분석 AI Agent 개발 전달 문서.md](공간%20분석%20AI%20Agent%20개발%20전달%20문서.md)

LLM은 질문 해석 · Dataset 선택 · Analysis Plan 생성 · 결과 설명만 합니다. SQL이나 코드를 생성하지 않으며, 모든 계산은 검증된 Plan을 GIS Tool(parameterized SQL)이 실행합니다.

## 준비

- conda 환경 `mapgpt` (Python 3.12), Docker, Node.js 20+

```bash
conda activate mapgpt
pip install -e ".[dev]"
cp .env.example .env   # 키를 채웁니다
docker compose up -d   # PostGIS
python -m app.cli init-db
```

`.env` 주요 항목:

| 변수 | 설명 |
|---|---|
| `LLM_PROVIDER` | `openai` 또는 `ollama` |
| `OPENAI_API_KEY`, `OPENAI_MODEL` | OpenAI Responses API (기본 `gpt-6.1-sol`) |
| `OLLAMA_BASE_URL`, `OLLAMA_MODEL` | 로컬 Ollama (예: `ollama pull qwen3.5:9b` 후 `OLLAMA_MODEL=qwen3.5:9b`) |
| `OLLAMA_REASONING_EFFORT` | thinking 모델의 추론 강도. `none`이면 thinking을 끕니다 (qwen3.5:9b 해석 단계 130초 → 6초) |
| `SEOUL_OPEN_API_KEY` | 서울 열린데이터광장 인증키 (어린이집 `ChildCareInfo` API) |

## 데이터 적재

```bash
python -m app.cli download        # 행정동 경계(GeoJSON)·인구(CSV) → data/raw/
python -m app.cli ingest all      # 경계 → 인구 → 어린이집 순서로 서울 데이터만 정규화·적재
```

어린이집은 API로 수집한 원본을 `data/raw/seoul_childcare_YYYYMMDD.json`에 캐시합니다(`--refresh`로 다시 수집). 적재할 때 운영 중(운영현황 '정상'·'재개')인 시설만 남기고, 좌표 품질 규칙(좌표 없음, 다른 자치구 시설과 같은 기본값 좌표, 신고 자치구 밖 좌표)에 걸린 시설을 제외한 뒤 제외 건수를 카탈로그에 기록합니다.

## 실행

```bash
uvicorn app.api.main:app --reload
```

```bash
cd frontend && npm install && npm run dev
```

브라우저에서 http://localhost:5173 을 엽니다. 터미널에서 바로 실행할 수도 있습니다.

```bash
python -m app.cli analyze "서울에서 어린이 인구 대비 어린이집이 부족한 행정동을 알려줘."
```

API: `POST /api/analyses`, `GET /api/analyses/{run_id}` (Provenance), `GET /api/datasets`, `GET /api/health`

## 테스트

```bash
pytest              # unit + integration (integration은 docker compose의 PostGIS에 mapgpt_test DB를 만들어 사용)
```

```bash
pytest -m e2e       # 실제 적재 데이터 + 실제 LLM으로 성공 기준 1~12 확인
```

## 데이터 출처와 라이선스

| Dataset | 출처 | 기준 시점 | 라이선스 |
|---|---|---|---|
| 행정동 경계 | 통계청 SGIS 기반 [vuski/admdongkor](https://github.com/vuski/admdongkor) `ver20260701` | 2026-07-01 | CC BY 4.0 (출처: 통계청 SGIS) |
| 연령별 인구 | 행정안전부, [공공데이터포털 15097972](https://www.data.go.kr/data/15097972/fileData.do) | 2026-09-30 | 이용허락범위 제한 없음 |
| 어린이집 | 서울 열린데이터광장 `ChildCareInfo` (OA-20300) | 수집일 기준 | **공공누리 제4유형 (출처표시·상업적 이용금지·변경금지)** |

어린이집 데이터는 상업적 이용이 금지되어 있습니다. 상업 서비스에 쓰려면 이용 조건을 따로 확인해야 합니다. 배경지도는 [OpenFreeMap](https://openfreemap.org) (© OpenMapTiles, OpenStreetMap)입니다.
