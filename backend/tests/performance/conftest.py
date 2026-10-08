"""Fixtures for the round-trip budget tests (`docs/reference/performance.md` §4).

Each clinic is registered the way production registers one (`POST /users/signup`), and every
request goes through the real app, so the count is what a request in production costs.
"""

from collections.abc import Iterator

import pytest
from fastapi.testclient import TestClient
from httpx import Response

from app.core.server_timing import SERVER_TIMING_HEADER
from tests.patients.conftest import PatientsApi, TenantSession


def round_trips(response: Response) -> int:
    """The database round trips the app spent on this response (its `Server-Timing` `db-rt`)."""
    for metric in response.headers[SERVER_TIMING_HEADER].split(", "):
        name, _, value = metric.partition(";")
        if name == "db-rt":
            return int(value.split("=", 1)[1].strip('"'))
    raise AssertionError(f"no db-rt in {response.headers[SERVER_TIMING_HEADER]!r}")


@pytest.fixture
def clinic(client: TestClient) -> Iterator[TenantSession]:
    """A freshly registered clinic and its owner's session; its rows are removed afterwards."""
    api = PatientsApi(client)
    try:
        yield api.register(clinic_name="Round Trip Clinic")
    finally:
        api.cleanup()
