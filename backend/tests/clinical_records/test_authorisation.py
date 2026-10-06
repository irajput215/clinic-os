"""S6, R2, R11 — deny by default: authentication, permission, and the one deferred resource rule.

Design: `docs/features/06-clinical-records/03-design.md` §"Deny-by-default request path". The order is
literal: authenticate → resolve the tenant from the session → check the permission → resolve the
resource → (the treating-relationship rule) → audit → validate → execute.

The treating-relationship rule (R11) is **not implemented**: the `care_relationships` module it reads
does not exist on this branch and the feature's own documents record it as `OPEN — blocked`
(`01-requirements.md` OPEN-3). `test_the_care_relationship_rule_is_not_yet_implemented` pins the
current behaviour deliberately, so the day the rule lands this test fails and the gap cannot be
forgotten.
"""

import uuid

from tests.clinical_records.conftest import (
    CLINICAL_URL,
    PATIENTS_URL,
    ClinicalApi,
    ClinicalTenant,
    created_record,
)


def test_every_clinical_route_requires_authentication(
    clinical: ClinicalApi, tenant: ClinicalTenant
) -> None:
    """S6: no route is reachable without a verified session."""
    record = created_record(clinical.create_record(tenant.owner, tenant.patient))
    patient_id = tenant.patient

    requests = (
        ("post", CLINICAL_URL, {"patient_id": str(patient_id), "body": "x"}),
        ("get", f"{CLINICAL_URL}/{record['id']}", None),
        ("get", f"{CLINICAL_URL}/{record['id']}/versions/1", None),
        ("get", f"{PATIENTS_URL}/{patient_id}/clinical-records", None),
        ("patch", f"{CLINICAL_URL}/{record['id']}", {"body": "x"}),
        ("post", f"{CLINICAL_URL}/{record['id']}/amendments", {"body": "x"}),
        ("post", f"{CLINICAL_URL}/{record['id']}/sign", None),
    )

    for method, url, body in requests:
        response = (
            clinical.client.request(method, url, json=body)
            if body is not None
            else clinical.client.request(method, url)
        )
        assert response.status_code == 401, (method, url, response.status_code)


def test_a_role_without_the_permission_is_refused(
    clinical: ClinicalApi, tenant: ClinicalTenant
) -> None:
    """S6: the `PHARMACY` bundle holds neither clinical permission, so every route is `403`."""
    record = created_record(clinical.create_record(tenant.owner, tenant.patient))
    pharmacy = clinical.add_actor(session=tenant.owner, role_code="PHARMACY")

    attempts = (
        clinical.read_record(pharmacy, record["id"]),
        clinical.read_version(pharmacy, record["id"], 1),
        clinical.timeline(pharmacy, tenant.patient),
        clinical.patch_record(pharmacy, record["id"], body="x", amendment_reason="x"),
        clinical.amend(pharmacy, record["id"], body="x", amendment_reason="x"),
        clinical.sign(pharmacy, record["id"]),
        clinical.create_record(pharmacy, tenant.patient),
    )

    for response in attempts:
        assert response.status_code == 403, response.text
        assert response.json()["detail"]["code"] == "PERMISSION_NOT_HELD"

    # Every refusal was audited, and nothing was written.
    denied = [
        row
        for row in clinical.clinical_events(tenant.tenant_id)
        if row["result"] == "DENIED"
    ]
    assert len(denied) == len(attempts), denied
    assert clinical.row_counts(tenant.tenant_id) == (1, 1)


def test_a_read_only_role_may_read_but_not_write(
    clinical: ClinicalApi, tenant: ClinicalTenant
) -> None:
    """US-8 / US-10: the compliance auditor reads the chart and is refused every write."""
    record = created_record(clinical.create_record(tenant.owner, tenant.patient))
    auditor = clinical.add_actor(session=tenant.owner, role_code="COMPLIANCE_AUDITOR")

    read = clinical.read_record(auditor, record["id"])
    assert read.status_code == 200, read.text
    assert read.json()["versions"][0]["body"] == record["versions"][0]["body"]

    for response in (
        clinical.create_record(auditor, tenant.patient),
        clinical.patch_record(
            auditor, record["id"], body="auditor edit", amendment_reason="x"
        ),
        clinical.amend(
            auditor, record["id"], body="auditor amendment", amendment_reason="x"
        ),
        clinical.sign(auditor, record["id"]),
    ):
        assert response.status_code == 403, response.text

    assert clinical.row_counts(tenant.tenant_id) == (1, 1)


def test_the_care_relationship_rule_is_not_yet_implemented(
    clinical: ClinicalApi, tenant: ClinicalTenant
) -> None:
    """The documented gap (R11 / OPEN-3), pinned so it cannot be forgotten.

    R11 requires an active treating relationship for every read and write. The rule's data source is
    `care_relationships`, which has no module and no table on this branch — the feature's own
    `07-definition-of-done.md` records it as `OPEN — blocked`. What *is* enforced is permission and
    tenancy; the relationship rule can only ever remove access, so its absence is a deferral rather
    than a fail-open.

    When `care_relationships` lands and the rule is wired in, an actor holding `clinical_record:read`
    with no active relationship must be refused here — and this assertion will fail, which is the
    point.
    """
    record = created_record(clinical.create_record(tenant.owner, tenant.patient))
    # An administrator holds `clinical_record:read` and has no treating relationship with the
    # patient: no `care_relationships` row exists for anybody in this environment.
    administrator = clinical.add_actor(session=tenant.owner, role_code="ADMINISTRATOR")

    response = clinical.read_record(administrator, record["id"])

    assert response.status_code == 200, (
        "the treating-relationship rule now refuses this read — R11 is implemented, and this "
        "gap-pinning test should be replaced by the positive and negative relationship cases: "
        + response.text
    )


def test_an_unknown_record_is_not_a_permission_probe(
    clinical: ClinicalApi, tenant: ClinicalTenant
) -> None:
    """R10: a caller without the permission gets `403`; a caller with it gets `404` — never both."""
    pharmacy = clinical.add_actor(session=tenant.owner, role_code="PHARMACY")

    unknown = uuid.uuid4()
    assert clinical.read_record(pharmacy, str(unknown)).status_code == 403
    assert clinical.read_record(tenant.owner, str(unknown)).status_code == 404
