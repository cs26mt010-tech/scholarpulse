"""Request schemas for ai endpoints."""
from pydantic import BaseModel, Field


class AIAskRequest(BaseModel):
    question: str = Field(..., min_length=1, max_length=500)
    scope_type: str = Field(..., description="resource | collection | course")
    scope_id: str = Field(...)
    simulate_failure: bool = False
