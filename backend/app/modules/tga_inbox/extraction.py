"""Field extraction from a letter's text: deterministic rules, two independent passes, a confidence.

FEAT-09 stage 8: *"configured pattern set **plus** an independent pass; never a single method; per-field
confidence and page/region"*. For each field:

1. **Label pass.** A line that starts with one of the field's labels ("IHI:", "Date of birth -") and
   whose value validates (a real date, an IHI with a valid check digit, a token-shaped category).
2. **Pattern pass**, where the field has a self-checking shape: any 16-digit number starting
   `800360` with a valid Luhn digit is an IHI wherever it appears, labelled or not. Fields with no
   such shape (a name, a dosage form) have only the label pass.

| Outcome | Confidence | `method` |
| --- | --- | --- |
| Both passes find the same value | 0.980 | `LABEL_AND_PATTERN` |
| Label pass only (field has no pattern pass) | 0.850 | `LABEL` |
| Label pass only (pattern pass found nothing) | 0.850 | `LABEL` |
| Pattern pass only, exactly one candidate | 0.750 | `PATTERN` |
| The two passes disagree | 0.500 | `LABEL` (the labelled value, flagged) |
| Nothing validates, or the pattern pass is ambiguous | — | `NOT_FOUND` |

These numbers are **provisional**: the thresholds they are compared with are a clinical safety
parameter awaiting Clinical Safety Officer sign-off (FEAT-09 R13, open-questions F2), and the golden
set that would calibrate them does not exist yet (F1). Nothing is guessed: a value that does not
validate is `NOT_FOUND` (R8), and every value is only ever a proposal a person accepts or corrects.

The text is untrusted. It is matched with bounded regular expressions, never evaluated, never used to
build a query, and no value from it reaches a log line.
"""

import re
from collections.abc import Callable
from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from typing import Final

EXTRACTOR_VERSION: Final[str] = "rules-2026.11.1"

BOTH: Final[Decimal] = Decimal("0.980")
LABEL_ONLY: Final[Decimal] = Decimal("0.850")
PATTERN_ONLY: Final[Decimal] = Decimal("0.750")
CONFLICT: Final[Decimal] = Decimal("0.500")

# The fields an approval cannot be created without (`TgaApprovalCreate`), and the per-field floor
# below which the review screen flags a value (design: "per-mandatory-field floor 0.80").
MANDATORY_FIELDS: Final[tuple[str, ...]] = (
    "APPROVAL_REFERENCE",
    "TGA_CATEGORY",
    "DOSAGE_FORM",
    "VALID_FROM",
    "VALID_TO",
)
FIELD_FLOOR: Final[Decimal] = Decimal("0.800")
COMPOSITE_THRESHOLD: Final[Decimal] = Decimal("0.950")

_MAX_VALUE_LENGTH: Final[int] = 120


@dataclass(frozen=True)
class Candidate:
    field_name: str
    value: str | None
    confidence: Decimal | None
    method: str | None
    page_number: int | None


# -- validators: each returns the normalised value, or None ------------------------------------------


def _luhn_ok(digits: str) -> bool:
    total = 0
    for index, char in enumerate(reversed(digits)):
        number = int(char)
        if index % 2 == 1:
            number *= 2
            if number > 9:
                number -= 9
        total += number
    return total % 10 == 0


def _healthcare_identifier(prefix: str) -> Callable[[str], str | None]:
    def check(raw: str) -> str | None:
        digits = re.sub(r"[\s-]", "", raw)
        if re.fullmatch(r"\d{16}", digits) and digits.startswith(prefix):
            return digits if _luhn_ok(digits) else None
        return None

    return check


_ihi = _healthcare_identifier("800360")
_hpi_i = _healthcare_identifier("800361")


def _medicare(raw: str) -> str | None:
    """10 digits (an 11th, the IRN, is dropped); first digit 2-6; weighted check digit."""
    digits = re.sub(r"[\s/-]", "", raw)
    if not re.fullmatch(r"\d{10,11}", digits) or digits[0] not in "23456":
        return None
    weights = (1, 3, 7, 9, 1, 3, 7, 9)
    check = sum(int(d) * w for d, w in zip(digits[:8], weights, strict=True)) % 10
    return digits[:10] if check == int(digits[8]) else None


