"""LLM 단계별 프롬프트. LLM은 해석·선택·계획·설명만 하고 계산은 하지 않는다."""

import json
from typing import Any

from app.domain.catalog import DatasetMetadata, RegionRef
from app.domain.enums import SPATIAL_LEVEL_NAMES, SpatialLevel
from app.domain.policies import POLICIES
from app.domain.results import ValidationIssue


def _level(level: SpatialLevel) -> str:
    return f"{level}({SPATIAL_LEVEL_NAMES[level]})"


def _json(data: Any) -> str:
    return json.dumps(data, ensure_ascii=False, indent=2, default=str)


def _policy_text() -> str:
    lines = []
    for policy in POLICIES.values():
        lines.append(f"- {policy.intent}: {policy.title}. {policy.description}")
        lines.append(f"  · 해석: {policy.interpretation}")
        lines.extend(f"  · 정의: {definition}" for definition in policy.definitions)
    return "\n".join(lines)


def interpret_prompt(question: str, coverage: list[tuple[RegionRef, list[SpatialLevel]]]) -> tuple[str, str]:
    available = "\n".join(
        f"- {region.name} ({region.level}): {', '.join(_level(u) for u in units) or '분석 가능한 단위 없음'}"
        for region, units in coverage
    )
    system = f"""너는 공간 분석 질문 해석기다. 사용자의 자연어 질문을 이 시스템이 지원하는 분석으로 해석할 수 있는지 판단하고 해석 결과만 반환한다. 계산이나 데이터 조회는 하지 않는다.

[지원하는 분석 유형(intent)과 분석 정책]
{_policy_text()}

[공간 단위(analysis_unit)]
{", ".join(_level(level) for level in SpatialLevel)}

[데이터가 있는 지역과 분석 가능한 단위]
{available or "- (없음)"}

[규칙]
1. 질문이 위 분석 유형으로 표현되지 않으면 intent, region, analysis_unit을 null로 두고 unsupported_reason에 이유를 쓴다.
2. region.name은 공식 명칭으로 쓴다 (예: '서울' → '서울특별시'). 사용자가 말한 지역을 다른 지역으로 바꾸지 않는다.
3. analysis_unit은 결과를 보여줄 공간 단위다 (예: '동별' → emd, '구별' → sigungu). 사용자가 말한 단위를 다른 단위로 바꾸지 않으며, 단위를 말하지 않았으면 그 지역에서 분석 가능한 단위를 쓴다.
4. assumptions에는 위 분석 정책 정의 외에 질문을 해석하며 추가로 둔 가정만 적는다. 정책 정의를 다시 쓰지 않으며, 없으면 빈 목록으로 둔다.
5. key_concepts에는 분석에 필요한 데이터 개념을 짧은 명사구로 적는다."""
    return system, f"질문: {question}"


def _dataset_summary(d: DatasetMetadata) -> dict[str, Any]:
    return {
        "dataset_id": d.dataset_id,
        "title": d.title,
        "description": d.description,
        "category": d.category,
        "semantic_tags": d.semantic_tags,
        "spatial": d.spatial.model_dump(mode="json", include={"level", "geometry_type", "coverage"}),
        "temporal": d.temporal.model_dump(mode="json"),
        "columns": {c.name: c.description for c in d.columns},
    }


def select_prompt(interpreted: dict[str, Any], candidates: list[DatasetMetadata]) -> tuple[str, str]:
    system = """너는 공간 분석에 필요한 Dataset을 고르는 선택기다. 해석된 분석 질문과 후보 Dataset 메타데이터를 보고 분석에 필요한 Dataset ID만 고른다.

[규칙]
1. 후보 목록에 있는 dataset_id만 쓴다.
2. 분석 단위 경계, 수요(인구), 공급(시설)처럼 계산에 필요한 Dataset은 빠짐없이 고르고, 필요 없는 Dataset은 넣지 않는다.
3. rationale에 각 Dataset을 고른 이유를 짧게 쓴다."""
    user = f"[해석된 질문]\n{_json(interpreted)}\n\n[후보 Dataset]\n{_json([_dataset_summary(d) for d in candidates])}"
    return system, user


