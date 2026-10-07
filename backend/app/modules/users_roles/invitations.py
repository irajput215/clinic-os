"""Staff invitation links: issue, read, and the email that carries one.

Design: `docs/features/03-users-and-roles/03-design.md` "Endpoints" (`POST /api/v1/users`, "invite")
and R10 (*"Invitations expire if not accepted inside the configured window"*). No table holds an
invitation (no schema change), so the link is a signed token and its three properties come from what
it signs (the mechanism is `app.core.password_bound_tokens`, shared with password recovery):

- **Purpose-bound.** The token is signed with a key derived from `SECRET_KEY` for this purpose only,
  so it never verifies as an access token (whose `sub` is also a user id) or as a password-reset
  token, and neither of those verifies here. A `purpose` claim is checked as well.
- **Expiring.** `exp` is `STAFF_INVITATION_EXPIRE_HOURS` after issue.
- **Single use.** The token carries a keyed fingerprint of the account's password hash at issue. The
  invitation sets a new password, which changes the hash, so the same link can never be spent twice;
  a password set any other way (password recovery) retires the link too. The fingerprint is an HMAC,
  so the token discloses nothing about the hash.

The admin never sets or sees a password: the account is created with the hash of a random secret that
is discarded at once, so nobody can sign in until the invitee chooses a password through the link.
"""

import html
import secrets
import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta

from app import utils
from app.core.config import settings
from app.core.password_bound_tokens import LinkClaims, PasswordBoundToken
from app.core.security import get_password_hash

PURPOSE = "staff-invitation"
_LINK = PasswordBoundToken(purpose=PURPOSE, key_label=b"clinicos/staff-invitation/v1")


def _key() -> bytes:
    """The signing key for invitation tokens, derived from `SECRET_KEY` and never used elsewhere."""
    return _LINK.key()


def fingerprint(hashed_password: str) -> str:
    """A keyed digest of the account's password hash, which binds a token to one password state."""
    return _LINK.fingerprint(hashed_password)


def unusable_password_hash() -> str:
    """The hash of a random secret nobody is told: the account exists but cannot sign in yet."""
    return get_password_hash(secrets.token_urlsafe(32))


def issue(
    *, user_id: uuid.UUID, hashed_password: str, now: datetime | None = None
) -> str:
    """Sign an invitation link token for one account in its current password state."""
    return _LINK.issue(
        subject=str(user_id),
        hashed_password=hashed_password,
        lifetime=timedelta(hours=settings.STAFF_INVITATION_EXPIRE_HOURS),
        now=now,
    )


@dataclass(frozen=True)
class InvitationClaims:
    user_id: uuid.UUID
    password_fingerprint: str


def read(token: str) -> InvitationClaims | None:
    """The claims of a valid, unexpired invitation token, or `None` for anything else.

    One answer for tampered, expired, wrong-purpose and malformed tokens, so the response cannot be
    used to tell them apart. Whether the link was already spent is decided by the caller, against the
    account's current password hash.
    """
    claims = _LINK.read(token)
    if claims is None:
        return None
    try:
        user_id = uuid.UUID(claims.subject)
    except ValueError:
        return None
    return InvitationClaims(
        user_id=user_id, password_fingerprint=claims.password_fingerprint
    )


def still_unspent(claims: InvitationClaims, hashed_password: str) -> bool:
    """Whether the account is still in the password state the link was issued for."""
    return _LINK.still_unspent(
        LinkClaims(
            subject=str(claims.user_id),
            password_fingerprint=claims.password_fingerprint,
        ),
        hashed_password,
    )


def send_invitation_email(
    *, email_to: str, full_name: str, organisation: str | None, token: str
) -> None:
    """Email the invitation link. The link lands on the app's `/accept-invite` page.

    The token travels in the link's query string, exactly as the password-reset link does; the page
    sends it to the API only in a request body.
    """
    link = f"{settings.FRONTEND_HOST}/accept-invite?token={token}"
    joining = organisation or "your clinic"
    # `render_email_template` does not autoescape, and the name and the organisation are typed by
    # people, so every value is escaped here: a name cannot inject markup into the email.
    html_content = utils.render_email_template(
        template_name="staff_invitation.html",
        context={
            key: html.escape(value)
            for key, value in {
                "project_name": settings.PROJECT_NAME,
                "full_name": full_name,
                "organisation": joining,
                "email": email_to,
                "valid_hours": str(settings.STAFF_INVITATION_EXPIRE_HOURS),
                "link": link,
            }.items()
        },
    )
    utils.send_email(
        email_to=email_to,
        subject=f"{settings.PROJECT_NAME} - You're invited to join {joining}",
        html_content=html_content,
    )
