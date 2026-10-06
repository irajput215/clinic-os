"""F10, F12, F14, R9-R10 — the read path: deterministic order, bounded timeline, `404` isolation.

Design: `docs/features/06-clinical-records/03-design.md` §"Endpoints", §"Deny-by-default request
path". Requirements R9, R10. Cross-tenant is `404`, never `403`: a `403` confirms the record exists.
"""

import uuid

from tests.clinical_records.conftest import ClinicalApi, ClinicalTenant, created_record


def test_missing_version_returns_404(
    clinical: ClinicalApi, tenant: ClinicalTenant
) -> None:
    """F14: one version of one record, and no partial record when it is absent."""
    record = created_record(clinical.create_record(tenant.owner, tenant.patient))

    missing = clinical.read_version(tenant.owner, record["id"], 99)
    assert missing.status_code == 404, missing.text

    present = clinical.read_version(tenant.owner, record["id"], 1)
    assert present.status_code == 200, present.text
    assert present.json()["version"] == 1
    assert present.json()["body"] == record["versions"][0]["body"]


def test_cross_tenant_record_returns_404(
    clinical: ClinicalApi, two_tenants: tuple[ClinicalTenant, ClinicalTenant]
) -> None:
    """F12 / S1 / R10: another tenant's record is `404` on every route, never `403`."""
    first, second = two_tenants
    record = created_record(clinical.create_record(first.owner, first.patient))

    assert clinical.read_record(second.owner, record["id"]).status_code == 404
    assert clinical.read_version(second.owner, record["id"], 1).status_code == 404
    assert (
        clinical.patch_record(
            second.owner,
            record["id"],
            body="Cross-tenant edit",
            amendment_reason="Cross-tenant",
        ).status_code
        == 404
    )
    assert (
        clinical.amend(
            second.owner,
            record["id"],
            body="Cross-tenant amendment",
            amendment_reason="Cross-tenant",
        ).status_code
        == 404
    )
    assert clinical.sign(second.owner, record["id"]).status_code == 404
    assert clinical.timeline(second.owner, first.patient).status_code == 404

    # Nothing of the first tenant's was touched or created for the second.
    assert clinical.row_counts(first.tenant_id) == (1, 1)
    assert clinical.row_counts(second.tenant_id) == (0, 0)


def test_timeline_is_newest_first_and_keyset_paginated(
    clinical: ClinicalApi, tenant: ClinicalTenant
) -> None:
    """US-6: cursor-paginated timeline, no repeats and no gaps across pages."""
    created = [
        created_record(
            clinical.create_record(tenant.owner, tenant.patient, body=f"Entry {index}")
        )
        for index in range(3)
    ]

    first_page = clinical.timeline(tenant.owner, tenant.patient, limit=2)
    assert first_page.status_code == 200, first_page.text
    body = first_page.json()
    assert body["count"] == 3
    assert len(body["data"]) == 2
    assert body["next_cursor"] is not None
    # Newest first, and each entry carries its current version's narrative.
    assert body["data"][0]["id"] == created[2]["id"]
    assert body["data"][0]["latest_version"]["body"] == "Entry 2"

    second_page = clinical.timeline(
        tenant.owner, tenant.patient, limit=2, cursor=body["next_cursor"]
    )
    assert second_page.status_code == 200, second_page.text
    tail = second_page.json()
    assert [entry["id"] for entry in tail["data"]] == [created[0]["id"]]
    assert tail["next_cursor"] is None

    seen = [entry["id"] for entry in body["data"]] + [
        entry["id"] for entry in tail["data"]
    ]
    assert sorted(seen) == sorted(entry["id"] for entry in created)


def test_timeline_refuses_a_forged_or_malformed_cursor(
    clinical: ClinicalApi, tenant: ClinicalTenant
) -> None:
    """The cursor is signed, so a client cannot forge a boundary that skips rows."""
    created_record(clinical.create_record(tenant.owner, tenant.patient))
    page = clinical.timeline(tenant.owner, tenant.patient, limit=1)
    assert page.status_code == 200, page.text
    assert page.json()["next_cursor"] is None

    for cursor in ("not-a-cursor", "AAAA", "eyJjcmVhdGVkX2F0IjogIjIwMjYtMDEtMDEifQ"):
        response = clinical.timeline(tenant.owner, tenant.patient, cursor=cursor)
        assert response.status_code == 422, (cursor, response.text)
        assert response.json()["detail"]["code"] == "INVALID_CURSOR"


def test_timeline_for_an_unknown_patient_is_404(
    clinical: ClinicalApi, tenant: ClinicalTenant
) -> None:
    """R10: a patient UUID the caller cannot resolve is `404`, indistinguishable from absent."""
    response = clinical.timeline(tenant.owner, uuid.uuid4())

    assert response.status_code == 404, response.text


def test_soft_deleted_records_are_not_readable(
    clinical: ClinicalApi, tenant: ClinicalTenant
) -> None:
    """`deleted_at` means "not readable", and nothing in this slice can set it."""
    record = created_record(clinical.create_record(tenant.owner, tenant.patient))

    from sqlalchemy import text

    from app.core.db import engine

    with engine.begin() as conn:
        conn.execute(
            text(
                "UPDATE clinical_records SET deleted_at = now() WHERE id = :record_id"
            ),
            {"record_id": uuid.UUID(record["id"])},
        )

    assert clinical.read_record(tenant.owner, record["id"]).status_code == 404
    assert clinical.timeline(tenant.owner, tenant.patient).json()["count"] == 0
    # The versions are still there — a soft delete never touches clinical content.
    assert len(clinical.version_rows(tenant.tenant_id, record["id"])) == 1
