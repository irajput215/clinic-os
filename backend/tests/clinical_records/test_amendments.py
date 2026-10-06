"""F6-F9, R6-R9 — amendments: a new version with provenance, never an in-place mutation.

Design: `docs/features/06-clinical-records/03-design.md` §"Constraints, indexes and read order" and
§"Failure behaviour"; requirements R6, R7, R8, R9. The reconstruct-the-current-position case is the
one the delivery contract names explicitly: a chain walk that rebuilds the clinical position from
the rows themselves.
"""

import threading
import uuid

import pytest
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError

from app.core.db import engine
from tests.clinical_records.conftest import (
    BLANK_SOAP_SURFACES,
    ClinicalApi,
    ClinicalTenant,
    assert_blank_narrative_refusal,
    created_record,
)


def test_amendment_creates_new_version_with_provenance(
    clinical: ClinicalApi, tenant: ClinicalTenant
) -> None:
    """F6 / R6: a new row with `version + 1`, `supersedes_version`, author and reason."""
    record = created_record(clinical.create_record(tenant.owner, tenant.patient))
    assert clinical.sign(tenant.owner, record["id"]).status_code == 200

    amended = clinical.amend(
        tenant.owner,
        record["id"],
        body="Correction: the headache began four days ago, not three.",
        amendment_reason="Patient corrected the onset date",
    )
    assert amended.status_code == 201, amended.text
    body = amended.json()

    assert body["current_version"] == 2
    assert body["signed_at"] is not None
    versions = body["versions"]
    assert [version["version"] for version in versions] == [1, 2]
    assert versions[1]["supersedes_version"] == 1
    assert versions[1]["amendment_reason"] == "Patient corrected the onset date"
    assert versions[1]["author_id"] == str(tenant.owner.user_id)
    # Version 1 is still readable, byte for byte.
    assert versions[0]["body"] != versions[1]["body"]
    rows = clinical.version_rows(tenant.tenant_id, record["id"])
    assert rows[0]["body"] == versions[0]["body"]


def test_amendment_reason_required_from_version_two(
    clinical: ClinicalApi, tenant: ClinicalTenant
) -> None:
    """F7 / R7: an amendment without a reason is `422 AMENDMENT_REASON_REQUIRED`, zero rows."""
    record = created_record(clinical.create_record(tenant.owner, tenant.patient))
    assert clinical.sign(tenant.owner, record["id"]).status_code == 200

    refused = clinical.amend(tenant.owner, record["id"], body="Correction")

    assert refused.status_code == 422, refused.text
    assert refused.json()["detail"]["code"] == "AMENDMENT_REASON_REQUIRED"
    assert clinical.row_counts(tenant.tenant_id) == (1, 1)


def test_append_rejects_a_blank_soap_narrative(
    clinical: ClinicalApi, tenant: ClinicalTenant
) -> None:
    """R6/R3: neither an edit nor an amendment may append a version with an empty narrative."""
    unsigned = created_record(clinical.create_record(tenant.owner, tenant.patient))
    signed = created_record(clinical.create_record(tenant.owner, tenant.patient))
    assert clinical.sign(tenant.owner, signed["id"]).status_code == 200

    for soap in BLANK_SOAP_SURFACES:
        edited = clinical.patch_record(
            tenant.owner,
            unsigned["id"],
            soap=soap,
            amendment_reason="Clarified the history",
        )
        assert edited.status_code == 422, edited.text
        assert_blank_narrative_refusal(edited.json())

        amended = clinical.amend(
            tenant.owner,
            signed["id"],
            soap=soap,
            amendment_reason="Clarified the history",
        )
        assert amended.status_code == 422, amended.text
        assert_blank_narrative_refusal(amended.json())

    blank_body = clinical.amend(
        tenant.owner,
        signed["id"],
        body=" \t ",
        amendment_reason="Clarified the history",
    )
    assert blank_body.status_code == 422, blank_body.text

    assert clinical.row_counts(tenant.tenant_id) == (2, 2)


def test_version_one_preserved_byte_for_byte(
    clinical: ClinicalApi, tenant: ClinicalTenant
) -> None:
    """F9 / R6: the original version's bytes are untouched by an amendment."""
    original = "Assessment: tension headache. Plan: analgesia."
    record = created_record(
        clinical.create_record(tenant.owner, tenant.patient, body=original)
    )
    assert clinical.sign(tenant.owner, record["id"]).status_code == 200
    assert (
        clinical.amend(
            tenant.owner,
            record["id"],
            body="Assessment: migraine without aura. Plan: triptan.",
            amendment_reason="Specialist review changed the assessment",
        ).status_code
        == 201
    )

    version_one = clinical.read_version(tenant.owner, record["id"], 1)
    assert version_one.status_code == 200, version_one.text
    assert version_one.json()["body"] == original

    rows = clinical.version_rows(tenant.tenant_id, record["id"])
    assert rows[0]["body"] == original


