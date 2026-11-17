"""The stand-in text-layer reader and the field rules (FEAT-09 R7, R8; D-011 §1)."""

import zlib
from decimal import Decimal

from app.modules.tga_inbox import adapters, extraction, pdf_text
from tests.tga_inbox.conftest import (
    SYNTHETIC_HPI_I,
    SYNTHETIC_IHI,
    SYNTHETIC_MEDICARE,
    approval_letter,
    luhn_complete,
    make_pdf,
)


def _fields(pages: list[str]) -> dict[str, extraction.Candidate]:
    return {c.field_name: c for c in extraction.extract(pages)}


def test_reads_compressed_and_uncompressed_text_layers_page_by_page() -> None:
    for compress in (True, False):
        text = pdf_text.read(
            make_pdf([["Hello (world)", "Line two"], ["Page two"]], compress=compress)
        )
        assert text.state == "NO_TEXT"  # under the minimum characters for a real letter
        assert text.pages == ["Hello (world)\nLine two", "Page two"]
    letter = pdf_text.read(make_pdf(approval_letter()))
    assert letter.state == "EXTRACTED"
    assert len(letter.pages) == 2
    assert "Approval number: SAS-2026-004512" in letter.pages[0]


def test_encrypted_and_malformed_files_are_never_cracked_or_guessed() -> None:
    assert (
        pdf_text.read(
            make_pdf(
                approval_letter(), extra=b"9 0 obj\n<< /Encrypt 10 0 R >>\nendobj\n"
            )
        ).state
        == "ENCRYPTED"
    )
    assert pdf_text.read(b"not a pdf").state == "FAILED"
    assert pdf_text.read(b"%PDF-1.4\n%%EOF").state == "FAILED"


def test_a_decompression_bomb_is_abandoned() -> None:
    bomb = zlib.compress(b"0" * (pdf_text.MAX_STREAM_BYTES + 1024))
    data = (
        b"%PDF-1.4\n1 0 obj\n<< /Type /Page /Contents 2 0 R >>\nendobj\n"
        + (b"2 0 obj\n<< /Length %d /Filter /FlateDecode >>\nstream\n" % len(bomb))
        + bomb
        + b"\nendstream\nendobj\n%%EOF"
    )
    result = pdf_text.read(data)
    assert result.state in ("NO_TEXT", "FAILED")
    assert all(page == "" for page in result.pages)


def test_every_field_of_a_letter_is_extracted_with_page_and_confidence() -> None:
    pages = pdf_text.read(make_pdf(approval_letter())).pages
    fields = _fields(pages)
    assert fields["APPROVAL_REFERENCE"].value == "SAS-2026-004512"
    assert fields["PATIENT_NAME"].value == "Ada Synthetic"
    assert fields["PATIENT_DOB"].value == "1990-01-01"
    assert fields["PATIENT_IHI"].value == SYNTHETIC_IHI
    assert fields["PATIENT_MEDICARE"].value == SYNTHETIC_MEDICARE[:10]
    assert fields["TGA_CATEGORY"].value == "CATEGORY_3"
    assert fields["DOSAGE_FORM"].value == "ORAL_OIL"
    assert fields["VALID_FROM"].value == "2026-03-01"
    assert fields["VALID_TO"].value == "2027-02-28"
    assert fields["PRESCRIBER_NAME"].value == "Dr Grace Example"
    assert fields["PRESCRIBER_HPI_I"].value == SYNTHETIC_HPI_I
    # Two independent methods agree only where the field has a self-checking shape.
    assert fields["PATIENT_IHI"].method == "LABEL_AND_PATTERN"
    assert fields["PATIENT_IHI"].confidence == extraction.BOTH
    assert fields["PATIENT_NAME"].method == "LABEL"
    assert fields["PATIENT_NAME"].confidence == extraction.LABEL_ONLY
    assert fields["PATIENT_IHI"].page_number == 1
    assert fields["DOSAGE_FORM"].page_number == 2


def test_a_value_that_fails_its_check_is_not_found_never_guessed() -> None:
    bad_ihi = SYNTHETIC_IHI[:-1] + str((int(SYNTHETIC_IHI[-1]) + 1) % 10)
    fields = _fields(
        [
            "\n".join(
                ["IHI: " + bad_ihi, "Date of birth: 31/02/1990", "Medicare: 1234567890"]
            )
        ]
    )
    for name in (
        "PATIENT_IHI",
        "PATIENT_DOB",
        "PATIENT_MEDICARE",
        "APPROVAL_REFERENCE",
    ):
        assert fields[name].value is None
        assert fields[name].confidence is None
        assert fields[name].method is None


def test_an_unlabelled_identifier_is_found_by_pattern_and_two_are_ambiguous() -> None:
    assert _fields([f"Re: {SYNTHETIC_IHI}"])["PATIENT_IHI"].method == "PATTERN"
    other = luhn_complete("800360" + "111111111")
    assert _fields([f"{SYNTHETIC_IHI} and {other}"])["PATIENT_IHI"].value is None


def test_a_label_the_text_contradicts_is_flagged_low() -> None:
    other = luhn_complete("800360" + "111111111")
    field = _fields([f"IHI: {SYNTHETIC_IHI}\nSee also {other}"])["PATIENT_IHI"]
    assert field.value == SYNTHETIC_IHI
    assert field.confidence == extraction.CONFLICT
    assert field.confidence < extraction.FIELD_FLOOR


def test_composite_score_counts_a_missing_mandatory_field_as_zero() -> None:
    full = {name: Decimal("1") for name in extraction.MANDATORY_FIELDS}
    assert extraction.composite_score(full) == Decimal("1.000")
    full.pop("VALID_TO")
    assert extraction.composite_score(full) == Decimal("0.800")


def test_dates_are_read_day_first() -> None:
    assert str(extraction.parse_date("03/04/2026")) == "2026-04-03"
    assert str(extraction.parse_date("3rd April 2026")) == "2026-04-03"
    assert extraction.parse_date("2026-13-01") is None


def test_the_stand_in_scanner_flags_the_eicar_test_file_only() -> None:
    scanner = adapters.SignatureScanner()
    assert scanner.scan(b"%PDF-1.4 " + adapters.EICAR_SIGNATURE) == "INFECTED"
    assert scanner.scan(make_pdf(approval_letter())) == "CLEAN"


def test_the_directory_store_keeps_keys_inside_its_root(tmp_path) -> None:  # type: ignore[no-untyped-def]
    store = adapters.DirectoryObjectStore(str(tmp_path))
    store.put("../../etc/passwd", b"data")
    assert store.get("../../etc/passwd") == b"data"
    assert [p.parent for p in tmp_path.iterdir()] == [tmp_path]
