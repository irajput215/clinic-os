"""Fixtures for the TGA inbox (FEAT-09, D-011) tests.

Organisations are created through the real signup flow, messages are delivered through the real ingest
route with the mailbox token, and the review is driven through the API. The PDFs are built here with
the standard library (`make_pdf`), so the text-layer reader is exercised on real PDF structure. All
data is synthetic; the IHIs and Medicare numbers are generated with valid check digits and belong to
nobody.
"""

import base64
import uuid
import zlib
from collections.abc import Iterator
from datetime import UTC, datetime
from typing import Any, NamedTuple

import pytest
from fastapi.testclient import TestClient
from httpx2 import Response
from pydantic import SecretStr
from sqlalchemy import text
from sqlmodel import Session

from app.core.config import settings
from app.core.db import engine
from app.modules.tga_inbox import adapters
from tests.utils.rbac import ActorSession, RbacApi

API = settings.API_V1_STR
INBOX = f"{API}/tga-inbox"
TOKEN = "t" * 40
TGA_DOMAIN = "tga.example.gov.au"


def luhn_complete(prefix: str) -> str:
    """`prefix` plus the Luhn check digit (synthetic healthcare identifiers)."""
    for digit in "0123456789":
        candidate = prefix + digit
        total = 0
        for index, char in enumerate(reversed(candidate)):
            number = int(char)
            if index % 2 == 1:
                number = number * 2 - 9 if number * 2 > 9 else number * 2
            total += number
        if total % 10 == 0:
            return candidate
    raise AssertionError("unreachable")


def medicare_number(first_eight: str = "29501234") -> str:
    weights = (1, 3, 7, 9, 1, 3, 7, 9)
    check = sum(int(d) * w for d, w in zip(first_eight, weights, strict=True)) % 10
    return f"{first_eight}{check}1"


SYNTHETIC_IHI = luhn_complete("800360" + "123456789")
SYNTHETIC_HPI_I = luhn_complete("800361" + "987654321")
SYNTHETIC_MEDICARE = medicare_number()


def _escape(line: str) -> str:
    return line.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)")


def make_pdf(
    pages: list[list[str]], *, compress: bool = True, extra: bytes = b""
) -> bytes:
    """A minimal valid PDF with one Helvetica text line per entry, one content stream per page."""
    objects: list[bytes] = []
    page_ids: list[int] = []
    # 1: catalog, 2: pages, 3: font; then per page: page object, content object.
    next_id = 4
    bodies: dict[int, bytes] = {}
    for lines in pages:
        content = (
            b"BT /F1 11 Tf 72 760 Td 14 TL\n"
            + b"".join(f"({_escape(line)}) Tj T*\n".encode("latin-1") for line in lines)
            + b"ET"
        )
        if compress:
            data = zlib.compress(content)
            stream = (
                b"<< /Length %d /Filter /FlateDecode >>\nstream\n" % len(data)
                + data
                + b"\nendstream"
            )
        else:
            stream = (
                b"<< /Length %d >>\nstream\n" % len(content) + content + b"\nendstream"
            )
        page_id, content_id = next_id, next_id + 1
        next_id += 2
        page_ids.append(page_id)
        bodies[page_id] = (
            b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 595 842] "
            b"/Resources << /Font << /F1 3 0 R >> >> /Contents %d 0 R >>" % content_id
        )
        bodies[content_id] = stream
    kids = b" ".join(b"%d 0 R" % pid for pid in page_ids)
    bodies[1] = b"<< /Type /Catalog /Pages 2 0 R >>"
    bodies[2] = b"<< /Type /Pages /Kids [" + kids + b"] /Count %d >>" % len(page_ids)
    bodies[3] = b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>"
    out = bytearray(b"%PDF-1.4\n")
    offsets: dict[int, int] = {}
    for object_id in sorted(bodies):
        offsets[object_id] = len(out)
        out += b"%d 0 obj\n" % object_id + bodies[object_id] + b"\nendobj\n"
    out += extra
    xref = len(out)
    out += b"xref\n0 %d\n0000000000 65535 f \n" % (len(bodies) + 1)
    for object_id in sorted(bodies):
        out += b"%010d 00000 n \n" % offsets[object_id]
    out += b"trailer\n<< /Size %d /Root 1 0 R >>\nstartxref\n%d\n%%%%EOF\n" % (
        len(bodies) + 1,
        xref,
    )
    del objects
    return bytes(out)


def approval_letter(**overrides: str) -> list[list[str]]:
    values = {
        "reference": "SAS-2026-004512",
        "name": "Ada Synthetic",
        "dob": "01/01/1990",
        "ihi": " ".join(SYNTHETIC_IHI[i : i + 4] for i in range(0, 16, 4)),
        "medicare": SYNTHETIC_MEDICARE,
        "category": "Category 3",
        "form": "Oral oil",
        "valid_from": "1 March 2026",
        "valid_to": "28/02/2027",
        "prescriber": "Dr Grace Example",
        "hpii": SYNTHETIC_HPI_I,
    }
    values.update(overrides)
    return [
        [
            "Therapeutic Goods Administration",
            "Special Access Scheme - Category B approval",
            f"Approval number: {values['reference']}",
            f"Patient name: {values['name']}",
            f"Date of birth: {values['dob']}",
            f"IHI: {values['ihi']}",
            f"Medicare number: {values['medicare']}",
        ],
        [
            f"Product category: {values['category']}",
            f"Dosage form: {values['form']}",
            f"Valid from: {values['valid_from']}",
            f"Valid until: {values['valid_to']}",
            f"Prescriber: {values['prescriber']}",
            f"Prescriber HPI-I: {values['hpii']}",
        ],
    ]


