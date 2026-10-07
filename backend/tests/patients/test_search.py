"""Patient search and keyset paging: `POST /api/v1/patients/search` and `GET /api/v1/patients?cursor=`.

Requirements: `docs/features/05-patients/01-requirements.md` R5 (search isolation), R12 (no search
term in a URL), R13 (denials audited with equal fidelity); test plan F13, S2, S12, S13, S17; the
pagination standard of `docs/reference/definition-of-done.md` §4 (opaque signed cursor that cannot be
replayed across tenants). Denials first, then the success paths.
"""

import uuid
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlmodel import Session

from app.core.config import settings
from app.modules.patients import service
from tests.observability.log_sinks import capture_logs
from tests.patients.conftest import PATIENTS_URL, PatientsApi, TenantSession
from tests.utils.rbac import RbacApi

SEARCH_URL = f"{PATIENTS_URL}/search"


def _names(response_body: dict[str, Any]) -> list[str]:
    return [
        f"{row['given_name']} {row['family_name']}" for row in response_body["data"]
    ]


def _walk(api: PatientsApi, session: TenantSession, q: str | None) -> list[str]:
    """Follow `next_cursor` to the end, returning every id in page order."""
    ids: list[str] = []
    cursor: str | None = None
    for _ in range(20):
        response = (
            api.list(session, limit=4, cursor=cursor)
            if q is None
            else api.search(session, q, limit=4, cursor=cursor)
        )
        assert response.status_code == 200, response.text
        body = response.json()
        ids.extend(row["id"] for row in body["data"])
        cursor = body["next_cursor"]
        if cursor is None:
            return ids
    raise AssertionError("paging never ended")


# ---------------------------------------------------------------------------------------------
# Denials
# ---------------------------------------------------------------------------------------------


def test_search_requires_authentication(client: TestClient) -> None:
    assert client.post(SEARCH_URL, json={"q": "ada"}).status_code == 401


def test_search_without_an_organisation_fails_closed(api: PatientsApi) -> None:
    account = api.register(clinic_name=None)
    response = api.search(account, "ada")
    assert response.status_code == 403
    assert response.json()["detail"]["code"] == "NO_ORGANISATION"


def test_search_without_patient_read_is_refused_and_audited(
    client: TestClient, db: Session, api: PatientsApi
) -> None:
    """S17: a permission denial writes `patient.read` `DENIED` before anything is read."""
    rbac = RbacApi(client, db)
    try:
        owner = rbac.register_tenant(clinic_name="Denial Clinic")
        assert owner.tenant_id is not None
        no_role = rbac.add_actor(tenant_id=owner.tenant_id, granted_by=owner.user_id)

        searched = client.post(SEARCH_URL, json={"q": "ada"}, headers=no_role.headers)
        listed = client.get(PATIENTS_URL, headers=no_role.headers)

        for response in (searched, listed):
            assert response.status_code == 403, response.text
            assert response.json()["detail"]["code"] == "PERMISSION_NOT_HELD"
        denials = api.patient_reads(owner.tenant_id)
        assert [(row["result"], row["reason"]) for row in denials] == [
            ("DENIED", "AUTHZ_DENIED"),
            ("DENIED", "AUTHZ_DENIED"),
        ]
        assert {row["actor_id"] for row in denials} == {no_role.user_id}
    finally:
        rbac.cleanup()


def test_a_search_term_in_the_url_is_refused_not_ignored(api: PatientsApi) -> None:
    """F13 / R12: `GET /patients?q=` is never answered, so the URL cannot become the search path."""
    clinic = api.register(clinic_name="Riverside Family Clinic")
    api.create(clinic, family_name="Searchable")

    response = api.client.get(
        PATIENTS_URL, params={"q": "Searchable"}, headers=clinic.headers
    )

    assert response.status_code == 422, response.text
    assert response.json()["detail"]["code"] == "UNSUPPORTED_QUERY_PARAMETER"
    assert "Searchable" not in response.text
    assert [
        (row["result"], row["reason"]) for row in api.patient_reads(clinic.tenant_id)
    ] == [("DENIED", "UNSUPPORTED_QUERY_PARAMETER")]


def test_search_rejects_a_body_field_the_contract_does_not_declare(
    api: PatientsApi,
) -> None:
    clinic = api.register(clinic_name="Riverside Family Clinic")
    response = api.client.post(
        SEARCH_URL,
        json={"q": "ada", "tenant_id": str(uuid.uuid4())},
        headers=clinic.headers,
    )
    assert response.status_code == 422


