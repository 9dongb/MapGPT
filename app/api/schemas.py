from pydantic import BaseModel, Field

from app.domain.enums import RunStatus
from app.domain.results import FinalResponse
from app.domain.state import WorkflowError


class AnalysisRequest(BaseModel):
    question: str = Field(min_length=1, max_length=500)


class AnalysisResponse(BaseModel):
    run_id: str
    status: RunStatus
    result: FinalResponse | None
    errors: list[WorkflowError]
