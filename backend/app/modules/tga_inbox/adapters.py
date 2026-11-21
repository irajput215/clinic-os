"""The inbox's vendor seams, and the stand-ins used until each vendor is approved (D-011 §1).

Each third-party job (object storage, malware scanning, OCR) sits behind a small `Protocol`. What
this module provides today are **stand-ins**: they do the job well enough to run the pipeline end to
end in CI, locally and in staging, and they send nothing to any third party. A real adapter replaces
a stand-in only after its vendor has a data-flow record and a residency sign-off (D-011 open items).

| Seam | Stand-in | What it really does |
| --- | --- | --- |
| `ObjectStore` | `MemoryObjectStore`, `DirectoryObjectStore` | Keeps bytes in process, or in a local directory |
| `MalwareScanner` | `SignatureScanner` | Flags the EICAR test file and nothing else. **Not a malware scanner** |
| `OcrEngine` | none | No OCR: a scanned PDF goes to a person (`NO_TEXT`) |

The scanner stand-in is the one to be most careful about: it proves the pipeline's *handling* of an
infected file (quarantine, never stored, never parsed) without detecting real malware. That is why
ingestion is off unless `TGA_INBOX_INGEST_TOKEN` is set, and why D-011 keeps production enablement
behind the scanner decision.
"""

import hashlib
import os
import threading
import uuid
from functools import cache
from pathlib import Path
from typing import Final, Literal, Protocol

from app.core.config import settings

ScanVerdict = Literal["CLEAN", "INFECTED", "ERROR"]

# The standard antivirus test string (eicar.org). Harmless; every real scanner flags it.
EICAR_SIGNATURE: Final[bytes] = (
    b"X5O!P%@AP[4\\PZX54(P^)7CC)7}$EICAR-STANDARD-ANTIVIRUS-TEST-FILE!$H+H*"
)


class ObjectStore(Protocol):
    """Private storage for originals. Keys are server-generated and never contain a filename."""

    def put(self, key: str, data: bytes) -> None: ...

    def get(self, key: str) -> bytes | None: ...


class MalwareScanner(Protocol):
    def scan(self, data: bytes) -> ScanVerdict: ...


class OcrEngine(Protocol):
    """Text for each page of a PDF that has no text layer. No implementation exists yet."""

    def pages(self, data: bytes) -> list[str] | None: ...


def object_key(*, tenant_id: uuid.UUID, sha256: bytes) -> str:
    """Tenant-prefixed and content-addressed: the same file stored twice is one object (R18)."""
    return f"tga-inbox/{tenant_id}/{sha256.hex()}"


class MemoryObjectStore:
    """In-process storage. Nothing survives a restart; for tests and local runs only."""

    def __init__(self) -> None:
        self._objects: dict[str, bytes] = {}
        self._lock = threading.Lock()

    def put(self, key: str, data: bytes) -> None:
        with self._lock:
            self._objects[key] = data

    def get(self, key: str) -> bytes | None:
        with self._lock:
            return self._objects.get(key)


class DirectoryObjectStore:
    """A local directory. The key is hashed into the file name, so no key can escape the root."""

    def __init__(self, root: str) -> None:
        self._root = Path(root)
        self._root.mkdir(parents=True, exist_ok=True, mode=0o700)

    def _path(self, key: str) -> Path:
        return self._root / hashlib.sha256(key.encode("utf-8")).hexdigest()

    def put(self, key: str, data: bytes) -> None:
        path = self._path(key)
        temporary = path.with_suffix(".partial")
        temporary.write_bytes(data)
        os.chmod(temporary, 0o600)
        temporary.replace(path)

    def get(self, key: str) -> bytes | None:
        path = self._path(key)
        return path.read_bytes() if path.exists() else None


class SignatureScanner:
    """Stand-in scanner: `INFECTED` for the EICAR test file, `CLEAN` for everything else."""

    def scan(self, data: bytes) -> ScanVerdict:
        return "INFECTED" if EICAR_SIGNATURE in data else "CLEAN"


@cache
def configured_store() -> ObjectStore:
    if settings.TGA_INBOX_STORAGE_DIR:
        return DirectoryObjectStore(settings.TGA_INBOX_STORAGE_DIR)
    return MemoryObjectStore()


@cache
def configured_scanner() -> MalwareScanner:
    return SignatureScanner()


def configured_ocr() -> OcrEngine | None:
    """No OCR vendor is approved (D-011, open-questions F3), so there is none."""
    return None
