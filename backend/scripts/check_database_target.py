"""Refuse to point the deployment at a different database.

`fastapi deploy` ships code only and never carries configuration, so the runtime `DATABASE_URL` is
managed by hand. Changing it must fix a *credential*, not move production onto another database: a
different host is a different product decision, with a different data set, and it must never arrive
as a side effect of correcting a password.

`FASTAPI_CLOUD_TOKEN` is a deploy token, so the Deploy workflow cannot read or write the app's
environment and cannot run this check for you — `fastapi cloud env get`/`set` need an interactive
login. Run this before a manual `env set`:

    uv run fastapi cloud env get DATABASE_URL --json --app-id "$APP_ID" > /tmp/deployed.json
    DATABASE_URL="<the new value>" uv run python scripts/check_database_target.py /tmp/deployed.json
    # exit 0 -> same database, safe to set.  exit 1 -> stop and reconcile deliberately.

Only hostnames are printed, never the credential.
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit


def host_of(url: str) -> str:
    """Return the hostname of a connection URL, or an empty string if it has none."""
    return urlsplit(url).hostname or ""


def host_from_cloud_payload(payload: Any) -> str:
    """Return the hostname from `fastapi cloud env get DATABASE_URL --json` output.

    Fails closed: an unexpected payload raises rather than reporting a match.
    """
    variable = payload["data"]["variable"]
    return host_of(str(variable["value"]))


def emit(message: str) -> None:
    """Write to stdout.

    A command-line check's output *is* its interface: the Deploy workflow reads these lines from
    the job log, and `::error::` is a GitHub Actions workflow command. This is the only reason
    `print` is used here, which is why the project-wide ban is waived on this line alone.
    """
    print(message)  # noqa: T201 - a CLI's stdout is its contract


def main(argv: list[str] | None = None) -> int:
    """Compare the deployed host with the secret's host. Exit non-zero on a mismatch."""
    args = sys.argv[1:] if argv is None else argv
    if len(args) != 1:
        emit("usage: check_database_target.py <path to cloud env get --json output>")
        return 2

    deployed = host_from_cloud_payload(json.loads(Path(args[0]).read_text()))
    secret = host_of(os.environ.get("DATABASE_URL", ""))

    emit(f"deployed host: {deployed}")
    emit(f"secret host:   {secret}")

    if not secret:
        emit("::error::DATABASE_URL is empty in this workflow; refusing to sync it.")
        return 1
    if deployed != secret:
        emit(
            "::error::Refusing to sync DATABASE_URL: the GitHub secret and the live deployment "
            "point at different databases. Repointing production at another database is a "
            "deliberate change, not a side effect of a deploy."
        )
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
