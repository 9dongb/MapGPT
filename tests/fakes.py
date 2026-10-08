import math
import re
import zlib

from pydantic import BaseModel

from app.catalog.definitions import SEOUL
from app.domain.plan import AnalysisPlan, Region
from app.domain.state import DatasetSelection, Explanation, InterpretedQuery
from app.llm.embeddings import EMBEDDING_DIMENSIONS
from tests.support import load_plan


class FakeLLM:
    """출력 타입별로 미리 정한 구조화 응답을 순서대로 돌려주는 LLM. 마지막 응답은 계속 반복한다."""

    provider = "fake"
    model = "fake-model"

    def __init__(self, responses: dict[type[BaseModel], list[BaseModel | Exception]]):
        self._responses = {output_type: list(items) for output_type, items in responses.items()}
        self.calls: list[tuple[type[BaseModel], str, str]] = []

    def generate(self, *, system: str, user: str, output_type: type[BaseModel]) -> BaseModel:
        self.calls.append((output_type, system, user))
        queue = self._responses[output_type]
        item = queue.pop(0) if len(queue) > 1 else queue[0]
        if isinstance(item, Exception):
            raise item
        return item

    def prompts_for(self, output_type: type[BaseModel]) -> list[str]:
        return [user for called_type, _, user in self.calls if called_type is output_type]


class FakeEmbedder:
    """단어 해싱으로 만든 결정론적 임베딩. 같은 단어를 많이 공유할수록 코사인 유사도가 높다."""

    def __init__(self, model: str = "fake-embedding"):
        self.model = model
        self.calls: list[list[str]] = []

    def embed(self, texts: list[str]) -> list[list[float]]:
        self.calls.append(list(texts))
        return [_hashed_vector(text) for text in texts]


def _hashed_vector(text: str) -> list[float]:
    vector = [0.0] * EMBEDDING_DIMENSIONS
    for token in re.findall(r"\w+", text.lower()):
        vector[zlib.crc32(token.encode()) % EMBEDDING_DIMENSIONS] += 1.0
    norm = math.sqrt(sum(value * value for value in vector)) or 1.0
    return [value / norm for value in vector]


def interpreted(region: str = SEOUL.name, **overrides) -> InterpretedQuery:
    data = {
        "intent": "supply_demand_gap",
        "unsupported_reason": None,
        "region": Region(name=region, level="sido"),
        "analysis_unit": "emd",
        "restated_question": "서울특별시 행정동별 0~5세 인구 1,000명당 어린이집 수가 적은 곳",
        "key_concepts": ["어린이집 위치", "0~5세 인구", "행정동 경계"],
        "assumptions": ["'어린이'를 만 0~5세로 해석"],
    }
    data.update(overrides)
    return InterpretedQuery.model_validate(data)


def daycare_llm(**overrides: list[BaseModel | Exception]) -> FakeLLM:
    """첫 Use Case를 올바르게 처리하는 LLM 응답. 키워드 인자로 단계별 응답을 바꾼다."""
    responses: dict[type[BaseModel], list[BaseModel | Exception]] = {
        InterpretedQuery: [interpreted()],
        DatasetSelection: [
            DatasetSelection(
                datasets=["emd_boundary", "population_by_age", "daycare_facility"],
                rationale="경계, 수요(0~5세 인구), 공급(어린이집)",
            )
        ],
        AnalysisPlan: [load_plan()],
        Explanation: [Explanation(summary="카동이 가장 부족합니다.")],
    }
    types = {
        "interpreted": InterpretedQuery,
        "selection": DatasetSelection,
        "plans": AnalysisPlan,
        "explanation": Explanation,
    }
    for name, items in overrides.items():
        responses[types[name]] = items
    return FakeLLM(responses)
