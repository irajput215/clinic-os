"""The deploy guard must refuse a database move, and must not refuse a credential fix."""

import json
from pathlib import Path

import pytest

from scripts.check_database_target import main

DEPLOYED = "postgresql://neondb_owner:old@ep-blue-truth-pooler.ap-southeast-2.aws.neon.tech/neondb"
SECRET_SAME_HOST = "postgresql://neondb_owner:new@ep-blue-truth-pooler.ap-southeast-2.aws.neon.tech/neondb"
SECRET_OTHER_HOST = "postgresql://neondb_owner:new@ep-somewhere-else-pooler.ap-southeast-2.aws.neon.tech/neondb"


def _cloud_payload(tmp_path: Path, url: str) -> Path:
    target = tmp_path / "deployed_database.json"
    target.write_text(
        json.dumps({"data": {"variable": {"name": "DATABASE_URL", "value": url}}})
    )
    return target


def test_allows_a_rotated_password_on_the_same_database(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """This is the case the sync exists for: same database, corrected credential."""
    monkeypatch.setenv("DATABASE_URL", SECRET_SAME_HOST)

    assert main([str(_cloud_payload(tmp_path, DEPLOYED))]) == 0


def test_refuses_to_repoint_the_deployment_at_another_database(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("DATABASE_URL", SECRET_OTHER_HOST)

    assert main([str(_cloud_payload(tmp_path, DEPLOYED))]) == 1


def test_fails_closed_when_the_secret_is_empty(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """An unset secret must never be synced over a working value."""
    monkeypatch.setenv("DATABASE_URL", "")

    assert main([str(_cloud_payload(tmp_path, DEPLOYED))]) == 1


def test_fails_closed_on_an_unexpected_payload(tmp_path: Path) -> None:
    target = tmp_path / "deployed_database.json"
    target.write_text(json.dumps({"unexpected": True}))

    with pytest.raises(KeyError):
        main([str(target)])
