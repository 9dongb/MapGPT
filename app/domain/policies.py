"""Intent별 명시적 분석 정책.

LLM 프롬프트에 제공하고, Plan Validator가 준수 여부를 결정론적으로 검사한다.
"""

from app.domain.base import StrictModel
from app.domain.enums import AnalysisIntent, SortOrder


class IntentPolicy(StrictModel):
    intent: AnalysisIntent
    title: str
    description: str
    ratio_scale: float
    rank_order: SortOrder
    interpretation: str
    definitions: list[str]
    limitations: list[str]


POLICIES: dict[AnalysisIntent, IntentPolicy] = {
    AnalysisIntent.SUPPLY_DEMAND_GAP: IntentPolicy(
        intent=AnalysisIntent.SUPPLY_DEMAND_GAP,
        title="수요 대비 시설 공급 부족",
        description=(
            "분석 단위별 공급 시설 수를 수요 인구로 나누고 1,000을 곱한 '수요 인구 1,000명당 시설 수'를 "
            "계산한 뒤, 값이 작은 순서(오름차순)로 순위를 매긴다."
        ),
        ratio_scale=1000,
        rank_order=SortOrder.ASC,
        interpretation="값이 작을수록 수요 인구 대비 시설 공급이 부족하다.",
        definitions=[
            "'부족하다'는 수요 인구 1,000명당 공급 시설 수가 상대적으로 작다는 뜻이다 (시설 수 ÷ 수요 인구 × 1,000).",
            "'어린이 인구'는 어린이집 이용 대상인 만 0~5세 인구로 정의한다.",
        ],
        limitations=[
            "시설 수만 반영하며 정원·현원 등 시설 규모는 반영하지 않는다.",
            "행정동 경계를 넘어 다른 동의 시설을 이용하는 행태는 반영하지 않는다.",
            "수요 인구가 적은 행정동은 시설 1개 차이로도 지표가 크게 변한다.",
        ],
    ),
}