def _dataset_detail(d: DatasetMetadata) -> dict[str, Any]:
    return d.model_dump(
        mode="json",
        include={"dataset_id", "title", "description", "spatial", "temporal", "columns", "join_keys"},
        exclude={"spatial": {"bbox", "feature_count"}},
    )


def plan_prompt(
    interpreted: dict[str, Any],
    datasets: list[DatasetMetadata],
    feedback: tuple[dict[str, Any] | None, list[ValidationIssue]] | None = None,
) -> tuple[str, str]:
    system = f"""너는 공간 분석 계획(AnalysisPlan)을 만드는 Planner다. SQL이나 코드를 쓰지 않고 JSON Schema에 맞는 AnalysisPlan만 만든다. 실제 계산은 별도의 GIS 엔진이 이 계획을 검증한 뒤 수행한다.

[분석 정책]
{_policy_text()}

[Operation 의미]
- aggregate_by_area: Point Dataset(input)을 Polygon 경계 Dataset(boundary)의 각 단위 안에 있는 개수로 센다 (aggregation=count). 결과는 경계 단위별 값이다.
- aggregate: Dataset(input)을 group_by 키(분석 단위 경계와 결합되는 join key 1개)별로 aggregation.field를 합계(sum)하거나 개수(count)를 센다.
- calculate_ratio: numerator ÷ denominator × scale. numerator와 denominator는 앞에서 만든 output 이름이다.
- rank: input(앞에서 만든 output)에 order 방향으로 순위를 매긴다.

[작성 규칙]
1. intent, region, analysis_unit은 해석 결과를 그대로 쓴다.
2. datasets에는 operation과 filter에서 쓰는 Dataset ID를 모두 넣는다. 주어진 Dataset만 쓴다.
3. 질문이나 분석 정책이 요구하는 행 조건만 filters에 Dataset별로 둔다 (예: 정책이 정의한 연령대). 기준일·유형 전체 나열처럼 요구되지 않은 조건은 추가하지 않는다 — Dataset은 이미 기준 시점의 데이터다. field는 그 Dataset의 컬럼명이고 값의 타입은 컬럼 data_type과 맞아야 한다. 분석 단위 경계 Dataset에는 filter를 두지 않는다 (지역은 region으로 정해진다).
4. operations는 실행 순서대로 쓰고, 뒤의 operation은 앞에서 만든 output만 참조한다.
5. output 이름은 snake_case 영문으로 서로 겹치지 않고 Dataset ID·컬럼명과도 겹치지 않는다. label은 짧은 한국어 이름이다.
6. output.metric에는 지도에 색으로 표시할 지표 값의 output 이름을 쓴다 (예: calculate_ratio의 output). rank의 output(순위)은 output.metric이 될 수 없다.
7. ranking.enabled가 true면 output.metric을 input으로 하는 rank operation이 있어야 한다."""
    user = f"[해석된 질문]\n{_json(interpreted)}\n\n[사용할 Dataset]\n{_json([_dataset_detail(d) for d in datasets])}"
    if feedback is not None:
        previous_plan, issues = feedback
        errors = "\n".join(f"- [{i.code}] {i.path or '-'}: {i.message}" for i in issues)
        user += f"\n\n[이전 계획의 검증 오류 — 모두 고쳐서 다시 작성]\n{errors}"
        if previous_plan is not None:
            user += f"\n\n[이전 계획]\n{_json(previous_plan)}"
    return system, user


def explain_prompt(facts: dict[str, Any]) -> tuple[str, str]:
    system = """너는 공간 분석 결과를 시민과 정책 담당자에게 설명하는 분석가다. 주어진 결과 JSON의 수치만 사용해 한국어로 3~5문장 요약(summary)을 쓴다.

[규칙]
1. 결과 JSON에 없는 수치나 사실을 만들지 않는다.
2. 지표의 의미와 가장 부족한 행정동 몇 곳을 구체적인 수치와 함께 말한다.
3. 중요한 한계(기준 시점 차이, 제외된 데이터 등)가 있으면 한 문장으로 언급한다."""
    return system, f"[분석 결과]\n{_json(facts)}"
