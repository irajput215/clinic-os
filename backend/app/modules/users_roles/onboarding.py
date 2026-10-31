"""A prescriber's onboarding pack: the credential vault, the agreement, and pack status.

docs3 feature 02 (manual §15.2, App. C), requirements R10-R16.

**Pack status is derived, never stored.** `missing_items` is the one query that answers "what stops
this person signing?": an attested agreement, an `ACTIVE` unexpired AHPRA registration and prescriber
number, and the current version of every SOP marked *required for onboarding* that applies to the
person's roles. The pack dialog, the staff list and the signing gate all call it, so they cannot
disagree. A person with no rows at all is missing everything (fail closed).

**Identifier values** are encrypted with the field-encryption envelope (D13), bound to the tenant and
the identifier kind. They are read back only to mask them; no route returns a value, and no log, audit
payload or error carries one (INV-5). Each change needs a step-up bound to
`practitioner.identifier_update` and the practitioner, and is audited with the kind and status only.

**Verification is an attestation** (D9): who checked, when and how. There is no live AHPRA or HI
Service lookup yet.

Pending vault entries are derived too: a prescriber with no row for a kind reads as `MISSING`, so a role
grant needs no side effect here.
"""

import re
import uuid
from collections.abc import Iterable, Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from typing import Final, cast

from fastapi import status
from sqlalchemy import text
from sqlmodel import Session, col, select

from app.core import field_crypto
from app.core.db import tenant_transaction
from app.models import User
from app.modules.audit import service as audit
from app.modules.identity_tenancy import service as identity
from app.modules.users_roles.models import (
    IDENTIFIER_KINDS,
    PractitionerAgreement,
    PractitionerIdentifier,
)
from app.modules.users_roles.policy import Actor
from app.modules.users_roles.schemas import (
    AgreementCreate,
    AgreementRead,
    IdentifierKind,
    IdentifierRead,
    IdentifierState,
    IdentifierUpdate,
    OnboardingPackRead,
    PackSopRead,
)

CONFIGURE: Final = "tenant:configure"
AUDIT_READ: Final = "audit:read"
STEP_UP_OPERATION: Final = "practitioner.identifier_update"
IDENTIFIER_UPDATE: Final = "practitioner.identifier_update"
AGREEMENT_RECORD: Final = "practitioner.agreement_record"
ONBOARDING_READ: Final = "practitioner.onboarding_read"
PRESCRIBER_NOT_READY: Final = "PRESCRIBER_NOT_READY"
IDENTIFIER_FORMAT: Final = "IDENTIFIER_FORMAT"
VERIFICATION_REQUIRED: Final = "VERIFICATION_REQUIRED"
USER_NOT_FOUND: Final = "USER_NOT_FOUND"

#: The roles whose holders need a pack before they prescribe (R10). The signing gate itself applies to
#: anyone who signs, whatever role let them.
PRESCRIBER_ROLES: Final[frozenset[str]] = frozenset({"DOCTOR", "AUTHORISED_PRESCRIBER"})
#: The identifiers the pack requires (R14). HPI-I and the provider number are recorded but optional
#: until eScripts and Medicare billing need them.
REQUIRED_IDENTIFIERS: Final[tuple[str, ...]] = ("AHPRA", "PRESCRIBER_NUMBER")
EXPIRING_WITHIN: Final = timedelta(days=60)

LABELS: Final[dict[str, str]] = {
    "AHPRA": "AHPRA registration",
    "HPI_I": "HPI-I",
    "PRESCRIBER_NUMBER": "Prescriber number",
    "PROVIDER_NUMBER": "Medicare provider number",
}
#: R12, to be confirmed against each issuer (D16). Values are normalised (spaces removed, upper case)
#: before they are checked.
FORMATS: Final[dict[str, tuple[re.Pattern[str], str]]] = {
    "AHPRA": (
        re.compile(r"^[A-Z]{3}\d{10}$"),
        "three letters and 10 digits, e.g. MED0001234567",
    ),
    "HPI_I": (re.compile(r"^800361\d{10}$"), "16 digits starting 800361"),
    "PRESCRIBER_NUMBER": (re.compile(r"^\d{7}$"), "7 digits"),
    "PROVIDER_NUMBER": (
        re.compile(r"^\d{6}[0-9A-Z][A-Z]$"),
        "6 digits, a location character and a check letter, e.g. 2123456A",
    ),
}


