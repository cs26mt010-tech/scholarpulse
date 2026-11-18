"""Request schemas for AI endpoints."""

from typing import Literal

from pydantic import BaseModel, Field


class AIAskRequest(BaseModel):
    question: str = Field(..., min_length=1, max_length=500)

    scope_type: Literal[
        "resource",
        "collection",
        "course",
        "general",
    ]

    scope_id: str = "global"
    simulate_failure: bool = False
