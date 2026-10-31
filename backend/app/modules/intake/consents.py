"""The consent documents a patient signs on the public application (manual §5.1 step 4, §12.3).

Platform defaults, versioned here. A patient's consent records the `version` and the SHA-256 of the
exact text shown, so "which words did this patient agree to, and when" always has an answer. A clinic's
own wording (published from Settings) is a later step; until then every clinic offers these.

No product or brand name appears in any of them (manual §5: a legal line on patient-facing pages).
"""

import hashlib
from dataclasses import dataclass
from typing import Final


@dataclass(frozen=True)
class ConsentDocument:
    kind: str
    version: str
    title: str
    body: str

    @property
    def sha256(self) -> str:
        return hashlib.sha256(self.body.encode()).hexdigest()


CONSENT_DOCUMENTS: Final[tuple[ConsentDocument, ...]] = (
    ConsentDocument(
        kind="PRIVACY",
        version="2026-10",
        title="Privacy collection notice",
        body=(
            "The clinic collects your personal and health information to assess whether its care is "
            "right for you, to provide that care, and to meet its legal obligations. Your information "
            "is stored in Australia, is seen only by the clinic's staff who need it, and is never "
            "sold. You can ask to see or correct it at any time. If you do not provide it, the clinic "
            "may not be able to treat you."
        ),
    ),
    ConsentDocument(
        kind="TELEHEALTH",
        version="2026-10",
        title="Telehealth consent",
        body=(
            "Your consultation may happen by video or phone. A telehealth consultation has limits: the "
            "doctor cannot examine you in person and may ask you to see a doctor face to face. Join "
            "from a private place. The clinic does not record consultations."
        ),
    ),
    ConsentDocument(
        kind="TREATMENT",
        version="2026-10",
        title="Treatment consent",
        body=(
            "Any treatment is decided by the doctor after your consultation, and may be declined. "
            "Some prescribed medicines are unapproved therapeutic goods supplied under a TGA pathway; "
            "the doctor will explain what that means for you. Some medicines can impair driving and "
            "operating machinery: do not drive while impaired, and ask the doctor about the law in "
            "your state. Tell the clinic about any side effects, other medicines or changes in your "
            "health."
        ),
    ),
)

CURRENT_CONSENTS: Final[dict[str, ConsentDocument]] = {
    document.kind: document for document in CONSENT_DOCUMENTS
}
