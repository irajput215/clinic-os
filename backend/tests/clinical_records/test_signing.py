"""F4-F5, R4-R5 — signing: identity-bound, and the point after which `PATCH` is refused.

Design: `docs/features/06-clinical-records/03-design.md` §"Endpoints", §"Failure behaviour" and
§"Immutability mechanism at two layers". Requirements R4 and R5.
"""

from tests.clinical_records.conftest import ClinicalApi, ClinicalTenant, created_record


def test_sign_is_identity_bound_to_version_author(
    clinical: ClinicalApi, tenant: ClinicalTenant
) -> None:
    """F4 / R4: only the version's author may sign it; a different clinician is refused `403`."""
    record = created_record(clinical.create_record(tenant.owner, tenant.patient))
    other_clinician = clinical.add_actor(session=tenant.owner, role_code="DOCTOR")

    attempt = clinical.sign(other_clinician, record["id"])
    assert attempt.status_code == 403, attempt.text
    assert attempt.json()["detail"]["code"] == "SIGN_NOT_VERSION_AUTHOR"

    # Nothing changed: the record is still unsigned and still at version 1.
    unsigned = clinical.read_record(tenant.owner, record["id"])
    assert unsigned.json()["signed_at"] is None

    signed = clinical.sign(tenant.owner, record["id"])
    assert signed.status_code == 200, signed.text
    assert signed.json()["signed_at"] is not None
    assert signed.json()["author_id"] == str(tenant.owner.user_id)

    row = clinical.record_row(tenant.tenant_id, record["id"])
    assert row is not None and row["signed_at"] is not None


def test_sign_is_refused_twice(clinical: ClinicalApi, tenant: ClinicalTenant) -> None:
    """R5: a signature is not re-applied; the second attempt is `403 NOTE_ALREADY_SIGNED`."""
    record = created_record(clinical.create_record(tenant.owner, tenant.patient))
    assert clinical.sign(tenant.owner, record["id"]).status_code == 200

    second = clinical.sign(tenant.owner, record["id"])
    assert second.status_code == 403, second.text
    assert second.json()["detail"]["code"] == "NOTE_ALREADY_SIGNED"


def test_patch_signed_note_returns_403(
    clinical: ClinicalApi, tenant: ClinicalTenant
) -> None:
    """F5 / R5: `PATCH` after signature is `403 NOTE_ALREADY_SIGNED`, and no version is written."""
    record = created_record(clinical.create_record(tenant.owner, tenant.patient))
    assert clinical.sign(tenant.owner, record["id"]).status_code == 200

    refused = clinical.patch_record(
        tenant.owner,
        record["id"],
        body="An in-place edit that must not land.",
        amendment_reason="Attempted edit after signature",
    )

    assert refused.status_code == 403, refused.text
    assert refused.json()["detail"]["code"] == "NOTE_ALREADY_SIGNED"
    assert clinical.row_counts(tenant.tenant_id) == (1, 1)
    rows = clinical.version_rows(tenant.tenant_id, record["id"])
    assert [row["version"] for row in rows] == [1]


def test_patch_unsigned_note_appends_and_requires_a_reason(
    clinical: ClinicalApi, tenant: ClinicalTenant
) -> None:
    """R5 with R7: while unsigned, `PATCH` appends a version — and from version 2 a reason is
    mandatory, the stricter reading `01-requirements.md` OPEN-2 records."""
    record = created_record(clinical.create_record(tenant.owner, tenant.patient))

    without_reason = clinical.patch_record(
        tenant.owner, record["id"], body="Draft, second pass."
    )
    assert without_reason.status_code == 422, without_reason.text
    assert without_reason.json()["detail"]["code"] == "AMENDMENT_REASON_REQUIRED"

    with_reason = clinical.patch_record(
        tenant.owner,
        record["id"],
        body="Draft, second pass.",
        amendment_reason="Draft updated before signature",
    )
    assert with_reason.status_code == 200, with_reason.text
    body = with_reason.json()
    assert body["current_version"] == 2
    assert body["signed_at"] is None
    assert [version["version"] for version in body["versions"]] == [1, 2]

    # The signature still lands on the current version and is still identity-bound.
    assert clinical.sign(tenant.owner, record["id"]).status_code == 200
    assert clinical.row_counts(tenant.tenant_id) == (1, 2)