class OnboardingRefused(Exception):  # noqa: N818 - a refusal, answered by the router
    def __init__(self, status_code: int, code: str, message: str) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.code = code
        self.message = message


def _not_found() -> OnboardingRefused:
    return OnboardingRefused(
        status.HTTP_404_NOT_FOUND, USER_NOT_FOUND, "Person not found"
    )


@contextmanager
def _transaction(actor: Actor) -> Iterator[Session]:
    with tenant_transaction(
        tenant_id=actor.tenant_id, actor_id=actor.user_id, actor_role=actor.actor_role
    ) as session:
        yield session


# -- pack status ------------------------------------------------------------------------------------

_MISSING = text(
    """
    WITH people AS (SELECT unnest(CAST(:users AS uuid[])) AS user_id),
    held AS (
        SELECT ur.user_id, array_agg(r.code::text) AS codes
        FROM user_roles ur
        JOIN roles r ON r.id = ur.role_id AND r.tenant_id = ur.tenant_id
        WHERE ur.tenant_id = :tenant AND ur.user_id = ANY(CAST(:users AS uuid[]))
        GROUP BY ur.user_id
    )
    SELECT people.user_id,
        array_remove(ARRAY[
            CASE WHEN NOT EXISTS (
                SELECT 1 FROM practitioner_agreements a
                WHERE a.tenant_id = :tenant AND a.user_id = people.user_id
            ) THEN 'AGREEMENT' END,
            CASE WHEN NOT EXISTS (
                SELECT 1 FROM practitioner_identifiers i
                WHERE i.tenant_id = :tenant AND i.user_id = people.user_id
                  AND i.kind = 'AHPRA' AND i.status = 'ACTIVE'
                  AND (i.expires_on IS NULL OR i.expires_on >= current_date)
            ) THEN 'AHPRA' END,
            CASE WHEN NOT EXISTS (
                SELECT 1 FROM practitioner_identifiers i
                WHERE i.tenant_id = :tenant AND i.user_id = people.user_id
                  AND i.kind = 'PRESCRIBER_NUMBER' AND i.status = 'ACTIVE'
                  AND (i.expires_on IS NULL OR i.expires_on >= current_date)
            ) THEN 'PRESCRIBER_NUMBER' END
        ], NULL)
        || COALESCE((
            SELECT array_agg('SOP:' || s.id::text ORDER BY lower(s.title), s.id)
            FROM sops s
            WHERE s.tenant_id = :tenant AND s.required_for_onboarding
              AND (cardinality(s.applies_to_roles) = 0
                   OR s.applies_to_roles && COALESCE(held.codes, '{}'::text[]))
              AND NOT EXISTS (
                  SELECT 1 FROM sop_acknowledgements k
                  WHERE k.tenant_id = :tenant AND k.sop_id = s.id
                    AND k.version = s.current_version AND k.user_id = people.user_id
              )
        ), '{}'::text[]) AS missing
    FROM people LEFT JOIN held ON held.user_id = people.user_id
    """
)


def missing_for_many(
    session: Session, *, tenant_id: uuid.UUID, user_ids: Iterable[uuid.UUID]
) -> dict[uuid.UUID, list[str]]:
    """What each person's pack lacks, in one statement on the caller's transaction."""
    wanted = sorted(set(user_ids))
    if not wanted:
        return {}
    rows = session.connection().execute(
        _MISSING, {"tenant": tenant_id, "users": wanted}
    )
    return {user_id: list(missing) for user_id, missing in rows}


