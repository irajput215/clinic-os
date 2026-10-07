"""Signed, purpose-bound, expiring, single-use account links - without a table.

Staff invitations and password recovery both mail a link that lets its holder set an account's
password. Neither has a table to record that a link was spent (no schema change), so each link is a
signed token whose properties come from what it signs:

- **Purpose-bound.** Each kind of link is signed with its own key, derived from `SECRET_KEY` with a
  label, and carries a `purpose` claim. An access token, an invitation and a recovery link never
  verify as one another.
- **Expiring.** `exp` is the link's lifetime after issue.
- **Single use.** The token carries a keyed fingerprint of the account's password hash at issue.
  Spending the link sets a new password, which changes the hash, so the same link never works twice;
  a password set any other way retires every outstanding link too. The fingerprint is an HMAC, so
  the token discloses nothing about the hash.

The caller decides whether a link is spent, against the account's current hash (`still_unspent`),
inside the transaction that sets the new password and with the account row locked.
"""

import hashlib
import hmac
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

import jwt
from jwt.exceptions import InvalidTokenError

from app.core.config import settings
from app.core.security import ALGORITHM


@dataclass(frozen=True)
class LinkClaims:
    subject: str
    password_fingerprint: str


@dataclass(frozen=True)
class PasswordBoundToken:
    """One kind of link: its `purpose` claim and the label its signing key is derived with."""

    purpose: str
    key_label: bytes

    def key(self) -> bytes:
        """The signing key for this kind of link, derived from `SECRET_KEY` and used nowhere else."""
        return hmac.new(
            settings.SECRET_KEY.encode(), self.key_label, hashlib.sha256
        ).digest()

    def fingerprint(self, hashed_password: str) -> str:
        """A keyed digest of a password hash, which binds a link to one password state."""
        return hmac.new(
            self.key(), hashed_password.encode(), hashlib.sha256
        ).hexdigest()

    def issue(
        self,
        *,
        subject: str,
        hashed_password: str,
        lifetime: timedelta,
        now: datetime | None = None,
    ) -> str:
        """Sign a link for one account in its current password state."""
        issued = now or datetime.now(UTC)
        claims = {
            "sub": subject,
            "purpose": self.purpose,
            "pwd": self.fingerprint(hashed_password),
            "iat": issued,
            "nbf": issued,
            "exp": issued + lifetime,
        }
        return jwt.encode(claims, self.key(), algorithm=ALGORITHM)

    def read(self, token: str) -> LinkClaims | None:
        """The claims of a valid, unexpired link of this kind, or `None` for anything else.

        One answer for tampered, expired, wrong-purpose and malformed tokens, so the response
        cannot be used to tell them apart.
        """
        try:
            claims = jwt.decode(
                token,
                self.key(),
                algorithms=[ALGORITHM],
                options={"require": ["sub", "purpose", "pwd", "exp", "nbf"]},
            )
        except InvalidTokenError:
            return None
        if claims["purpose"] != self.purpose:
            return None
        return LinkClaims(
            subject=str(claims["sub"]), password_fingerprint=str(claims["pwd"])
        )

    def still_unspent(self, claims: LinkClaims, hashed_password: str) -> bool:
        """Whether the account is still in the password state the link was issued for."""
        return hmac.compare_digest(
            claims.password_fingerprint, self.fingerprint(hashed_password)
        )
