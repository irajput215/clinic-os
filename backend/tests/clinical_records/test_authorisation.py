"""S6, R2, R11 — deny by default: authentication, permission, and the treating-relationship rule.

Design: `docs/features/06-clinical-records/03-design.md` §"Deny-by-default request path". The order is
literal: authenticate → resolve the tenant from the session → check the permission → resolve the
resource → the treating-relationship rule → audit → validate → execute.

R11 (task T1-34): a doctor's or nurse's `clinical_record:*` grant reaches a record only through an
active care relationship with its patient (the matrix's `cr`); without one, every route answers
`403 AUTHZ_CARE_RELATIONSHIP_DENIED` and writes a `DENIED` event with that reason. Across a tenant
boundary the answer stays `404`. An unconditional grant (an administrator's read) is not bound.
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


def test_a_doctor_without_a_care_relationship_is_refused_on_every_route(
    clinical: ClinicalApi, tenant: ClinicalTenant
) -> None:
    """R11 / US-7: `403` with the relationship code, audited, and nothing written."""
    record = created_record(clinical.create_record(tenant.owner, tenant.patient))
    doctor = clinical.add_actor(session=tenant.owner, role_code="DOCTOR")
    before = clinical.row_counts(tenant.tenant_id)

    for response in (
        clinical.read_record(doctor, record["id"]),
        clinical.read_version(doctor, record["id"], 1),
        clinical.timeline(doctor, tenant.patient),
        clinical.create_record(doctor, tenant.patient),
        clinical.patch_record(
            doctor, record["id"], body="An edit", amendment_reason="Unrelated"
        ),
        clinical.amend(doctor, record["id"], body="An amendment", amendment_reason="x"),
        clinical.sign(doctor, record["id"]),
    ):
        assert response.status_code == 403, response.text
        assert response.json()["detail"]["code"] == "AUTHZ_CARE_RELATIONSHIP_DENIED"
        # The refusal names no patient data.
        assert "Synthetic" not in response.text

    assert clinical.row_counts(tenant.tenant_id) == before
    denials = [
        row
        for row in clinical.clinical_events(tenant.tenant_id)
        if row["actor_id"] == doctor.user_id
    ]
    assert len(denials) == 7
    assert {row["result"] for row in denials} == {"DENIED"}
    assert {row["reason"] for row in denials} == {"AUTHZ_CARE_RELATIONSHIP_DENIED"}
    assert {row["metadata"]["patient_id"] for row in denials} == {str(tenant.patient)}


def test_another_tenants_record_stays_404_for_a_relationship_bound_doctor(
    clinical: ClinicalApi, tenant: ClinicalTenant
) -> None:
    """The relationship `403` is only ever answered inside the caller's own tenant."""
    record = created_record(clinical.create_record(tenant.owner, tenant.patient))
    other_owner = clinical.register(clinic_name="Another Clinical Clinic")
    other_doctor = clinical.add_actor(session=other_owner, role_code="DOCTOR")

    assert clinical.read_record(other_doctor, record["id"]).status_code == 404
    assert clinical.timeline(other_doctor, tenant.patient).status_code == 404
    assert clinical.sign(other_doctor, record["id"]).status_code == 404


def test_a_doctor_with_a_care_relationship_reads_and_writes_audited(
    clinical: ClinicalApi, tenant: ClinicalTenant
) -> None:
    """R11: the relationship opens the record, and the read records its id and the purpose."""
    record = created_record(clinical.create_record(tenant.owner, tenant.patient))
    doctor = clinical.add_actor(session=tenant.owner, role_code="DOCTOR")
    relationship = clinical.relate(
        manager=tenant.owner, practitioner=doctor, patient=tenant.patient
    )

    assert clinical.read_record(doctor, record["id"]).status_code == 200
    assert clinical.timeline(doctor, tenant.patient).status_code == 200
    created = clinical.create_record(doctor, tenant.patient)
    assert created.status_code == 201, created.text

    reads = [
        row
        for row in clinical.clinical_events(
            tenant.tenant_id, action="clinical_record.read"
        )
        if row["actor_id"] == doctor.user_id
    ]
    assert [row["result"] for row in reads] == ["SUCCESS", "SUCCESS"]
    for row in reads:
        assert row["metadata"]["care_relationship_id"] == str(relationship)
        assert row["metadata"]["purpose"] == "TREATMENT"


def test_an_unconditional_grant_is_not_bound_by_the_relationship_rule(
    clinical: ClinicalApi, tenant: ClinicalTenant
) -> None:
    """The matrix gives an administrator `clinical_record:read` without `cr`: no relationship needed,
    and the read is recorded with the administrative purpose and no relationship id."""
    record = created_record(clinical.create_record(tenant.owner, tenant.patient))
    administrator = clinical.add_actor(session=tenant.owner, role_code="ADMINISTRATOR")

    response = clinical.read_record(administrator, record["id"])

    assert response.status_code == 200, response.text
    [read] = [
        row
        for row in clinical.clinical_events(
            tenant.tenant_id, action="clinical_record.read"
        )
        if row["actor_id"] == administrator.user_id
    ]
    assert read["metadata"]["purpose"] == "PRACTICE_ADMINISTRATION"
    assert "care_relationship_id" not in read["metadata"]


def test_an_unknown_record_is_not_a_permission_probe(
    clinical: ClinicalApi, tenant: ClinicalTenant
) -> None:
    """R10: a caller without the permission gets `403`; a caller with it gets `404` — never both."""
    pharmacy = clinical.add_actor(session=tenant.owner, role_code="PHARMACY")

    unknown = uuid.uuid4()
    assert clinical.read_record(pharmacy, str(unknown)).status_code == 403
    assert clinical.read_record(tenant.owner, str(unknown)).status_code == 404
