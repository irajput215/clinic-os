"""Request and response models for questionnaires. Strict: unknown fields are refused."""

import uuid
from datetime import datetime
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field

InstrumentCode = Literal["PHQ9", "GAD7", "K10"]


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


class OptionRead(_Strict):
    label: str
    value: int


class BandRead(_Strict):
    code: str
    label: str
    low: int
    high: int


class InstrumentRead(_Strict):
    code: InstrumentCode
    version: str
    title: str
    stem: str
    items: list[str]
    options: list[OptionRead]
    bands: list[BandRead]
    difficulty_question: str | None
    difficulty_options: list[str]
    min_score: int
    max_score: int


class AcknowledgeActionRead(_Strict):
    code: str
    label: str


class InstrumentCatalogue(_Strict):
    instruments: list[InstrumentRead]
    acknowledge_actions: list[AcknowledgeActionRead]


class FormResponseCreate(_Strict):
    """No `tenant_id`, `patient_id` (it is the path), score, band or author: all the server's."""

    instrument: InstrumentCode
    instrument_version: Annotated[str, Field(max_length=16)]
    answers: Annotated[list[int], Field(min_length=1, max_length=20)]
    difficulty: Annotated[int | None, Field(ge=0, le=3)] = None
    corrects_id: uuid.UUID | None = None


class SafetyFlagRead(_Strict):
    id: uuid.UUID
    response_id: uuid.UUID
    rule_code: str
    description: str
    status: Literal["OPEN", "ACKNOWLEDGED"]
    raised_at: datetime
    acknowledged_by: uuid.UUID | None
    acknowledged_at: datetime | None
    action_code: str | None


class FormResponseRead(_Strict):
    id: uuid.UUID
    patient_id: uuid.UUID
    instrument: InstrumentCode
    instrument_version: str
    answers: list[int]
    difficulty: int | None
    total_score: int
    band: str
    band_label: str
    entered_by: uuid.UUID
    corrects_id: uuid.UUID | None
    corrected_by_id: uuid.UUID | None = None
    created_at: datetime
    flags: list[SafetyFlagRead]


class PatientForms(_Strict):
    responses: list[FormResponseRead]
    open_flags: list[SafetyFlagRead]


class AcknowledgeRequest(_Strict):
    action_code: Annotated[str, Field(pattern=r"^[A-Z][A-Z0-9_]{0,63}$")]