class InboxApi:
    def __init__(self, client: TestClient, db: Session) -> None:
        self.client = client
        self.rbac = RbacApi(client, db)
        self.tenant_ids: list[uuid.UUID] = []

    def register(self) -> ActorSession:
        actor = self.rbac.register_tenant(
            clinic_name=f"Inbox Clinic {uuid.uuid4().hex[:6]}"
        )
        assert actor.tenant_id is not None
        self.tenant_ids.append(actor.tenant_id)
        return actor

    def add(self, owner: ActorSession, role_code: str) -> ActorSession:
        assert owner.tenant_id is not None
        return self.rbac.add_actor(
            tenant_id=owner.tenant_id, granted_by=owner.user_id, role_code=role_code
        )

    def create_patient(self, actor: ActorSession, **overrides: Any) -> uuid.UUID:
        body = {
            "given_name": "Ada",
            "family_name": "Synthetic",
            "date_of_birth": "1990-01-01",
        }
        response = self.client.post(
            f"{API}/patients", json={**body, **overrides}, headers=actor.headers
        )
        assert response.status_code == 201, response.text
        return uuid.UUID(response.json()["id"])

    def address(self, tenant_id: uuid.UUID) -> str:
        return f"tga+{tenant_id}@{settings.TGA_INBOX_DOMAIN}"

    def deliver(
        self,
        to_tenant: uuid.UUID,
        /,
        *,
        attachments: list[tuple[str, str, bytes]] | None = None,
        token: str = TOKEN,
        **overrides: Any,
    ) -> Response:
        if attachments is None:
            attachments = [
                ("approval.pdf", "application/pdf", make_pdf(approval_letter()))
            ]
        body: dict[str, Any] = {
            "provider_message_id": f"<{uuid.uuid4()}@{TGA_DOMAIN}>",
            "from_address": f"approvals@{TGA_DOMAIN}",
            "to_address": self.address(to_tenant),
            "subject": "SAS approval for Ada Synthetic",
            "received_at": datetime.now(UTC).isoformat(),
            "spf_result": "PASS",
            "dkim_result": "PASS",
            "dmarc_result": "PASS",
            "attachments": [
                {
                    "filename": name,
                    "content_type": content_type,
                    "content_base64": base64.b64encode(data).decode("ascii"),
                }
                for name, content_type, data in attachments
            ],
        }
        body.update(overrides)
        return self.client.post(
            f"{INBOX}/messages", json=body, headers={"Authorization": f"Bearer {token}"}
        )

    def delivered(self, to_tenant: uuid.UUID, /, **kwargs: Any) -> uuid.UUID:
        response = self.deliver(to_tenant, **kwargs)
        assert response.status_code == 201, response.text
        return uuid.UUID(response.json()["message_id"])

    def detail(self, actor: ActorSession, message_id: uuid.UUID) -> Response:
        return self.client.get(f"{INBOX}/messages/{message_id}", headers=actor.headers)

    def post(
        self, actor: ActorSession, message_id: uuid.UUID, verb: str, body: Any = None
    ) -> Response:
        return self.client.post(
            f"{INBOX}/messages/{message_id}/{verb}", json=body, headers=actor.headers
        )

    def audit(self, tenant_id: uuid.UUID, action: str) -> list[dict[str, Any]]:
        with engine.connect() as conn:
            rows = (
                conn.execute(
                    text(
                        "SELECT action, result, reason, resource_id FROM audit_log"
                        ' WHERE tenant_id = :t AND action = :a ORDER BY "timestamp", event_id'
                    ),
                    {"t": tenant_id, "a": action},
                )
                .mappings()
                .all()
            )
        return [dict(row) for row in rows]

    def scalar(self, sql: str, **params: Any) -> Any:
        with engine.connect() as conn:
            return conn.execute(text(sql), params).scalar_one_or_none()

    def cleanup(self) -> None:
        if self.tenant_ids:
            with engine.begin() as conn:
                for table in (
                    "tga_extraction_results",
                    "tga_inbox_attachments",
                    "tga_inbox_messages",
                    "tga_approval_events",
                    "tga_approvals",
                ):
                    conn.execute(
                        text(f"DELETE FROM {table} WHERE tenant_id = ANY(:ids)"),  # noqa: S608
                        {"ids": self.tenant_ids},
                    )
        self.rbac.cleanup()
        self.tenant_ids.clear()


class Clinic(NamedTuple):
    owner: ActorSession
    tenant_id: uuid.UUID
    patient_id: uuid.UUID


@pytest.fixture(autouse=True)
def _inbox_settings(
    monkeypatch: pytest.MonkeyPatch,
) -> Iterator[adapters.MemoryObjectStore]:
    monkeypatch.setattr(settings, "USERS_OPEN_REGISTRATION", True)
    monkeypatch.setattr(settings, "TGA_INBOX_INGEST_TOKEN", SecretStr(TOKEN))
    monkeypatch.setattr(
        settings, "TGA_INBOX_ALLOWED_SENDER_DOMAINS", ["example.gov.au"]
    )
    store = adapters.MemoryObjectStore()
    monkeypatch.setattr(adapters, "configured_store", lambda: store)
    yield store


@pytest.fixture
def inbox(client: TestClient, db: Session) -> Iterator[InboxApi]:
    helper = InboxApi(client, db)
    yield helper
    helper.cleanup()


@pytest.fixture
def clinic(inbox: InboxApi) -> Clinic:
    owner = inbox.register()
    assert owner.tenant_id is not None
    patient_id = inbox.create_patient(owner, ihi=SYNTHETIC_IHI)
    return Clinic(owner=owner, tenant_id=owner.tenant_id, patient_id=patient_id)


def code(response: Response) -> str | None:
    detail = response.json().get("detail")
    return detail.get("code") if isinstance(detail, dict) else None
