"""Database round trips per request, pinned so they cannot creep back (`performance.md` §4).

Production pays the full app-to-database latency once per round trip (about 216 ms on 2026-10-08,
`docs/reference/performance.md` §3), so a round trip added to a hot request is a regression a user
feels, even though no test of behaviour would notice it. The counts come from the app's own
`Server-Timing` header, which is measured inside the driver.

The budget for a typical read is three: the request's prelude (the account, its organisation's
status and its grants, in one flight), the route's first statement (which carries the transaction's
`BEGIN` and tenant context), and `COMMIT`.
"""

from datetime import UTC, datetime, timedelta

import pytest
from fastapi.testclient import TestClient

from app.core.config import settings
from tests.patients.conftest import TenantSession
from tests.performance.conftest import round_trips

API = settings.API_V1_STR


def _get(client: TestClient, clinic: TenantSession, path: str) -> int:
    # Once first, so the counted request finds the pool warm.
    client.get(f"{API}{path}", headers=clinic.headers)
    response = client.get(f"{API}{path}", headers=clinic.headers)
    assert response.status_code == 200, response.text
    return round_trips(response)


def test_the_readiness_probe_is_one_round_trip(client: TestClient) -> None:
    client.get(f"{API}/health/ready/")
    assert round_trips(client.get(f"{API}/health/ready/")) == 1


@pytest.mark.parametrize("path", ["/users/me", "/users/me/permissions"])
def test_the_session_prelude_is_one_round_trip(
    client: TestClient, clinic: TenantSession, path: str
) -> None:
    """Account, organisation status, tenant context and grants: one flight, nothing else."""
    assert _get(client, clinic, path) == 1


def test_the_script_queue_is_a_typical_read(
    client: TestClient, clinic: TenantSession
) -> None:
    assert _get(client, clinic, "/prescriptions") == 3


def test_a_week_of_the_calendar_is_a_typical_read(
    client: TestClient, clinic: TenantSession
) -> None:
    start = datetime.now(UTC).replace(microsecond=0)
    end = start + timedelta(days=7)
    path = f"/appointments?from={start.isoformat()}&to={end.isoformat()}".replace(
        "+", "%2B"
    )
    assert _get(client, clinic, path) == 3
