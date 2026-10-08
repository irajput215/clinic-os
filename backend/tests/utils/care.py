"""Record a care relationship the way the product does: through the care-team route (T1-34, D-007).

The route is the only writer the application has, so a test that needs a relationship-bound clinician
to reach a patient asks for it there, as the practice owner, rather than inserting a row behind the
policy layer. `tests/utils/seeding.py` keeps the owner-level insert for the tests that exercise the
table itself (RLS, the interval).
"""

import uuid
from typing import Any

from fastapi.testclient import TestClient

from app.core.config import settings


def care_team_url(patient_id: uuid.UUID | str) -> str:
    return f"{settings.API_V1_STR}/patients/{patient_id}/care-relationships"


def relate(
    client: TestClient,
    manager_headers: dict[str, str],
    *,
    patient_id: uuid.UUID | str,
    practitioner_id: uuid.UUID | str,
) -> uuid.UUID:
    """Add `practitioner_id` to the patient's care team; return the new relationship's id."""
    response = client.post(
        care_team_url(patient_id),
        json={"practitioner_id": str(practitioner_id)},
        headers=manager_headers,
    )
    assert response.status_code == 201, response.text
    body: dict[str, Any] = response.json()
    [member] = [
        row for row in body["data"] if row["practitioner_id"] == str(practitioner_id)
    ]
    return uuid.UUID(member["id"])
