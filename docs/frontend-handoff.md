# 화면 현황과 향후 과제 — 프론트엔드 담당자 전달 문서

- 작성일: 2026-10-09
- 기준 코드: `main` 브랜치 `2df606c`
- 대상: 화면(`frontend/`)을 넘겨받을 프론트엔드 담당자

이 문서는 세 가지를 담는다.

1. 넘겨받는 화면 초안의 상태와, 백엔드·에이전트와 맞물린 계약 (사실)
2. 아직 없는 것과 개발 쪽 의견 (제안)
3. 프론트엔드 담당자가 결정해 줄 사항 (결정)

화면의 구조와 동작(컴포넌트, 상태 흐름, 지도 렌더링)은 [에이전트 설계 개요 7장](agent-design-overview.md#7-프론트엔드)에 자세히 있어 여기서는 반복하지 않는다. 권장안은 개발 쪽 의견이며 결정은 담당자가 한다.

## 요약

- **현재:** Vite + React + TypeScript + MapLibre로 만든 초안이다.
  - 질문을 입력하면 `POST /api/analyses`를 한 번 보내고, 응답으로 지도·순위·요약·분석 방법·가정·한계를 그린다.
  - `src`는 약 770줄이고, 런타임 라이브러리는 React와 MapLibre뿐이다.
  - 타입 검사와 빌드는 통과한다.
- **지도:** 팀은 처음에 카카오맵을 쓰기로 했지만, 구현 기준이었던 개발 전달 문서(23·29·42번)가 MapLibre를 명시해 MapLibre로 만들었다. 어느 쪽으로 갈지는 담당자가 정한다(F1). 바꾸더라도 지도 컴포넌트 하나만 다시 만들면 된다.
- **첫 분석 주제에 묶인 부분:** "행정동", "공급 부족 / 여유" 같은 문구와 색 방향이 코드에 고정되어 있다. 두 번째 분석 주제가 생기면 응답에서 받아오도록 바꿔야 한다.
- **백엔드와 함께 정할 것:** 진행 상황 표시(지금은 경과 시간만), 배포 시 서빙 방식, 응답 타입 동기화.
- **결정 요청:** 6장. 먼저 정할 것은 지도 라이브러리(F1)와 진행 상황 표시 방식(F3)이다.

## 목차

1. [넘겨받는 것](#1-넘겨받는-것)
2. [백엔드·에이전트와의 계약](#2-백엔드에이전트와의-계약)
3. [지도: MapLibre와 카카오맵](#3-지도-maplibre와-카카오맵)
4. [첫 분석 주제에 묶인 부분](#4-첫-분석-주제에-묶인-부분)
5. [아직 없는 것과 개발 쪽 의견](#5-아직-없는-것과-개발-쪽-의견)
6. [프론트엔드 담당자 결정 사항](#6-프론트엔드-담당자-결정-사항)
7. [참고](#7-참고)

## 1. 넘겨받는 것

### 1.1 구성

| 구분 | 내용 |
|---|---|
| 스택 | Vite 8.3, React 19.3, TypeScript 7.0(strict), MapLibre GL 6.13 |
| 런타임 의존성 | `react`, `react-dom`, `maplibre-gl` 셋뿐이다. 상태 관리·UI·라우터 라이브러리는 없다 |
| 스타일 | `styles.css` 하나. 색은 CSS 변수로 두고, `prefers-color-scheme`으로 라이트·다크를 바꾼다. 860px 미만에서는 세로로 쌓는다 |
| 배경지도 | OpenFreeMap positron(라이트), dark(다크). API 키가 필요 없다 |
| 개발 서버 | `:5173`. `/api`를 FastAPI `:8000`으로 프록시한다(타임아웃 300초) |
| 로컬 검증 환경 | Node 23.11, npm 10.9. README는 Node 20 이상으로 안내한다 |

파일별 역할은 [개요 문서 7.2절](agent-design-overview.md#72-디렉터리-구조)에 있다. 크기는 다음과 같다.

| 파일 | 줄 수 |
|---|---|
| `ChoroplethMap.tsx` | 149 |
| `App.tsx` | 123 |
| `RankingTable.tsx` | 80 |
| `types.ts` | 78 |
| `theme.ts` | 61 |
| `ResultDetails.tsx` | 54 |
| `Legend.tsx` | 40 |
| `ErrorPanel.tsx` | 39 |
| `api.ts` | 15 |
| `styles.css` | 125 |

### 1.2 명령

```bash
cd frontend
npm install
npm run dev         # 개발 서버 :5173 (API 서버 :8000이 떠 있어야 함)
npm run typecheck   # tsc --noEmit
npm run build       # 타입 검사 후 frontend/dist에 빌드
```

API 서버와 데이터 준비는 [README](../README.md)와 [백엔드 담당자 전달 문서 3.3절](backend-handoff.md#33-실행-방법)에 있다.

### 1.3 빌드 결과

| 파일 | 크기 | gzip |
|---|---|---|
| `index-*.js` (앱 + React + MapLibre) | 1,276KB | 355KB |
| `maplibre-gl-worker-*.js` | 508KB | (보고 없음) |
| `index-*.css` (대부분 MapLibre CSS) | 88KB | 12KB |

Vite가 "500KB를 넘는 청크" 경고를 낸다.

### 1.4 확인된 것과 없는 것

- **확인된 것:**
  - 실제 데이터(행정동 427개)로 지도·표·범례·툴팁이 동작한다.
  - 표와 지도 강조가 양방향으로 연동된다.
  - 라이트·다크 전환과 좁은 화면 배치가 동작한다.
  - 지도 색 램프는 라이트·다크 모두 순서형 팔레트 검사를 통과했다.
- **없는 것:**
  - 테스트, ESLint·Prettier 설정, CI가 없다. 검사는 `npm run typecheck`뿐이다.
  - `ChoroplethMap.tsx`에 `eslint-disable` 주석이 하나 있지만, ESLint는 설치되어 있지 않다.

## 2. 백엔드·에이전트와의 계약

### 2.1 API 사용

| API | 화면에서 쓰는 곳 |
|---|---|
| `POST /api/analyses` | 분석 요청 ([api.ts](../frontend/src/api.ts)) |
| `GET /api/analyses/{run_id}` | "실행 기록" 링크로 원본 JSON을 새 탭에 연다 |
| `GET /api/datasets`, `GET /api/health` | 쓰지 않는다 |

- **응답 처리:**
  - 분석이 실패해도 HTTP 200에 `status: "failed"`와 `errors[]`가 온다. `ErrorPanel`이 단계 이름, 코드, 메시지, 세부 issues를 보여준다.
  - 422(형식 오류)나 503(LLM·임베딩 설정 누락) 같은 HTTP 오류는 "요청을 처리하지 못했습니다" 카드에 `detail`을 보여준다.
- **단계 이름:** `errors[].step`은 백엔드 워크플로의 9개 단계 이름이다. 화면은 `ErrorPanel.tsx`의 `STEP_NAMES`로 한국어 이름을 붙이므로, 단계가 늘면 함께 고친다.
- **응답 크기와 시간:**
  - 성공 응답은 행정동 427개의 GeoJSON을 포함해 약 590KB다.
  - 걸리는 시간은 gpt-4o-mini 기준 15~21초, 로컬 LLM은 최대 3분 정도다.
  - 개발 서버 프록시는 300초에 끊는다.

### 2.2 타입 동기화

[frontend/src/types.ts](../frontend/src/types.ts)는 백엔드의 `app/api/schemas.py`, `app/domain/results.py`, `app/domain/state.py`를 손으로 옮긴 것이다. 코드 생성이 없으므로 한쪽을 바꾸면 다른 쪽도 함께 바꿔야 한다. FastAPI가 `/openapi.json`을 제공하므로 타입 생성 도구로 바꿀 수 있다(F10). 다만 `GET /api/analyses/{run_id}`는 응답 스키마가 느슨하다.

### 2.3 화면이 지켜야 할 것

1. **필수 표시 항목:** 개발 전달 문서 22번이 요구하는 항목을 모두 보여준다. 지금은 모두 있다.
   - 지도, 순위, 분석 지표, 사용 데이터, 데이터 기준 시점, 분석 방법, 가정, 한계
2. **수치는 응답 값 그대로:**
   - 순위, 분위 경계값, 결측 사유는 백엔드가 계산한 값을 그대로 쓰고, 화면에서 다시 계산하지 않는다.
   - 범례 구간은 `[경계값 이상, 다음 경계값 미만)`으로, 지도 색 식(MapLibre `step`)과 같다.
3. **LLM이 만든 문자열은 텍스트로만 넣는다:**
   - 해당 문자열은 요약, 지표·연산 라벨, 가정, 지원하지 않는 이유다.
   - React는 기본으로 이스케이프하고, 지도 툴팁(HTML 문자열)은 `escapeHtml`을 거친다.
   - 이 문자열을 `dangerouslySetInnerHTML`이나 HTML 조립에 그대로 넣지 않는다.
4. **출처·라이선스 표시:** 사용 데이터 카드에 각 데이터의 라이선스를 보여준다.
   - 어린이집 데이터는 **공공누리 제4유형(출처표시, 상업적 이용금지, 변경금지)**이라 출처 표시가 필요하다.
   - 지도 하단의 배경지도 표기(OpenMapTiles, OpenStreetMap)와 "경계: 통계청 SGIS"를 없애지 않는다.
5. **색:**
   - 램프는 단일 색상 5단계이고, 가장 작은 값(공급 부족)이 가장 눈에 띈다. 라이트는 진할수록, 다크는 밝을수록 부족하다.
   - 값 없음은 회색이다.
   - 색을 바꾸면 라이트·다크 모두에서 순서가 구분되는지 다시 확인한다.

## 3. 지도: MapLibre와 카카오맵

### 3.1 경위

팀에서는 처음에 카카오맵을 쓰기로 했다. 하지만 구현 기준으로 삼은 개발 전달 문서가 지도를 MapLibre로 명시했고, 카카오맵 결정은 이 문서에 반영되어 있지 않아 MapLibre로 구현했다.
- 23번(지도 출력): "React + MapLibre GL JS"
- 29번(UI 연결): MapLibre
- 42번(핵심 기술): MapLibre

### 3.2 이 화면의 지도에 필요한 것

- 행정동 427개를 값에 따라 칠하는 지도(Choropleth)
- 분위 구간별 색, 값 없음 회색
- 표와 지도의 hover 강조, 툴팁
- 지명 라벨을 가리지 않는 레이어 순서
- 라이트·다크 배경지도

### 3.3 비교

| 항목 | MapLibre + OpenFreeMap (현재) | 카카오맵 JavaScript API |
|---|---|---|
| GeoJSON | API 응답을 GeoJSON 소스로 그대로 올린다 | 공식 레퍼런스에서 GeoJSON을 바로 그리는 기능을 찾지 못했다. 좌표를 변환해 행정동마다 다각형 객체를 만들어야 한다 |
| 값에 따른 색 | 스타일 식(`step`) 하나로 지정 | 다각형마다 색을 계산해 지정 |
| 강조·툴팁 | `feature-state`와 레이어 이벤트 | 다각형마다 이벤트 연결 |
| 배경지도 스타일 | 스타일 URL만 바꾸면 라이트·다크 전환 | 배경지도 색·스타일을 바꾸는 공식 기능을 찾지 못했다 |
| 키·등록 | 필요 없다. MapLibre는 BSD-3 오픈소스이고 OpenFreeMap은 가입·키가 없다 | JavaScript 앱 키 발급과 사이트 도메인 등록이 필요하다. 등록한 도메인에서만 동작한다 |
| 호출 한도·비용 | 없다. OpenFreeMap은 요청 수 제한이 없고 상업 이용도 허용한다 | 지도 SDK 무료 쿼터는 하루 30만 건이고, 개발자 계정의 첫 번째 앱에만 준다. 넘으면 건당 0.1원이 과금되고, 유료 설정이 없으면 429 오류가 난다. 2026-07-21에 사용 방법과 무료 쿼터 방식이 바뀌었다 |
| 국내 지도 품질 | OpenStreetMap 기반이다. 국내 상호·건물 정보는 국내 포털 지도보다 적은 편이다 | 국내 상호·건물 정보가 풍부하고 사용자에게 익숙하다. 로드뷰·스카이뷰가 있다 |
| 확장 | 데이터가 커지면 벡터 타일로 넘어갈 수 있다 | 직접 만든 벡터 타일을 그리는 기능은 확인하지 못했다 |

- 카카오의 주소 검색·장소 검색은 지도 SDK와 별개인 REST API라서, MapLibre를 써도 함께 쓸 수 있다.
- 이 API는 데이터 담당자 문서의 지오코딩 결정(D16)에도 후보로 들어 있다.

### 3.4 바꿀 때 범위

- **다시 만들 것:**
  - `ChoroplethMap.tsx`(149줄)
  - `theme.ts`의 배경지도 설정(`MAP_CHROME.basemapStyle`)
- **그대로 두는 것:** 범례, 순위 표, 타입, API 호출. 백엔드와 에이전트도 영향이 없다. API는 GeoJSON을 그대로 돌려준다.
- **카카오맵으로 갈 때 할 일:**
  - 앱 키 발급과 개발·운영 도메인 등록
  - SDK 로드
  - GeoJSON MultiPolygon을 카카오 다각형으로 변환. 구멍 있는 경계를 어떻게 처리할지 확인해야 한다
  - 구간별 색 계산
  - 다각형별 hover·툴팁 연결
- **잃는 것:** 다크 배경지도
- **절충안:** MapLibre를 유지하면서 국내 배경지도 타일(예: 브이월드)로 바꾸는 방법도 있다. 키와 약관은 따로 확인해야 하고, 아직 검증하지 않았다.

## 4. 첫 분석 주제에 묶인 부분

지금 화면은 "인구 대비 시설 공급 부족을 행정동별로 보는" 첫 분석 주제에 맞춰 문구와 방향이 고정되어 있다. 두 번째 분석 주제(예: 지하철역 500m 밖 지역)나 다른 공간 단위가 생기면 고쳐야 한다.

| 위치 | 고정된 것 |
|---|---|
| `RankingTable.tsx` | 제목 "공급 부족 상위 N개 행정동"과 "전체 N개 행정동", 열 이름 "행정동" |
| `Legend.tsx` | 양 끝 문구 "← 공급 부족 / 여유 →" (작은 값이 부족이라는 방향) |
| `theme.ts` | 색 램프 방향(작은 값이 가장 눈에 띔), 결측 사유 문구("분모(인구)가 0", "인구 자료 없음", "시설 자료 없음") |
| `App.tsx` | 예시 질문, 진행 표시용 단계 목록(7개, 실제 단계는 9개), 안내 문구 |

- **지금 응답에 있는 것:**
  - 지표 이름·라벨·해석 문장(`metric.interpretation`, 예: "값이 작을수록 공급 부족")
  - 순위 지표 이름(`rank_metric`)
- **없는 것:** 공간 단위 이름(행정동·시군구), 값의 방향(작을수록 나쁜지)
- **의견:** 이 두 값을 응답 필드로 받아 화면 문구와 색 방향을 정하는 것을 권한다. 응답 형식을 바꾸는 일이므로 에이전트 담당과 함께 정한다.

## 5. 아직 없는 것과 개발 쪽 의견

### 5.1 진행 상황과 긴 대기 (백엔드 B1과 함께, 먼저)

지금은 응답이 올 때까지 경과 시간과 고정된 단계 목록만 보여준다.
- 백엔드가 비동기 실행으로 바뀌면 `run_id`를 바로 받는다.
- 그 뒤로는 폴링(`GET /api/analyses/{run_id}`)이나 SSE로 실제 단계 진행을 받아 보여줄 수 있다.
- 백엔드 쪽 권장안은 [백엔드 담당자 전달 문서 8.1절](backend-handoff.md#81-비동기-실행과-진행-상황-먼저)에 있다.
- 취소 버튼도 이 구조 위에서 만든다.

### 5.2 결과 URL과 새로고침 (지금 바로 가능)

- 지금은 새로고침하면 결과가 사라지고, 결과를 링크로 공유할 수 없다.
- `GET /api/analyses/{run_id}`가 이미 `result`(성공 시 `FinalResponse`)와 `provenance`(실패 시 `errors` 포함)를 돌려준다.
- 그래서 `?run=<run_id>`처럼 URL에 실행 ID를 남기면, 백엔드 변경 없이 결과를 다시 열 수 있다.

### 5.3 실행 기록 보기

- 지금은 "실행 기록" 링크가 원본 JSON을 연다.
- 같은 응답의 `provenance`에 해석 결과, 데이터 후보와 유사도, 데이터 선택 근거, 계획 시도와 검증 오류가 모두 있다.
- 이것을 읽기 쉬운 패널로 보여주면 사용자가 결과를 믿을 근거가 되고, 실패 원인을 찾기도 쉬워진다.

### 5.4 오류 안내

- 지금은 오류 코드(`REGION_NOT_SUPPORTED` 등)와 백엔드 메시지를 그대로 보여준다.
- 자주 나는 코드에는 사용자용 안내를 붙이는 것을 권한다.
  - `REGION_NOT_SUPPORTED`: "현재는 서울만 분석할 수 있습니다"
  - `UNIT_NOT_SUPPORTED`: "행정동 단위만 지원합니다"
- 지원하는 질문 예시도 보여주면 좋다.
- 코드별 의미는 [개요 문서 3.7절](agent-design-overview.md#37-실패-코드-모음-workflowerrorcode)과 [10.2절](agent-design-overview.md#102-자주-보는-오류)에 있다.

### 5.5 접근성과 입력 장치

- 툴팁과 표·지도 강조는 마우스 hover로만 동작한다. 터치 기기와 키보드 사용은 검증하지 않았다.
- 지도는 `role="img"`와 설명 라벨이 있고, 같은 정보는 순위 표("전체 표 보기")로도 볼 수 있다.

### 5.6 성능

- 주 번들이 1.28MB(gzip 355KB)다. 지도 컴포넌트를 동적 `import()`로 나누면 첫 화면이 가벼워진다.
- 응답 약 590KB는 백엔드 쪽 압축(백엔드 문서 8.9절)으로 줄일 수 있다.
- 테마가 바뀌면 배경지도 스타일이 달라 지도를 다시 만든다.

### 5.7 도구와 배포

- **도구:**
  - ESLint·Prettier 설정
  - 컴포넌트 테스트(Vitest + Testing Library)
  - API를 흉내 낸 화면 E2E(Playwright 등)
  - Node 버전 고정(`.nvmrc`나 `engines`)
- **배포:**
  - `npm run build` 결과(`frontend/dist`)를 리버스 프록시가 서빙하고 `/api`를 API로 넘기는 구성을 권한다(백엔드 B8).
  - 화면은 `/api`를 상대 경로로 부르므로, 같은 출처로 서빙하면 설정이 필요 없다.
  - 다른 출처에 두면 API 주소 설정과 CORS가 필요하다.

### 5.8 그 밖에

- `GET /api/datasets`로 등록된 데이터와 지원 지역을 보여주면, 사용자가 어떤 질문을 할 수 있는지 알기 쉽다.
- 다크 모드는 운영체제 설정만 따른다. 직접 바꾸는 버튼은 없다.

## 6. 프론트엔드 담당자 결정 사항

"우선"에 "먼저"라고 표시한 항목은 다음 개발을 시작하기 전에 정해야 하는 것이다. 권장은 개발 쪽 의견이다.

| # | 결정 사항 | 선택지 | 권장 | 우선 |
|---|---|---|---|---|
| F1 | 지도 라이브러리 | MapLibre(현재) / 카카오맵 | 분석 지도(Choropleth)에는 MapLibre를 유지한다. 국내 지도 품질이 중요하면 F2로 보완한다 | 먼저 |
| F2 | 배경지도 | OpenFreeMap(현재) / 국내 배경지도 타일(브이월드 등) / 카카오(F1에 따름) | 우선 유지하고, 사용자 반응을 보고 국내 배경지도를 검토한다. 키·약관 확인 필요 | |
| F3 | 진행 상황 표시 | 경과 시간(현재) / 폴링 / SSE | 백엔드 B1과 함께 정한다. 실제 단계 진행과 취소를 보여준다 | 먼저 |
| F4 | 결과 URL | 없음(현재) / `run_id`를 URL에 남김 | URL에 남기고 `GET /api/analyses/{run_id}`로 다시 연다 | |
| F5 | 실행 기록 보기 | 원본 JSON 링크(현재) / 읽기 쉬운 패널 | 해석, 데이터 후보·선택 근거, 계획 시도를 패널로 보여준다 | |
| F6 | 상태 관리·라우팅 | React state만(현재) / 라우터 + 서버 상태 라이브러리(TanStack Query 등) | F3·F4를 할 때 도입을 검토한다 | |
| F7 | UI 구성 요소 | 직접 작성한 CSS(현재) / UI 라이브러리·디자인 시스템 | 화면이 늘어날 때 정한다. 지금 색 토큰(CSS 변수)은 그대로 옮길 수 있다 | |
| F8 | 지원 환경 | 데스크톱 우선, 860px 미만 세로 배치(현재) / 모바일·터치 정식 지원 | 공개 대상에 맞춰 정한다. 터치에서는 hover 대신 탭으로 정보를 보여준다 | |
| F9 | 테스트·린트 | typecheck만(현재) / ESLint·Prettier, Vitest, E2E | ESLint·Prettier와 Vitest부터 두고, CI는 백엔드와 함께 구성한다 | |
| F10 | 타입 동기화 | 수동(현재) / OpenAPI에서 타입 생성(openapi-typescript 등) | 생성 방식으로 바꾼다. 백엔드가 응답 스키마를 모두 선언해야 한다 | |
| F11 | 분석 주제가 늘 때의 문구·색 방향 | 화면에 고정(현재) / 응답 필드로 받음 | 공간 단위 이름과 값의 방향을 응답에서 받는다. 에이전트 담당과 협의한다 | |

## 7. 참고

### 7.1 코드 위치

| 내용 | 위치 |
|---|---|
| 화면 구성, 요청, 진행 표시 | [frontend/src/App.tsx](../frontend/src/App.tsx) |
| API 호출 | [frontend/src/api.ts](../frontend/src/api.ts) |
| 응답 타입 | [frontend/src/types.ts](../frontend/src/types.ts) |
| 지도 | [frontend/src/components/ChoroplethMap.tsx](../frontend/src/components/ChoroplethMap.tsx) |
| 범례 | [frontend/src/components/Legend.tsx](../frontend/src/components/Legend.tsx) |
| 순위 표 | [frontend/src/components/RankingTable.tsx](../frontend/src/components/RankingTable.tsx) |
| 데이터·방법·가정·한계 | [frontend/src/components/ResultDetails.tsx](../frontend/src/components/ResultDetails.tsx) |
| 오류 | [frontend/src/components/ErrorPanel.tsx](../frontend/src/components/ErrorPanel.tsx) |
| 색 램프, 배경지도, 값 포맷, 결측 사유 | [frontend/src/theme.ts](../frontend/src/theme.ts) |
| 레이아웃·색 토큰 | [frontend/src/styles.css](../frontend/src/styles.css) |
| 개발 서버·프록시 | [frontend/vite.config.ts](../frontend/vite.config.ts) |
| 백엔드 응답 모델 | [app/api/schemas.py](../app/api/schemas.py), [app/domain/results.py](../app/domain/results.py), [app/domain/state.py](../app/domain/state.py) |

### 7.2 관련 문서

- [에이전트 설계 개요](agent-design-overview.md): 7장 화면 구조와 동작, 3.7절 오류 코드, 6.3절 API 응답 예시
- [백엔드 담당자 전달 문서](backend-handoff.md): API 계약, 실행 모델, 비동기 실행(B1), 화면 서빙(B8)
- [데이터 담당자 전달 문서](data-handoff.md): 데이터 출처와 라이선스, 지오코딩 검토(D16)
- [개발 전달 문서](공간%20분석%20AI%20Agent%20개발%20전달%20문서.md): 원 요구사항. 결과 출력은 22번, 지도 출력은 23번

### 7.3 외부 자료 (2026-10 확인)

- [카카오맵 Web API 가이드](https://apis.map.kakao.com/web/guide/): 앱 키, 도메인 등록
- [카카오 디벨로퍼스 쿼터](https://developers.kakao.com/docs/ko/getting-started/quota): 지도 SDK 일 30만 건, 초과 요금
- [카카오맵 API 이해하기](https://developers.kakao.com/docs/ko/kakaomap/common): 첫 앱 무료 쿼터, 2026-07-21 변경
- [데브톡: GeoJSON 좌표를 직접 변환해 폴리곤을 그리는 사례](https://devtalk.kakao.com/t/topic/133798)
- [OpenFreeMap](https://openfreemap.org/): 키·요청 제한 없음, 상업 이용 허용, 출처 표기
- [MapLibre GL JS](https://github.com/maplibre/maplibre-gl-js): BSD-3 라이선스