@pytest.mark.parametrize(
    "q",
    ["", "   ", "x" * 101, "one two three four five six seven"],
    ids=["empty", "blank", "too-long", "too-many-words"],
)
def test_search_rejects_an_empty_or_oversized_query(api: PatientsApi, q: str) -> None:
    clinic = api.register(clinic_name="Riverside Family Clinic")
    response = api.search(clinic, q)
    assert response.status_code == 422, response.text
    if q.strip():
        assert q not in response.text, "a validation error must not echo the term"


@pytest.mark.parametrize(
    "cursor",
    ["not-a-cursor", "AAAA.AAAA", "x" * 40 + "." + "y" * 22, "...."],
)
def test_a_forged_cursor_is_refused_and_audited(api: PatientsApi, cursor: str) -> None:
    clinic = api.register(clinic_name="Riverside Family Clinic")

    listed = api.list(clinic, cursor=cursor)
    searched = api.search(clinic, "ada", cursor=cursor)

    for response in (listed, searched):
        assert response.status_code == 422, response.text
        assert response.json()["detail"]["code"] == "INVALID_CURSOR"
    reads = api.patient_reads(clinic.tenant_id)
    assert [(row["result"], row["reason"]) for row in reads] == [
        ("DENIED", "INVALID_CURSOR"),
        ("DENIED", "INVALID_CURSOR"),
    ]


def test_a_cursor_cannot_be_replayed_in_another_tenant(api: PatientsApi) -> None:
    """`definition-of-done.md` §4: the cursor is bound to the tenant that was issued it."""
    clinic_a = api.register(clinic_name="Alpha Clinic")
    clinic_b = api.register(clinic_name="Beta Clinic")
    for index in range(3):
        api.create(clinic_a, family_name=f"Alpha{index}")
        api.create(clinic_b, family_name=f"Beta{index}")
    cursor = api.list(clinic_a, limit=1).json()["next_cursor"]
    assert cursor is not None

    response = api.list(clinic_b, limit=1, cursor=cursor)

    assert response.status_code == 422
    assert response.json()["detail"]["code"] == "INVALID_CURSOR"
    assert "Alpha" not in response.text


def test_a_cursor_cannot_be_reused_for_a_different_request(api: PatientsApi) -> None:
    """A list cursor does not continue a search, and a search cursor does not continue another."""
    clinic = api.register(clinic_name="Riverside Family Clinic")
    for index in range(3):
        api.create(clinic, given_name="Ada", family_name=f"Lovelace{index}")
    list_cursor = api.list(clinic, limit=1).json()["next_cursor"]
    search_cursor = api.search(clinic, "ada", limit=1).json()["next_cursor"]
    assert list_cursor is not None
    assert search_cursor is not None

    assert api.search(clinic, "ada", cursor=list_cursor).status_code == 422
    assert api.search(clinic, "love", cursor=search_cursor).status_code == 422
    assert api.list(clinic, cursor=search_cursor).status_code == 422
    # The same search, differently spaced and cased, is the same request.
    assert api.search(clinic, "  ADA ", cursor=search_cursor).status_code == 200


def test_search_is_scoped_to_the_callers_tenant(api: PatientsApi) -> None:
    """S2 / R5: another tenant's matching row is absent, not refused."""
    clinic_a = api.register(clinic_name="Alpha Clinic")
    clinic_b = api.register(clinic_name="Beta Clinic")
    mine = api.create(clinic_a, family_name="Sharedname")
    theirs = api.create(clinic_b, family_name="Sharedname", given_name="Other")

    response = api.search(clinic_a, "sharedname")

    assert response.status_code == 200, response.text
    body = response.json()
    assert [row["id"] for row in body["data"]] == [mine["id"]]
    assert body["count"] == 1
    assert theirs["id"] not in response.text
    reference = "PT-" + theirs["id"].replace("-", "")[:6]
    assert api.search(clinic_a, reference).json()["data"] == []


@pytest.mark.parametrize("wildcard", ["%", "_", "a%", "a_a", "\\"])
def test_like_wildcards_are_escaped(api: PatientsApi, wildcard: str) -> None:
    """S12 / T-05.2: `%` and `_` match themselves; they never widen the result to the tenant."""
    clinic = api.register(clinic_name="Riverside Family Clinic")
    api.create(clinic, family_name="Aaa")
    api.create(clinic, family_name="Abba")
    literal = api.create(clinic, family_name=f"{wildcard}literal")

    body = api.search(clinic, wildcard).json()

    # Only the name that literally starts with the term; an unescaped `%` or `_` would also have
    # matched "Aaa" and "Abba" (and every other row of the tenant).
    assert {row["id"] for row in body["data"]} == {literal["id"]}
    assert body["count"] == 1


