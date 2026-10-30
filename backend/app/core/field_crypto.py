"""Field-level encryption for identifiers, and the keyed blind index that finds them.

`docs/features/05-patients/01-requirements.md` R8: Medicare numbers and IHIs are encrypted at the
application boundary, and exact-match search uses a keyed blind index, so the database never holds a
searchable plaintext identifier. The same helper serves practitioner identifiers (docs3 feature 02).

- **Encryption** is AES-256-GCM. A stored value is `version (1 byte) || nonce (12) || ciphertext+tag`.
  The version names the key, so a later key can be introduced without re-reading old rows first.
  The associated data binds a value to its tenant and its column (`kind`): a ciphertext copied into
  another tenant's row, or into another column, fails to decrypt instead of reading as valid.
- **The blind index** is HMAC-SHA256 over the tenant, the kind and the normalised value. Scoping it by
  tenant means two clinics' rows for the same person cannot be linked by comparing indexes.
- **Keys** come from `FIELD_ENCRYPTION_KEY` (32 bytes, base64url) or, when unset, are derived from
  `SECRET_KEY`. Two separate keys are derived with HKDF, one per purpose, so the index key can never
  decrypt anything.

Nothing here logs, and no error carries a value (INV-5): a value that fails to decrypt is reported as
`None`, and the caller shows it as unavailable.
"""

import base64
import hashlib
import hmac
import logging
import os
import uuid
from functools import cache
from typing import Final

from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.kdf.hkdf import HKDF

from app.core.config import settings

logger = logging.getLogger(__name__)

KEY_VERSION: Final = 1
_NONCE_BYTES: Final = 12
_KEY_BYTES: Final = 32


@cache
def _master_key() -> bytes:
    configured = settings.FIELD_ENCRYPTION_KEY
    if configured is not None:
        raw = configured.get_secret_value()
        key = base64.urlsafe_b64decode(raw + "=" * (-len(raw) % 4))
        if len(key) != _KEY_BYTES:
            raise ValueError("FIELD_ENCRYPTION_KEY must be 32 bytes, base64url-encoded")
        return key
    return hashlib.sha256(
        b"clinicos/field-crypto/v1|" + settings.SECRET_KEY.encode()
    ).digest()


@cache
def _derived(purpose: bytes) -> bytes:
    return HKDF(
        algorithm=hashes.SHA256(),
        length=_KEY_BYTES,
        salt=None,
        info=b"clinicos/" + purpose + b"/v1",
    ).derive(_master_key())


def _associated(tenant_id: uuid.UUID, kind: str) -> bytes:
    return tenant_id.bytes + b"|" + kind.encode()


def encrypt(value: str, *, tenant_id: uuid.UUID, kind: str) -> bytes:
    """`value` encrypted for one tenant's `kind` column."""
    nonce = os.urandom(_NONCE_BYTES)
    sealed = AESGCM(_derived(b"encrypt")).encrypt(
        nonce, value.encode(), _associated(tenant_id, kind)
    )
    return bytes([KEY_VERSION]) + nonce + sealed


def decrypt(stored: bytes | None, *, tenant_id: uuid.UUID, kind: str) -> str | None:
    """The plaintext, or `None` when nothing is stored or it cannot be read with the current key."""
    if not stored:
        return None
    if stored[0] != KEY_VERSION:
        logger.warning("Stored identifier uses an unknown key version")
        return None
    nonce, sealed = stored[1 : 1 + _NONCE_BYTES], stored[1 + _NONCE_BYTES :]
    try:
        plain = AESGCM(_derived(b"encrypt")).decrypt(
            nonce, sealed, _associated(tenant_id, kind)
        )
    except InvalidTag:
        logger.warning("Stored identifier could not be decrypted with the current key")
        return None
    return plain.decode()


def blind_index(value: str, *, tenant_id: uuid.UUID, kind: str) -> bytes:
    """The keyed exact-match index of a normalised `value` for one tenant's `kind` column."""
    return hmac.new(
        _derived(b"blind-index"),
        _associated(tenant_id, kind) + b"|" + value.encode(),
        hashlib.sha256,
    ).digest()


def mask(value: str | None) -> str | None:
    """`•••• ` and the last three characters (`05-patients` R9); never more of the value."""
    if not value:
        return None
    return "•••• " + value[-3:]
