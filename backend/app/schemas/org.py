from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field


class OrganizationOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    slug: str
    name_ar: str
    name_en: str
    commercial_registration: str | None = None
    city: str | None = None
    country: str | None = None
    website: str | None = None
    employee_count: int | None = None
    years_active: int | None = None
    annual_projects: int | None = None
    primary_segment: str | None = None
    notes: str | None = None
    profile_completeness: float = 0.0


class OrganizationUpdate(BaseModel):
    name_ar: str | None = Field(default=None, max_length=200)
    name_en: str | None = Field(default=None, max_length=200)
    commercial_registration: str | None = Field(default=None, max_length=60)
    city: str | None = Field(default=None, max_length=120)
    country: str | None = Field(default=None, max_length=120)
    website: str | None = Field(default=None, max_length=200)
    employee_count: int | None = Field(default=None, ge=0)
    years_active: int | None = Field(default=None, ge=0)
    annual_projects: int | None = Field(default=None, ge=0)
    primary_segment: str | None = Field(default=None, max_length=120)
    notes: str | None = None