def missing_items(
    session: Session, *, tenant_id: uuid.UUID, user_id: uuid.UUID
) -> list[str]:
    """What stops this person signing (R14, R15). Empty means the pack is complete."""
    return missing_for_many(session, tenant_id=tenant_id, user_ids=[user_id])[user_id]


# -- the pack -------------------------------------------------------------------------------------


def _target(session: Session, *, tenant_id: uuid.UUID, user_id: uuid.UUID) -> User:
    user = session.exec(
        select(User).where(User.id == user_id, User.tenant_id == tenant_id)
    ).first()
    if user is None:
        raise _not_found()
    return user


def _role_codes(
    session: Session, *, tenant_id: uuid.UUID, user_id: uuid.UUID
) -> list[str]:
    rows = session.connection().execute(
        text(
            "SELECT DISTINCT r.code FROM user_roles ur JOIN roles r ON r.id = ur.role_id "
            "AND r.tenant_id = ur.tenant_id WHERE ur.tenant_id = :t AND ur.user_id = :u "
            "ORDER BY r.code"
        ),
        {"t": tenant_id, "u": user_id},
    )
    return [code for (code,) in rows]


def _names(
    session: Session, *, tenant_id: uuid.UUID, user_ids: Iterable[uuid.UUID | None]
) -> dict[uuid.UUID, str]:
    wanted = sorted({user_id for user_id in user_ids if user_id is not None})
    if not wanted:
        return {}
    rows = session.exec(
        select(col(User.id), col(User.full_name), col(User.email)).where(
            col(User.tenant_id) == tenant_id, col(User.id).in_(wanted)
        )
    ).all()
    return {user_id: full_name or email for user_id, full_name, email in rows}


def _state(row: PractitionerIdentifier | None, today: date) -> IdentifierState:
    if row is None:
        return "MISSING"
    if row.status == "PENDING":
        return "PENDING"
    if row.expires_on is not None:
        if row.expires_on < today:
            return "EXPIRED"
        if row.expires_on <= today + EXPIRING_WITHIN:
            return "EXPIRING"
    return "ACTIVE"


def _pack(session: Session, *, tenant_id: uuid.UUID, user: User) -> OnboardingPackRead:
    roles = _role_codes(session, tenant_id=tenant_id, user_id=user.id)
    missing = missing_items(session, tenant_id=tenant_id, user_id=user.id)
    identifiers = {
        row.kind: row
        for row in session.exec(
            select(PractitionerIdentifier).where(
                PractitionerIdentifier.tenant_id == tenant_id,
                PractitionerIdentifier.user_id == user.id,
            )
        ).all()
    }
    agreement = session.exec(
        select(PractitionerAgreement)
        .where(
            PractitionerAgreement.tenant_id == tenant_id,
            PractitionerAgreement.user_id == user.id,
        )
        .order_by(col(PractitionerAgreement.attested_at).desc())
        .limit(1)
    ).first()
    sops = (
        session.connection()
        .execute(
            text(
                """
            SELECT s.id, s.title, s.current_version,
                (SELECT max(k.version) FROM sop_acknowledgements k
                 WHERE k.tenant_id = s.tenant_id AND k.sop_id = s.id AND k.user_id = :u)
            FROM sops s
            WHERE s.tenant_id = :t AND s.required_for_onboarding
              AND (cardinality(s.applies_to_roles) = 0
                   OR s.applies_to_roles && CAST(:roles AS text[]))
            ORDER BY lower(s.title), s.id
            """
            ),
            {"t": tenant_id, "u": user.id, "roles": roles},
        )
        .all()
    )
    names = _names(
        session,
        tenant_id=tenant_id,
        user_ids=[
            *(row.verified_by for row in identifiers.values()),
            agreement.attested_by if agreement else None,
        ],
    )
    today = datetime.now(UTC).date()

    def masked(row: PractitionerIdentifier) -> str | None:
        return field_crypto.mask(
            field_crypto.decrypt(
                row.value_ciphertext, tenant_id=tenant_id, kind=_crypto_kind(row.kind)
            )
        )

    return OnboardingPackRead(
        user_id=user.id,
        name=user.full_name or user.email,
        role_codes=roles,
        is_prescriber=bool(PRESCRIBER_ROLES & set(roles)),
        pack_complete=not missing,
        missing=missing,
        agreement=(
            AgreementRead(
                agreement_version=agreement.agreement_version,
                signed_on=agreement.signed_on,
                attested_by_name=names.get(agreement.attested_by),
                attested_at=agreement.attested_at,
            )
            if agreement
            else None
        ),
        identifiers=[
            IdentifierRead(
                kind=cast(IdentifierKind, kind),
                label=LABELS[kind],
                required=kind in REQUIRED_IDENTIFIERS,
                state=_state(row, today),
                masked=masked(row) if row else None,
                expires_on=row.expires_on if row else None,
                verified_by_name=names.get(row.verified_by)
                if row and row.verified_by
                else None,
                verified_at=row.verified_at if row else None,
                verification_method=row.verification_method if row else None,
            )
            for kind in IDENTIFIER_KINDS
            for row in [identifiers.get(kind)]
        ],
        sops=[
            PackSopRead(
                id=sop_id,
                title=title,
                current_version=current,
                acknowledged_version=acked,
            )
            for sop_id, title, current, acked in sops
        ],
    )


