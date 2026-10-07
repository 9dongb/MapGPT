from pydantic import BaseModel, ConfigDict


class StrictModel(BaseModel):
    """Core Contract 공통 베이스. 정의되지 않은 필드는 거부한다."""

    model_config = ConfigDict(extra="forbid")
