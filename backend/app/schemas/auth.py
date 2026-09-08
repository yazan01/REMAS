from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict, EmailStr, Field

from app.models.enums import Locale


class RegisterIn(BaseModel):
    email: EmailStr
    password: str = Field(min_length=8, max_length=128)
    full_name: str = Field(min_length=2, max_length=200)
    organization_name_ar: str = Field(min_length=2, max_length=200)
    organization_name_en: str = Field(min_length=2, max_length=200)
    locale: Locale = Locale.AR


class LoginIn(BaseModel):
    email: EmailStr
    password: str
    mfa_code: str | None = None


class VerifyIn(BaseModel):
    token: str


class TokenOut(BaseModel):
    access_token: str
    token_type: str = "bearer"
    expires_in: int


class UserOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    email: EmailStr
    full_name: str
    role: str
    locale: str
    email_verified_at: datetime | None = None
    organization_id: str
    mfa_enabled: bool = False


class MeOut(BaseModel):
    user: UserOut
    organization_name_ar: str
    organization_name_en: str
    organization_slug: str
    profile_completeness: float
