"""Request and response models for questionnaires. Strict: unknown fields are refused."""

import uuid
from datetime import datetime
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

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
    # Clinic-made forms (R6), newest first. Declared after the classes it names (see the end of file).
    clinic_responses: list[ClinicFormResponseRead] = []


class AcknowledgeRequest(_Strict):
    action_code: Annotated[str, Field(pattern=r"^[A-Z][A-Z0-9_]{0,63}$")]


# -- clinic-made forms (R6) --------------------------------------------------------------------

FieldType = Literal["TEXT", "LONG_TEXT", "CHOICE", "SCALE", "DATE", "YES_NO"]
_FIELD_ID = Annotated[str, Field(pattern=r"^[a-z][a-z0-9_]{0,31}$")]
_LABEL = Annotated[str, Field(min_length=1, max_length=200)]
_OPTION = Annotated[str, Field(min_length=1, max_length=100)]


class ClinicFormField(_Strict):
    """One field of a clinic form. The vocabulary is deliberately small (R6)."""

    id: _FIELD_ID
    label: _LABEL
    type: FieldType
    required: bool = False
    help: Annotated[str | None, Field(max_length=300)] = None
    options: Annotated[list[_OPTION], Field(max_length=20)] = []
    scale_min: Annotated[int | None, Field(ge=0, le=10)] = None
    scale_max: Annotated[int | None, Field(ge=0, le=10)] = None

    @model_validator(mode="after")
    def _type_rules(self) -> ClinicFormField:
        if self.type == "CHOICE":
            if len(self.options) < 2 or len(set(self.options)) != len(self.options):
                raise ValueError("a choice field needs at least two distinct options")
        elif self.options:
            raise ValueError("only a choice field has options")
        if self.type == "SCALE":
            if (
                self.scale_min is None
                or self.scale_max is None
                or self.scale_min >= self.scale_max
            ):
                raise ValueError(
                    "a scale field needs scale_min below scale_max (0 to 10)"
                )
        elif self.scale_min is not None or self.scale_max is not None:
            raise ValueError("only a scale field has a range")
        return self


class ClinicFormWrite(_Strict):
    title: Annotated[str, Field(min_length=3, max_length=120)]
    description: Annotated[str | None, Field(max_length=500)] = None
    fields: Annotated[list[ClinicFormField], Field(min_length=1, max_length=50)]

    @model_validator(mode="after")
    def _unique_ids(self) -> ClinicFormWrite:
        ids = [f.id for f in self.fields]
        if len(set(ids)) != len(ids):
            raise ValueError("each field needs its own id")
        return self


class ClinicFormRead(_Strict):
    id: uuid.UUID
    status: Literal["ACTIVE", "RETIRED"]
    version_id: uuid.UUID
    version: int
    title: str
    description: str | None
    fields: list[ClinicFormField]
    published_at: datetime


AnswerValue = str | int | bool | None


class ClinicFormResponseCreate(_Strict):
    form_version_id: uuid.UUID
    answers: Annotated[dict[str, AnswerValue], Field(max_length=50)]
    corrects_id: uuid.UUID | None = None


class ClinicFormResponseRead(_Strict):
    id: uuid.UUID
    patient_id: uuid.UUID
    form_id: uuid.UUID
    form_version_id: uuid.UUID
    version: int
    title: str
    fields: list[ClinicFormField]
    answers: dict[str, AnswerValue]
    entered_by: uuid.UUID
    corrects_id: uuid.UUID | None
    corrected_by_id: uuid.UUID | None = None
    created_at: datetime


PatientForms.model_rebuild()
