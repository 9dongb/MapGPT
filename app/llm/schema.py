"""Pydantic 모델을 LLM Structured Output 호환 JSON Schema로 변환한다.

OpenAI strict 모드와 Ollama(JSON Schema → 문법) 모두에서 쓸 수 있도록:
- 모든 object에 additionalProperties=false, 모든 property를 required로 둔다.
- oneOf(+discriminator) → anyOf, const → enum으로 바꾼다.
- 수치·길이·패턴 제약과 default를 제거한다. 제거한 제약은 응답 수신 후 Pydantic이 다시 검증한다.
"""

from typing import Any

from pydantic import BaseModel

_DROPPED_KEYWORDS = {
    "title",
    "default",
    "discriminator",
    "minimum",
    "maximum",
    "exclusiveMinimum",
    "exclusiveMaximum",
    "multipleOf",
    "minLength",
    "maxLength",
    "pattern",
    "minItems",
    "maxItems",
    "uniqueItems",
}


def to_llm_json_schema(model: type[BaseModel]) -> dict[str, Any]:
    return _convert(model.model_json_schema())


def _convert(node: Any) -> Any:
    if isinstance(node, list):
        return [_convert(item) for item in node]
    if not isinstance(node, dict):
        return node

    if "$ref" in node:
        # strict 모드는 $ref 옆에 다른 키워드를 허용하지 않는다.
        return {"$ref": node["$ref"]}

    converted: dict[str, Any] = {}
    for key, value in node.items():
        if key in _DROPPED_KEYWORDS:
            continue
        if key == "oneOf":
            converted["anyOf"] = _convert(value)
        elif key == "const":
            converted["enum"] = [value]
        elif key in ("properties", "$defs"):
            converted[key] = {name: _convert(sub) for name, sub in value.items()}
        else:
            converted[key] = _convert(value)

    if converted.get("type") == "object" and "properties" in converted:
        converted["additionalProperties"] = False
        converted["required"] = list(converted["properties"])
    return converted
