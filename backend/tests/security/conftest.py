"""Fixtures for the authorisation and access-control tests."""

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
