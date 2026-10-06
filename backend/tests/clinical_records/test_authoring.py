"""F1-F3, R1-R3 — authoring: the create path, strict schema, and the single narrative column.

Design: `docs/features/06-clinical-records/03-design.md` §"Endpoints"; requirements R1, R2, R3.
Every case drives the real API and then inspects the row as the owner connection, which bypasses
row-level security: the assertion is about the row that exists, not the row a policy would show.
"""

import uuid

from sqlalchemy import text

from app.core.db import engine
from tests.clinical_records.conftest import (
    BLANK_SOAP_SURFACES,
    DEFAULT_NOTE_BODY,
    ClinicalApi,
    ClinicalTenant,
    assert_blank_narrative_refusal,
    created_record,
)


def test_create_note_tenant_and_author_from_session(
    clinical: ClinicalApi, tenant: ClinicalTenant
) -> None:
    """F1 / R1: `201`, `version = 1`, unsigned, tenant and author from the session."""
    response = clinical.create_record(tenant.owner, tenant.patient)
    body = created_record(response)

    assert body["patient_id"] == str(tenant.patient)
    assert body["record_type"] == "NOTE"
    assert body["author_id"] == str(tenant.owner.user_id)
    assert body["current_version"] == 1
    assert body["signed_at"] is None
    assert [version["version"] for version in body["versions"]] == [1]
    assert body["versions"][0]["body"] == DEFAULT_NOTE_BODY
    assert body["versions"][0]["author_id"] == str(tenant.owner.user_id)
    assert body["versions"][0]["supersedes_version"] is None

    # The row the owner connection sees carries the session's tenant, and no other.
    row = clinical.record_row(tenant.tenant_id, body["id"])
    assert row is not None
    assert str(row["tenant_id"]) == str(tenant.tenant_id)
    assert str(row["patient_id"]) == str(tenant.patient)
    assert clinical.row_counts(tenant.tenant_id) == (1, 1)


def test_create_note_rejects_unknown_fields(
    clinical: ClinicalApi, tenant: ClinicalTenant
) -> None:
    """F2 / R2 / S5: a body that tries to set attribution or lineage is `422`, with zero rows."""
    response = clinical.create_record(
        tenant.owner,
        tenant.patient,
        tenant_id=str(uuid.uuid4()),
        author_id=str(uuid.uuid4()),
        signed_at="2026-01-01T00:00:00Z",
        version=7,
        current_version=7,
        id=str(uuid.uuid4()),
    )

    assert response.status_code == 422, response.text
    assert clinical.row_counts(tenant.tenant_id) == (0, 0)


def test_create_note_rejects_a_missing_or_doubled_narrative(
    clinical: ClinicalApi, tenant: ClinicalTenant
) -> None:
    """R2/R3: exactly one narrative. Neither, both, or an empty SOAP surface is `422`."""
    neither = clinical.create_record(tenant.owner, tenant.patient, body=None)
    assert neither.status_code == 422, neither.text

    both = clinical.create_record(
        tenant.owner,
        tenant.patient,
        body="body and soap",
        soap={"subjective": "both"},
    )
    assert both.status_code == 422, both.text

    empty_soap = clinical.create_record(
        tenant.owner, tenant.patient, body=None, soap={}
    )
    assert empty_soap.status_code == 422, empty_soap.text

    assert clinical.row_counts(tenant.tenant_id) == (0, 0)


def test_create_note_rejects_a_blank_soap_narrative(
    clinical: ClinicalApi, tenant: ClinicalTenant
) -> None:
    """R2/R3: a SOAP surface whose every section is blank is `422`, with zero rows written."""
    for soap in BLANK_SOAP_SURFACES:
        refused = clinical.create_record(
            tenant.owner, tenant.patient, body=None, soap=soap
        )
        assert refused.status_code == 422, refused.text
        assert_blank_narrative_refusal(refused.json())

    blank_body = clinical.create_record(tenant.owner, tenant.patient, body="  \n ")
    assert blank_body.status_code == 422, blank_body.text

    assert clinical.row_counts(tenant.tenant_id) == (0, 0)


def test_create_note_keeps_a_blank_section_beside_a_written_one(
    clinical: ClinicalApi, tenant: ClinicalTenant
) -> None:
    """`docs2/sdlc/03-consult-notes/api.md`: every section sent is rendered, blank or not.

    The blank-narrative refusal is about a note with nothing in it, not about a note with one
    unwritten section.
    """
    response = clinical.create_record(
        tenant.owner,
        tenant.patient,
        body=None,
        soap={"subjective": "Headache for three days.", "objective": "  "},
    )
    version = created_record(response)["versions"][0]

    assert "Headache for three days." in version["body"]
    assert "## Objective" in version["body"]


def test_narrative_is_single_body_column(
    clinical: ClinicalApi, tenant: ClinicalTenant
) -> None:
    """F3 / R3: the SOAP authoring surface serialises into the one `body` column."""
    response = clinical.create_record(
        tenant.owner,
        tenant.patient,
        body=None,
        soap={
            "subjective": "Headache for three days.",
            "objective": "Alert, afebrile.",
            "assessment": "Tension headache.",
            "plan": "Analgesia, review in two weeks.",
        },
    )
    body = created_record(response)
    version = body["versions"][0]

    assert version["body_format"] == "MARKDOWN"
    assert "## Subjective" in version["body"]
    assert "## Plan" in version["body"]
    assert "Tension headache." in version["body"]
    # The stored narrative is one field, and there is no SOAP column anywhere.
    with engine.connect() as conn:
        columns = {
            row[0]
            for row in conn.execute(
                text(
                    "SELECT column_name FROM information_schema.columns"
                    " WHERE table_schema = 'public'"
                    " AND table_name = 'clinical_record_versions'"
                )
            )
        }
    assert columns.isdisjoint({"subjective", "objective", "assessment", "plan"})


def test_each_record_is_a_separate_row(
    clinical: ClinicalApi, tenant: ClinicalTenant
) -> None:
    """R3: a second note for the same patient is a second record, not a version of the first."""
    first = created_record(clinical.create_record(tenant.owner, tenant.patient))
    second = created_record(
        clinical.create_record(tenant.owner, tenant.patient, body="Second entry.")
    )

    assert first["id"] != second["id"]
    assert clinical.row_counts(tenant.tenant_id) == (2, 2)


def test_create_for_a_patient_outside_the_tenant_is_404(
    clinical: ClinicalApi, two_tenants: tuple[ClinicalTenant, ClinicalTenant]
) -> None:
    """R10: a patient of another tenant does not exist for this caller — `404`, never `403`."""
    first, second = two_tenants

    response = clinical.create_record(first.owner, second.patient)

    assert response.status_code == 404, response.text
    assert clinical.row_counts(first.tenant_id) == (0, 0)


def test_record_type_vocabulary_is_closed(
    clinical: ClinicalApi, tenant: ClinicalTenant
) -> None:
    """The CHECK constraint's vocabulary is what the API accepts, and nothing else."""
    accepted = clinical.create_record(
        tenant.owner, tenant.patient, record_type="ADDENDUM"
    )
    assert accepted.status_code == 201, accepted.text

    refused = clinical.create_record(
        tenant.owner, tenant.patient, record_type="PRESCRIPTION"
    )
    assert refused.status_code == 422, refused.text
    assert clinical.row_counts(tenant.tenant_id) == (1, 1)
