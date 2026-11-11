"""Request schemas for auth endpoints."""
from typing import List, Optional
from pydantic import BaseModel, Field

class UserRegisterRequest(BaseModel):
    username: str = Field(..., min_length=3, max_length=50)
    email: str = Field(..., min_length=5, max_length=120)
    password: str = Field(..., min_length=8, max_length=128)
    bio: Optional[str] = Field(None, max_length=500)
    consent_accepted: bool = Field(...)

class EmailOnlyRequest(BaseModel):
    email: str = Field(..., min_length=5, max_length=120)

class EmailVerificationRequest(BaseModel):
    email: str = Field(..., min_length=5, max_length=120)
    code: str = Field(..., min_length=6, max_length=6)

class UserLoginRequest(BaseModel):
    email: str
    password: str
    remember_me: bool = False

class UserUpdateRequest(BaseModel):
    username: Optional[str] = Field(None, min_length=3, max_length=50)
    bio: Optional[str] = Field(None, max_length=500)
    programme: Optional[str] = Field(None, max_length=120)
    email_notifications: Optional[bool] = None
    public_profile: Optional[bool] = None

class PasswordChangeRequest(BaseModel):
    current_password: str
    new_password: str = Field(..., min_length=8, max_length=128)
