"""Probe contract tests (feature `16-operations-and-observability`, requirement R19).

The design fixes two obligations that a naive probe breaks, and both are asserted here:

- **A probe exposes no tenant data and no more than a boolean status**
  (`16-operations-and-observability/03-design.md` §"Deny-by-default request path").
- **A probe is never routed through tenant resolution**, with or without tenant context present
  (`16-operations-and-observability/06-test-plan.md` scenario S8).
"""

from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.exc import OperationalError

READINESS_PATH = "/api/v1/health/ready/"
LIVENESS_PATH = "/api/v1/utils/health-check/"


class _UnreachableEngine:
    """Stands in for an engine whose database cannot be reached."""

    def connect(self) -> Any:
        raise OperationalError("SELECT 1", {}, Exception("connection refused"))


@pytest.fixture
def unreachable_database(monkeypatch: pytest.MonkeyPatch) -> None:
    """Make every readiness check fail to connect."""
    monkeypatch.setattr("app.core.health.autocommit_engine", _UnreachableEngine())


# --- The denial path comes first: a probe that cannot report failure is not a probe. ---


@pytest.mark.usefixtures("unreachable_database")
def test_readiness_probe_reports_not_ready_when_the_database_is_unreachable(
    client: TestClient,
) -> None:
    response = client.get(READINESS_PATH)

    assert response.status_code == 503
    assert response.json() is False


@pytest.mark.usefixtures("unreachable_database")
def test_readiness_probe_never_leaks_why_it_failed(client: TestClient) -> None:
    """The reason is an operations concern, not a world-readable one.

    The route is unauthenticated, so a driver message naming the host, the role or the failure
    mode would be an information disclosure to anyone who can reach the URL.
    """
    response = client.get(READINESS_PATH)

    assert response.text.strip() == "false"
    for leaked in ("connection refused", "SELECT 1", "host", "password", "Traceback"):
        assert leaked not in response.text


# --- The success path. ---


def test_readiness_probe_reports_ready_when_the_database_is_reachable(
    client: TestClient,
) -> None:
    response = client.get(READINESS_PATH)

    assert response.status_code == 200
    assert response.json() is True


# --- R19 / S8: boolean only, no tenant data, never routed through tenant resolution. ---


def test_readiness_probe_exposes_no_tenant_data(client: TestClient) -> None:
    """Requirement R19 — the test the design names, run with and without tenant context."""
    bogus_tenant = "11111111-2222-3333-4444-555555555555"

    without_tenant = client.get(READINESS_PATH)
    with_tenant = client.get(READINESS_PATH, headers={"X-Tenant-Id": bogus_tenant})

    # Boolean only: not an object, not a list, nothing to add a field to later.
    for response in (without_tenant, with_tenant):
        assert isinstance(response.json(), bool)
        assert response.text.strip() in {"true", "false"}
        assert bogus_tenant not in response.text
        assert "tenant" not in response.text.lower()


def test_readiness_probe_is_not_routed_through_tenant_resolution(
    client: TestClient,
) -> None:
    """An orchestrator holds no session and no tenant, so a probe must never demand either.

    A `401`, `403` or tenant-context failure here would mean the deploy pipeline can no longer ask
    whether the release works.
    """
    response = client.get(READINESS_PATH)

    assert response.status_code not in {401, 403}
    assert response.status_code == 200


# --- Liveness must stay independent of the database. ---


@pytest.mark.usefixtures("unreachable_database")
def test_liveness_probe_does_not_touch_the_database(client: TestClient) -> None:
    """A database blip must not restart every container.

    Liveness answers "is this process wedged?"; coupling it to the database turns a partial outage
    into a full one, because the orchestrator replaces healthy processes.
    """
    response = client.get(LIVENESS_PATH)

    assert response.status_code == 200
    assert response.json() is True