def test_the_search_term_reaches_no_log_and_no_audit_payload(
    api: PatientsApi,
) -> None:
    """INV-5 / US-7: the term is never logged, and the audit event records only its kinds."""
    sentinel = "QZQZSearchSentinel"
    clinic = api.register(clinic_name="Riverside Family Clinic")
    api.create(clinic, family_name=sentinel)
    cursor_source = api.create(clinic, family_name=f"{sentinel}Two")
    assert cursor_source

    with capture_logs(envelope_filter=False) as sink:
        first = api.search(clinic, f"{sentinel.lower()} 1990-01-01", limit=1)
        assert first.status_code == 200, first.text
        follow = api.search(
            clinic,
            f"{sentinel.lower()} 1990-01-01",
            limit=1,
            cursor=first.json()["next_cursor"],
        )
        assert follow.status_code == 200, follow.text
        bad = api.search(clinic, sentinel, cursor="forged.cursor")
        assert bad.status_code == 422

    logged = sink.raw
    assert logged, "the sink saw nothing, so the absence below would prove nothing"
    assert sentinel not in logged
    assert sentinel.lower() not in logged
    for row in api.patient_reads(clinic.tenant_id):
        assert sentinel.lower() not in str(row).lower()
        assert "1990-01-01" not in str(row)


def test_search_is_rate_limited_per_session(
    api: PatientsApi, monkeypatch: pytest.MonkeyPatch
) -> None:
    """S13 / T-05.13: a sweep of searches is cut off with `429` and `Retry-After`."""
    monkeypatch.setattr(settings, "RATE_LIMIT_ENABLED", True)
    clinic = api.register(clinic_name="Riverside Family Clinic")

    statuses = [api.search(clinic, "a").status_code for _ in range(121)]

    assert statuses[:120] == [200] * 120
    assert statuses[120] == 429


# ---------------------------------------------------------------------------------------------
# Success paths
# ---------------------------------------------------------------------------------------------


def test_search_matches_a_name_prefix_case_insensitively(api: PatientsApi) -> None:
    clinic = api.register(clinic_name="Riverside Family Clinic")
    api.create(clinic, given_name="Ada", family_name="Lovelace")
    api.create(
        clinic, given_name="Grace", family_name="Hopper", preferred_name="Amazing"
    )
    api.create(clinic, given_name="Alan", family_name="Turing")
    api.create(clinic, given_name="Edsger", family_name="Dijkstra")

    def found(q: str) -> list[str]:
        response = api.search(clinic, q)
        assert response.status_code == 200, response.text
        return _names(response.json())

    assert found("LOVE") == ["Ada Lovelace"]
    assert found("a") == ["Grace Hopper", "Ada Lovelace", "Alan Turing"]
    assert found("ama") == ["Grace Hopper"], "the preferred name is a search key"
    assert found("ada love") == ["Ada Lovelace"], "every word must match"
    assert found("ada turing") == []
    assert found("velace") == [], "prefix, not substring"


def test_search_matches_a_date_of_birth_in_either_written_order(
    api: PatientsApi,
) -> None:
    clinic = api.register(clinic_name="Riverside Family Clinic")
    api.create(clinic, family_name="Born", date_of_birth="1980-03-14")
    api.create(clinic, family_name="Other", date_of_birth="1980-03-15")

    for q in ("1980-03-14", "14/03/1980", "14/3/1980", "born 1980-03-14"):
        response = api.search(clinic, q)
        assert response.status_code == 200, response.text
        assert [row["family_name"] for row in response.json()["data"]] == ["Born"], q
    # Not a real date: treated as a name prefix, and matches nothing.
    assert api.search(clinic, "31/02/1980").json()["data"] == []


def test_search_matches_the_on_screen_reference(api: PatientsApi) -> None:
    clinic = api.register(clinic_name="Riverside Family Clinic")
    target = api.create(clinic, family_name="Target")
    api.create(clinic, family_name="Bystander")
    reference = "PT-" + target["id"].replace("-", "")[:6].upper()

    for q in (reference, reference.lower(), reference.replace("-", "")):
        response = api.search(clinic, q)
        assert response.status_code == 200, response.text
        assert [row["id"] for row in response.json()["data"]] == [target["id"]], q


