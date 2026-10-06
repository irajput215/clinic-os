"""Control 1: access tokens are short-lived.

`docs/reference/build-contract.md` §6 control 1 — *"15-minute access tokens"* — and
`docs/features/02-authentication/01-requirements.md` R3: *"Access tokens are short-lived and refused
after expiry."* The source conflicts on the value (10 minutes in doc 06 §3 against 15 in doc 02 §1 and
doc 03 §4, recorded as OPEN-2); this repository adopts the 15 the build contract states.

Until refresh-token rotation lands, this lifetime **is** the whole session: feature 02 specifies
rotation, family revocation and a deny list (R4–R7) but they are blocked by D-003, so a stolen token
is useful for 15 minutes and no longer. The test decodes the token the login route actually issued
rather than reading the setting back, so it proves the configured lifetime reaches the client.
"""

from datetime import UTC, datetime, timedelta

import jwt
from fastapi.testclient import TestClient

from app.core import security
from app.core.config import settings

# The route runs in milliseconds; a generous slack still distinguishes 15 minutes from the 8 days
# the template shipped, and from a 10-minute value.
_LOWER_BOUND = timedelta(minutes=14, seconds=30)
_UPPER_BOUND = timedelta(minutes=15)


def test_issued_access_token_lives_fifteen_minutes(client: TestClient) -> None:
    response = client.post(
        f"{settings.API_V1_STR}/login/access-token",
        data={
            "username": settings.FIRST_SUPERUSER,
            "password": settings.FIRST_SUPERUSER_PASSWORD,
        },
    )
    assert response.status_code == 200

    payload = jwt.decode(
        response.json()["access_token"],
        settings.SECRET_KEY,
        algorithms=[security.ALGORITHM],
    )
    remaining = datetime.fromtimestamp(payload["exp"], tz=UTC) - datetime.now(UTC)

    assert _LOWER_BOUND < remaining <= _UPPER_BOUND
