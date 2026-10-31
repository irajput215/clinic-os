"""Complete a prescriber's onboarding pack through the API (docs3 feature 02).

Signing a script needs an attested agreement and active AHPRA and prescriber numbers (the signing gate,
R15). Fixtures that sign call `make_ready` once for each prescriber, as an owner would in the product:
each identifier change carries its own step-up.
"""

import random
import uuid

from fastapi.testclient import TestClient

from app.core.config import settings

API = settings.API_V1_STR


def step_up(
    client: TestClient, headers: dict[str, str], password: str, user_id: uuid.UUID
) -> str:
    response = client.post(
        f"{API}/auth/step-up",
        json={
            "password": password,
            "operation": "practitioner.identifier_update",
            "resource_id": str(user_id),
        },
        headers=headers,
    )
    assert response.status_code == 201, response.text
    return str(response.json()["step_up_token"])


def make_ready(
    client: TestClient,
    *,
    configurer_headers: dict[str, str],
    configurer_password: str,
    user_id: uuid.UUID,
) -> None:
    agreement = client.post(
        f"{API}/users/{user_id}/agreements",
        json={"agreement_version": "2026-1", "signed_on": "2026-01-05"},
        headers=configurer_headers,
    )
    assert agreement.status_code == 201, agreement.text
    for kind, value in (
        ("AHPRA", f"MED{random.randint(0, 10**10 - 1):010d}"),
        ("PRESCRIBER_NUMBER", f"{random.randint(0, 10**7 - 1):07d}"),
    ):
        response = client.put(
            f"{API}/users/{user_id}/identifiers/{kind}",
            json={
                "value": value,
                "status": "ACTIVE",
                "verification_method": "AHPRA public register",
                "step_up_token": step_up(
                    client, configurer_headers, configurer_password, user_id
                ),
            },
            headers=configurer_headers,
        )
        assert response.status_code == 200, response.text
    assert response.json()["pack_complete"], response.json()["missing"]
