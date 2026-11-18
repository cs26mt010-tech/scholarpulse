"""Request schemas for moderation endpoints."""
from typing import Optional

from pydantic import BaseModel, Field


class ReportCreateRequest(BaseModel):
    target_type: str = Field(..., description="resource | comment")
    target_id: int
    reason: str
    details: Optional[str] = Field(None, max_length=1000)

class ModerationActionRequest(BaseModel):
    action: str = Field(..., description="hide | restore | remove | dismiss")
    note: Optional[str] = Field(None, max_length=500)

REPORT_REASONS = ("copyright_concern", "incorrect_or_misleading", "low_quality_or_spam", "inappropriate_content")

