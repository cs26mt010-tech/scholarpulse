
from typing import List, Optional

from pydantic import BaseModel, Field


class CollectionCreateRequest(BaseModel):
    title: str = Field(..., min_length=3, max_length=150)
    description: Optional[str] = Field(None, max_length=1000)
    course_code: Optional[str] = None
    is_public: bool = True
    is_official: bool = False


class CollectionUpdateRequest(BaseModel):
    title: Optional[str] = Field(None, min_length=3, max_length=150)
    description: Optional[str] = Field(None, max_length=1000)
    ordered_resource_ids: Optional[List[int]] = None


class CollectionItemAddRequest(BaseModel):
    resource_id: int
    position: Optional[int] = None
    notes: Optional[str] = Field(None, max_length=300)
