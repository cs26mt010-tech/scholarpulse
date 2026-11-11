"""Request schemas for resources endpoints."""
from typing import List, Optional
from pydantic import BaseModel, Field

class ResourceUpdateRequest(BaseModel):
    title: Optional[str] = Field(None, min_length=3, max_length=200)
    course_code: Optional[str] = None
    tags: Optional[List[str]] = None
