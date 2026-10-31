"""Practice settings and setup checklist shapes (docs3 feature 01)."""

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.modules.practice.models import MIN_ADULT_RETENTION_YEARS, STAGING_ROLES

StagingRole = Literal["NURSE", "DOCTOR", "ADMINISTRATOR"]


class PracticeSettingsRead(BaseModel):
    draft_staging_roles: list[StagingRole]
    adult_retention_years: int
    #: `None` until the settings were first saved (the setup step stays undone).
    updated_at: datetime | None


class PracticeSettingsUpdate(BaseModel):
    """Both fields, every time: the Practice tab saves them together. Unknown fields are refused."""

    model_config = ConfigDict(extra="forbid")

    draft_staging_roles: list[StagingRole] = Field(min_length=1, max_length=3)
    adult_retention_years: int = Field(ge=MIN_ADULT_RETENTION_YEARS, le=100)

    @field_validator("draft_staging_roles")
    @classmethod
    def _nurses_always(cls, roles: list[str]) -> list[str]:
        if "NURSE" not in roles:
            raise ValueError("Nurses always stage drafts; keep NURSE in the list.")
        return [r for r in STAGING_ROLES if r in roles]


StepKey = Literal[
    "clinic_name",
    "hours",
    "team_invited",
    "prescriber_ready",
    "workflow",
    "consents",
    "permissions_reviewed",
    "booking_page",
    "integrations",
]


class SetupStep(BaseModel):
    key: StepKey
    status: Literal["done", "todo", "optional", "informational"]
    required: bool


class SetupRead(BaseModel):
    """The setup checklist (R1-R3), every step derived from live data."""

    steps: list[SetupStep]
    required_done: int
    required_total: int
    ready: bool