def _may_read(actor: Actor, user_id: uuid.UUID) -> bool:
    return user_id == actor.user_id or bool({CONFIGURE, AUDIT_READ} & actor.permissions)


def read_pack(*, actor: Actor, user_id: uuid.UUID) -> OnboardingPackRead:
    """A person's pack: themself, or `tenant:configure` / `audit:read` (R16). Audited."""
    if not _may_read(actor, user_id):
        raise OnboardingRefused(
            status.HTTP_403_FORBIDDEN,
            "PERMISSION_NOT_HELD",
            "Only the person themself, or someone who configures the practice, can see this pack.",
        )
    with _transaction(actor) as session:
        user = _target(session, tenant_id=actor.tenant_id, user_id=user_id)
        pack = _pack(session, tenant_id=actor.tenant_id, user=user)
        audit.record(
            session,
            audit.AuditEvent(
                action=ONBOARDING_READ,
                result="SUCCESS",
                resource_id=user_id,
                payload={"target_user_id": str(user_id)},
            ),
        )
        return pack


def _crypto_kind(kind: str) -> str:
    return f"practitioner_{kind.lower()}"


def normalise(kind: str, value: str) -> str:
    """The stored form of an identifier, or `OnboardingRefused` naming the expected format (R12)."""
    cleaned = re.sub(r"[\s-]", "", value).upper()
    pattern, expected = FORMATS[kind]
    if not pattern.fullmatch(cleaned):
        raise OnboardingRefused(
            status.HTTP_422_UNPROCESSABLE_CONTENT,
            IDENTIFIER_FORMAT,
            f"{LABELS[kind]} should be {expected}.",
        )
    return cleaned


def update_identifier(
    *, actor: Actor, user_id: uuid.UUID, kind: str, body: IdentifierUpdate
) -> OnboardingPackRead:
    """Record or re-verify one identifier: format, then the person, then the step-up (R11, R12)."""
    value = normalise(kind, body.value) if body.value is not None else None
    if body.status == "ACTIVE" and not body.verification_method:
        raise OnboardingRefused(
            status.HTTP_422_UNPROCESSABLE_CONTENT,
            VERIFICATION_REQUIRED,
            "Say how the identifier was checked before marking it active.",
        )
    with _transaction(actor) as session:
        user = _target(session, tenant_id=actor.tenant_id, user_id=user_id)
        # A refused step-up is audited by `consume_step_up`; the refusal is raised only after this
        # transaction commits, so that audit row is kept.
        stepped_up = identity.consume_step_up(
            session,
            tenant_id=actor.tenant_id,
            user_id=actor.user_id,
            operation=STEP_UP_OPERATION,
            resource_id=user_id,
            token=body.step_up_token,
        )
        if stepped_up:
            pack = _write_identifier(
                session, actor=actor, user=user, kind=kind, value=value, body=body
            )
    if not stepped_up:
        raise OnboardingRefused(
            status.HTTP_403_FORBIDDEN,
            identity.STEP_UP_REQUIRED,
            "Changing a practitioner's identifiers needs a fresh step-up: re-enter your password.",
        )
    return pack