def test_amendment_chain_reconstructs_the_current_position(
    clinical: ClinicalApi, tenant: ClinicalTenant
) -> None:
    """R6-R9: walking `supersedes_version` from the newest row rebuilds the clinical position."""
    first = "Version one narrative."
    record = created_record(
        clinical.create_record(tenant.owner, tenant.patient, body=first)
    )
    assert clinical.sign(tenant.owner, record["id"]).status_code == 200
    second = "Version two narrative."
    third = "Version three narrative."
    assert (
        clinical.amend(
            tenant.owner,
            record["id"],
            body=second,
            amendment_reason="Second version reason",
        ).status_code
        == 201
    )
    final = clinical.amend(
        tenant.owner,
        record["id"],
        body=third,
        amendment_reason="Third version reason",
    )
    assert final.status_code == 201, final.text
    assert final.json()["current_version"] == 3

    rows = clinical.version_rows(tenant.tenant_id, record["id"])

    # The chain is total and contiguous from version 1 to the current version.
    assert [row["version"] for row in rows] == [1, 2, 3]
    assert rows[0]["supersedes_version"] is None
    assert [row["supersedes_version"] for row in rows[1:]] == [1, 2]

    # Walking backwards from the current version reaches every earlier one and stops at the root.
    by_version = {row["version"]: row for row in rows}
    walked: list[int] = []
    cursor: int | None = by_version[max(by_version)]["version"]
    while cursor is not None:
        walked.append(cursor)
        cursor = by_version[cursor]["supersedes_version"]
    assert walked == [3, 2, 1]

    # The current clinical position is the newest row, and it is the one the record points at.
    record_row = clinical.record_row(tenant.tenant_id, record["id"])
    assert record_row is not None
    current = by_version[int(record_row["current_version"])]
    assert current["body"] == third

    # Byte-for-byte history: every earlier narrative is still exactly what was written.
    assert [row["body"] for row in rows] == [first, second, third]


def test_read_api_returns_versions_in_ascending_order(
    clinical: ClinicalApi, tenant: ClinicalTenant
) -> None:
    """F10 / R9: the read path is deterministic — `ORDER BY version ASC`."""
    record = created_record(clinical.create_record(tenant.owner, tenant.patient))
    assert clinical.sign(tenant.owner, record["id"]).status_code == 200
    for index in range(2, 6):
        assert (
            clinical.amend(
                tenant.owner,
                record["id"],
                body=f"Version {index} narrative.",
                amendment_reason=f"Reason {index}",
            ).status_code
            == 201
        )

    response = clinical.read_record(tenant.owner, record["id"])
    assert response.status_code == 200, response.text
    assert [version["version"] for version in response.json()["versions"]] == [
        1,
        2,
        3,
        4,
        5,
    ]


def test_unique_constraint_rejects_a_duplicate_version(
    clinical: ClinicalApi, tenant: ClinicalTenant
) -> None:
    """R8: one row per `(record, version)`, enforced by the database, not by the service."""
    record = created_record(clinical.create_record(tenant.owner, tenant.patient))

    with pytest.raises(IntegrityError) as collision:
        with engine.begin() as conn:
            conn.execute(
                text(
                    "INSERT INTO clinical_record_versions"
                    " (tenant_id, clinical_record_id, version, body, body_format,"
                    "  author_id, created_at)"
                    " VALUES (:tenant_id, :record_id, 1, 'duplicate', 'PLAIN',"
                    "  :author_id, now())"
                ),
                {
                    "tenant_id": tenant.tenant_id,
                    "record_id": record["id"],
                    "author_id": tenant.owner.user_id,
                },
            )

    assert "uq_clinical_record_versions_tenant_record_version" in str(collision.value)


def test_concurrent_amendments_do_not_lose_an_update(
    clinical: ClinicalApi, tenant: ClinicalTenant
) -> None:
    """R8 / S16: two racing appends leave a contiguous chain and one authoritative pointer.

    The assertion is deliberately about the *invariant*, not about which writer wins: the unique
    constraint makes a lost update impossible, because no statement ever rewrites an existing
    version row. Either both appends land as versions 2 and 3, or one of them is refused with a
    conflict after its single retry.
    """
    from app.modules.clinical_records import service as clinical_service

    record = created_record(clinical.create_record(tenant.owner, tenant.patient))
    assert clinical.sign(tenant.owner, record["id"]).status_code == 200
    record_id = record["id"]

    barrier = threading.Barrier(2)
    bodies = ["Racing amendment A", "Racing amendment B"]
    outcomes: list[str] = []

    def append(body: str) -> None:
        from app.modules.clinical_records.schemas import ClinicalRecordAppend

        context = clinical_service.AuditContext(
            actor_id=tenant.owner.user_id, actor_role="PRACTICE_OWNER"
        )
        barrier.wait(timeout=10)
        try:
            outcome = clinical_service.append_version(
                tenant_id=tenant.tenant_id,
                context=context,
                record_id=uuid.UUID(record_id),
                append_in=ClinicalRecordAppend(
                    body=body, amendment_reason=f"reason for {body}"
                ),
                amendment=True,
            )
            outcomes.append(outcome.status)
        except clinical_service.VersionConflict:
            outcomes.append(clinical_service.VERSION_CONFLICT)

    threads = [threading.Thread(target=append, args=(body,)) for body in bodies]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=30)

    assert len(outcomes) == 2, outcomes
    rows = clinical.version_rows(tenant.tenant_id, record_id)
    versions = [row["version"] for row in rows]
    assert versions == list(range(1, len(versions) + 1)), versions
    assert len(rows) >= 2, rows  # at least one raced append landed
    row = clinical.record_row(tenant.tenant_id, record_id)
    assert row is not None
    assert int(row["current_version"]) == max(versions)