_MONTHS: Final[dict[str, int]] = {
    name: number
    for number, names in enumerate(
        (
            ("jan", "january"),
            ("feb", "february"),
            ("mar", "march"),
            ("apr", "april"),
            ("may",),
            ("jun", "june"),
            ("jul", "july"),
            ("aug", "august"),
            ("sep", "sept", "september"),
            ("oct", "october"),
            ("nov", "november"),
            ("dec", "december"),
        ),
        start=1,
    )
    for name in names
}


def parse_date(raw: str) -> date | None:
    """Australian day-first dates, ISO dates, and written dates ("1 March 2026")."""
    text = raw.strip().rstrip(".")
    numeric = re.fullmatch(r"(\d{1,2})[/.-](\d{1,2})[/.-](\d{4})", text)
    try:
        if numeric:
            day, month, year = (int(part) for part in numeric.groups())
            return date(year, month, day)
        iso = re.fullmatch(r"(\d{4})-(\d{2})-(\d{2})", text)
        if iso:
            return date.fromisoformat(text)
        written = re.fullmatch(
            r"(\d{1,2})(?:st|nd|rd|th)?\s+([A-Za-z]+)\s+(\d{4})", text
        )
        if written and written.group(2).lower() in _MONTHS:
            return date(
                int(written.group(3)),
                _MONTHS[written.group(2).lower()],
                int(written.group(1)),
            )
    except ValueError:
        return None
    return None


def _date(raw: str) -> str | None:
    parsed = parse_date(raw)
    return parsed.isoformat() if parsed else None


def _token(raw: str) -> str | None:
    """A controlled token in the shape `tga_approvals` requires: `Oral oil` -> `ORAL_OIL`."""
    token = re.sub(r"[^A-Z0-9]+", "_", raw.strip().upper()).strip("_")
    return token if re.fullmatch(r"[A-Z0-9][A-Z0-9_]{0,31}", token) else None


def _category(raw: str) -> str | None:
    value = raw.strip()
    if re.fullmatch(r"\d", value):
        value = f"Category {value}"
    return _token(value)


def _reference(raw: str) -> str | None:
    value = raw.strip()
    return value if re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9/_. -]{0,63}", value) else None


def _person_name(raw: str) -> str | None:
    value = re.sub(r"\s+", " ", raw.strip())
    return value if re.fullmatch(r"[A-Za-z][A-Za-z' .-]{1,99}", value) else None


@dataclass(frozen=True)
class _Rule:
    labels: tuple[str, ...]
    validate: Callable[[str], str | None]
    # A regular expression whose matches are candidates anywhere in the text, or None.
    pattern: re.Pattern[str] | None = None


_SIXTEEN_DIGITS = r"\b\d{4}[\s-]?\d{4}[\s-]?\d{4}[\s-]?\d{4}\b"

RULES: Final[dict[str, _Rule]] = {
    "APPROVAL_REFERENCE": _Rule(
        (
            "approval number",
            "approval no",
            "approval reference",
            "approval id",
            "tga reference",
            "reference number",
            "our reference",
        ),
        _reference,
    ),
    "PATIENT_NAME": _Rule(("patient name", "name of patient", "patient"), _person_name),
    "PATIENT_DOB": _Rule(("date of birth", "dob", "d.o.b"), _date),
    "PATIENT_IHI": _Rule(
        ("individual healthcare identifier", "ihi number", "ihi"),
        _ihi,
        re.compile(_SIXTEEN_DIGITS),
    ),
    "PATIENT_MEDICARE": _Rule(
        ("medicare number", "medicare no", "medicare card number", "medicare"),
        _medicare,
        re.compile(r"\b\d{4}\s?\d{5}\s?\d(?:[\s/-]?\d)?\b"),
    ),
    "TGA_CATEGORY": _Rule(("product category", "category"), _category),
    "DOSAGE_FORM": _Rule(("dosage form", "dose form", "formulation"), _token),
    "VALID_FROM": _Rule(
        (
            "valid from",
            "start date",
            "date of approval",
            "approval date",
            "approved on",
        ),
        _date,
    ),
    "VALID_TO": _Rule(
        ("valid to", "valid until", "expiry date", "expiry", "expires", "end date"),
        _date,
    ),
    "PRESCRIBER_NAME": _Rule(
        (
            "prescriber name",
            "prescriber",
            "authorised prescriber",
            "medical practitioner",
        ),
        _person_name,
    ),
    "PRESCRIBER_HPI_I": _Rule(
        ("prescriber hpi-i", "hpi-i number", "hpi-i", "hpii"),
        _hpi_i,
        re.compile(_SIXTEEN_DIGITS),
    ),
}


