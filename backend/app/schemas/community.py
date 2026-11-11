"""Request schemas for community endpoints."""
from typing import List, Optional
from pydantic import BaseModel, Field

class RatingRequest(BaseModel):
    score: int = Field(..., ge=1, le=5)

class CommentCreateRequest(BaseModel):
    body: str = Field(..., min_length=2, max_length=2000)
