import json
from pathlib import Path
from typing import Any

from app.domain.plan import AnalysisPlan

FIXTURES = Path(__file__).parent / "fixtures"
QUESTION = "서울에서 어린이 인구 대비 어린이집이 부족한 행정동을 알려줘."


def load_plan_dict() -> dict[str, Any]:
    return json.loads((FIXTURES / "plan_daycare.json").read_text(encoding="utf-8"))


def load_plan(**overrides: Any) -> AnalysisPlan:
    data = load_plan_dict()
    data.update(overrides)
    return AnalysisPlan.model_validate(data)