def _write_identifier(
    session: Session,
    *,
    actor: Actor,
    user: User,
    kind: str,
    value: str | None,
    body: IdentifierUpdate,
) -> OnboardingPackRead:
    row = session.exec(
        select(PractitionerIdentifier)
        .where(
            PractitionerIdentifier.tenant_id == actor.tenant_id,
            PractitionerIdentifier.user_id == user.id,
            PractitionerIdentifier.kind == kind,
        )
        .with_for_update()
    ).first()
    if row is None and value is None:
        raise OnboardingRefused(
            status.HTTP_422_UNPROCESSABLE_CONTENT,
            IDENTIFIER_FORMAT,
            f"Enter the {LABELS[kind]}.",
        )
    now = datetime.now(UTC)
    if row is None:
        row = PractitionerIdentifier(
            tenant_id=actor.tenant_id,
            user_id=user.id,
            kind=kind,
            value_ciphertext=b"",
            updated_by=actor.user_id,
        )
    if value is not None:
        row.value_ciphertext = field_crypto.encrypt(
            value, tenant_id=actor.tenant_id, kind=_crypto_kind(kind)
        )
    row.status = body.status
    row.expires_on = body.expires_on
    if body.status == "ACTIVE":
        row.verified_by = actor.user_id
        row.verified_at = now
        row.verification_method = body.verification_method
    else:
        row.verified_by = None
        row.verified_at = None
        row.verification_method = None
    row.updated_by = actor.user_id
    row.updated_at = now
    session.add(row)
    session.flush()
    audit.record(
        session,
        audit.AuditEvent(
            action=IDENTIFIER_UPDATE,
            result="SUCCESS",
            resource_id=user.id,
            payload={
                "target_user_id": str(user.id),
                "kind": kind,
                "to_state": body.status,
                "step_up": True,
            },
        ),
    )
    return _pack(session, tenant_id=actor.tenant_id, user=user)


def record_agreement(
    *, actor: Actor, user_id: uuid.UUID, body: AgreementCreate
) -> OnboardingPackRead:
    """Record that the practitioner signed agreement version X on date Y, attested by the caller."""
    if body.signed_on > datetime.now(UTC).date() + timedelta(days=1):
        raise OnboardingRefused(
            status.HTTP_422_UNPROCESSABLE_CONTENT,
            "SIGNED_ON_FUTURE",
            "The signing date can't be in the future.",
        )
    with _transaction(actor) as session:
        user = _target(session, tenant_id=actor.tenant_id, user_id=user_id)
        session.add(
            PractitionerAgreement(
                tenant_id=actor.tenant_id,
                user_id=user_id,
                agreement_version=body.agreement_version.strip(),
                signed_on=body.signed_on,
                attested_by=actor.user_id,
            )
        )
        session.flush()
        audit.record(
            session,
            audit.AuditEvent(
                action=AGREEMENT_RECORD,
                result="SUCCESS",
                resource_id=user_id,
                payload={
                    "target_user_id": str(user_id),
                    "version": body.agreement_version.strip(),
                },
            ),
        )
        return _pack(session, tenant_id=actor.tenant_id, user=user)


@dataclass(frozen=True)
class NotReady:
    """The signing gate's refusal (R15): every missing item, named."""

    missing: list[str]


def signing_readiness(
    session: Session, *, tenant_id: uuid.UUID, user_id: uuid.UUID
) -> NotReady | None:
    """`None` when the signer's pack is complete; otherwise what is missing. On the signing
    transaction, so the answer is the one the signature commits against."""
    missing = missing_items(session, tenant_id=tenant_id, user_id=user_id)
    return NotReady(missing) if missing else None