def _label_line(rule: _Rule) -> re.Pattern[str]:
    labels = "|".join(
        re.escape(label) for label in sorted(rule.labels, key=len, reverse=True)
    )
    return re.compile(
        rf"^\s*(?:{labels})\s*(?:[:#-]|\s)\s*(.{{1,{_MAX_VALUE_LENGTH}}})$", re.I
    )


_LABEL_LINES: Final[dict[str, re.Pattern[str]]] = {
    name: _label_line(rule) for name, rule in RULES.items()
}


def _label_pass(field_name: str, pages: list[str]) -> tuple[str, int] | None:
    rule = RULES[field_name]
    for page_number, page in enumerate(pages, start=1):
        for line in page.splitlines():
            match = _LABEL_LINES[field_name].match(line)
            if match:
                value = rule.validate(match.group(1))
                if value is not None:
                    return value, page_number
    return None


def _pattern_pass(field_name: str, pages: list[str]) -> tuple[str, int] | None | bool:
    """`(value, page)` for exactly one distinct valid match, `None` for none, `False` if ambiguous."""
    rule = RULES[field_name]
    if rule.pattern is None:
        return None
    found: dict[str, int] = {}
    for page_number, page in enumerate(pages, start=1):
        for match in rule.pattern.finditer(page):
            value = rule.validate(match.group(0))
            if value is not None:
                found.setdefault(value, page_number)
    if not found:
        return None
    if len(found) > 1:
        return False
    value, page_number = next(iter(found.items()))
    return value, page_number


def extract(pages: list[str]) -> list[Candidate]:
    """One candidate per field, `NOT_FOUND` included, in `RULES` order."""
    candidates: list[Candidate] = []
    for field_name in RULES:
        labelled = _label_pass(field_name, pages)
        patterned = _pattern_pass(field_name, pages)
        if labelled is not None:
            value, page = labelled
            if isinstance(patterned, tuple) and patterned[0] == value:
                candidates.append(
                    Candidate(field_name, value, BOTH, "LABEL_AND_PATTERN", page)
                )
            elif isinstance(patterned, tuple) or patterned is False:
                # The text holds another valid value the label does not account for.
                candidates.append(Candidate(field_name, value, CONFLICT, "LABEL", page))
            else:
                candidates.append(
                    Candidate(field_name, value, LABEL_ONLY, "LABEL", page)
                )
        elif isinstance(patterned, tuple):
            value, page = patterned
            candidates.append(
                Candidate(field_name, value, PATTERN_ONLY, "PATTERN", page)
            )
        else:
            candidates.append(Candidate(field_name, None, None, None, None))
    return candidates


def composite_score(confidences: dict[str, Decimal | None]) -> Decimal:
    """The mean confidence of the mandatory fields, a missing field counting zero. Display only:
    automatic creation is not enabled (design, "Confidence threshold"), so the score orders and
    flags; it never decides."""
    total = sum(
        (confidences.get(name) or Decimal(0) for name in MANDATORY_FIELDS), Decimal(0)
    )
    return (total / len(MANDATORY_FIELDS)).quantize(Decimal("0.001"))