def test_search_pages_with_a_keyset_cursor_and_counts_the_matches(
    api: PatientsApi,
) -> None:
    clinic = api.register(clinic_name="Riverside Family Clinic")
    created = [
        api.create(clinic, given_name="Match", family_name=f"Family{index:02d}")
        for index in range(10)
    ]
    api.create(clinic, given_name="Elsewhere", family_name="Nomatch")

    first = api.search(clinic, "match", limit=4).json()
    assert first["count"] == 10
    assert len(first["data"]) == 4
    assert first["next_cursor"] is not None

    ids = _walk(api, clinic, "match")
    assert ids == [row["id"] for row in created]


def test_every_patient_is_reachable_through_the_list(api: PatientsApi) -> None:
    """The list is no longer capped at the first page: `next_cursor` reaches every row once."""
    clinic = api.register(clinic_name="Riverside Family Clinic")
    created = [
        api.create(clinic, given_name=given, family_name=family)
        for family, given in [
            ("Same", "Bea"),
            ("Same", "Ada"),
            ("Same", "Ada"),
            ("Able", "Zed"),
            ("Zulu", "Amy"),
            ("Mid", "Kim"),
            ("Mid", "Kim"),
            ("Mid", "Kim"),
            ("Mid", "Kim"),
        ]
    ]

    ids = _walk(api, clinic, None)

    assert sorted(ids) == sorted(row["id"] for row in created)
    assert len(ids) == len(set(ids)), "a row was repeated across pages"
    rows = {row["id"]: row for row in created}
    keys = [(rows[i]["family_name"], rows[i]["given_name"], i) for i in ids]
    assert keys == sorted(keys), "pages follow (family_name, given_name, id)"
    assert api.list(clinic, limit=25).json()["next_cursor"] is None


def test_a_patient_added_while_paging_is_neither_skipped_nor_repeated(
    api: PatientsApi,
) -> None:
    """Keyset, not `OFFSET`: an insert before the boundary does not shift the next page."""
    clinic = api.register(clinic_name="Riverside Family Clinic")
    for family in ("Bravo", "Charlie", "Delta", "Echo"):
        api.create(clinic, family_name=family)
    first = api.list(clinic, limit=2).json()
    api.create(clinic, family_name="Alpha")

    second = api.list(clinic, limit=2, cursor=first["next_cursor"]).json()

    assert [row["family_name"] for row in first["data"]] == ["Bravo", "Charlie"]
    assert [row["family_name"] for row in second["data"]] == ["Delta", "Echo"]


def test_list_and_search_reads_are_audited(api: PatientsApi) -> None:
    """A1: one `patient.read` per page, with the page's count and the kinds of term used."""
    clinic = api.register(clinic_name="Riverside Family Clinic")
    api.create(
        clinic, given_name="Ada", family_name="Lovelace", date_of_birth="1815-12-10"
    )
    api.create(clinic, given_name="Alan", family_name="Turing")

    api.list(clinic)
    api.search(clinic, "a 1815-12-10 a")

    reads = api.patient_reads(clinic.tenant_id)
    assert [(row["result"], row["resource_id"]) for row in reads] == [
        ("SUCCESS", None),
        ("SUCCESS", None),
    ]
    assert reads[0]["metadata"] == {"result_count": 2}
    assert reads[1]["metadata"] == {
        "query_filters": [service.DATE_OF_BIRTH, service.NAME_PREFIX],
        "result_count": 1,
    }
    assert {row["actor_id"] for row in reads} == {clinic.user_id}


def test_parse_search_classifies_each_word() -> None:
    """The term grammar, without the database: dates, references, and escaped name prefixes."""
    terms = service.parse_search("Smi 14/03/1980 pt-abcdef 2020-02-30 50%_\\")
    assert [term.kind for term in terms] == [
        service.NAME_PREFIX,
        service.DATE_OF_BIRTH,
        service.REFERENCE,
        service.NAME_PREFIX,
        service.NAME_PREFIX,
    ]
    assert terms[0].value == "smi%"
    assert terms[4].value == "50\\%\\_\\\\%"
    low, high = terms[2].value  # type: ignore[misc]
    assert str(low).startswith("abcdef00-0000")
    assert str(high).startswith("abcdefff-ffff")
