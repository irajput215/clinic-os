"""Fixtures for the tenant-resolution tests.

The `rbac` fixture mirrors the one in `tests/rbac`, `tests/security` and `tests/users`: it registers
an organisation through the real signup route and removes everything it created afterwards. Tenants
are global rows, so a leaked one would be visible to later tests.
"""

from collections.abc import Iterator

import pytest
from fastapi.testclient import TestClient
from sqlmodel import Session

from tests.utils.rbac import RbacApi


@pytest.fixture
def rbac(client: TestClient, db: Session) -> Iterator[RbacApi]:
    helper = RbacApi(client, db)
    yield helper
    helper.cleanup()
