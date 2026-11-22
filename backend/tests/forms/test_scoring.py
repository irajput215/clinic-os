"""The published scoring rules and bands of PHQ-9, GAD-7 and K10, and the provisional flag rule."""

import pytest

from app.modules.forms.instruments import (
    GAD7,
    INSTRUMENTS,
    K10,
    PHQ9,
    InvalidAnswers,
    score,
)


@pytest.mark.parametrize(
    ("instrument", "answers", "total", "band"),
    [
        (PHQ9, (0,) * 9, 0, "MINIMAL"),
        (PHQ9, (1, 1, 1, 1, 1, 0, 0, 0, 0), 5, "MILD"),
        (PHQ9, (2, 2, 2, 2, 2, 0, 0, 0, 0), 10, "MODERATE"),
        (PHQ9, (3, 3, 3, 3, 3, 0, 0, 0, 0), 15, "MODERATELY_SEVERE"),
        (PHQ9, (3, 3, 3, 3, 3, 3, 2, 0, 0), 20, "SEVERE"),
        (PHQ9, (3,) * 9, 27, "SEVERE"),
        (GAD7, (0,) * 7, 0, "MINIMAL"),
        (GAD7, (1, 1, 1, 1, 1, 0, 0), 5, "MILD"),
        (GAD7, (2, 2, 2, 2, 2, 0, 0), 10, "MODERATE"),
        (GAD7, (3, 3, 3, 3, 3, 0, 0), 15, "SEVERE"),
        (GAD7, (3,) * 7, 21, "SEVERE"),
        (K10, (1,) * 10, 10, "LOW"),
        (K10, (2, 2, 2, 2, 2, 2, 1, 1, 1, 1), 16, "MODERATE"),
        (K10, (3, 3, 2, 2, 2, 2, 2, 2, 2, 2), 22, "HIGH"),
        (K10, (3,) * 10, 30, "VERY_HIGH"),
        (K10, (5,) * 10, 50, "VERY_HIGH"),
    ],
)
def test_published_totals_and_band_boundaries(instrument, answers, total, band) -> None:  # type: ignore[no-untyped-def]
    scored = score(instrument, answers, None)
    assert (scored.total, scored.band.code) == (total, band)


def test_bands_cover_every_possible_score_without_gaps() -> None:
    for instrument in INSTRUMENTS.values():
        assert instrument.bands[0].low == instrument.min_score
        assert instrument.bands[-1].high == instrument.max_score
        for lower, upper in zip(instrument.bands, instrument.bands[1:], strict=False):
            assert lower.high + 1 == upper.low


def test_phq9_item_9_above_zero_raises_the_flag_whatever_the_total() -> None:
    assert [f.code for f in score(PHQ9, (0,) * 8 + (1,), None).flags] == [
        "PHQ9_ITEM9_POSITIVE"
    ]
    assert score(PHQ9, (3,) * 8 + (0,), None).flags == ()
    assert score(GAD7, (3,) * 7, None).flags == ()
    assert score(K10, (5,) * 10, None).flags == ()


@pytest.mark.parametrize(
    ("instrument", "answers", "difficulty"),
    [
        (PHQ9, (0,) * 8, None),
        (PHQ9, (0,) * 8 + (4,), None),
        (K10, (0,) * 10, None),
        (K10, (1,) * 10, 0),
        (GAD7, (0,) * 7, 4),
    ],
)
def test_answers_that_do_not_fit_are_refused(instrument, answers, difficulty) -> None:  # type: ignore[no-untyped-def]
    with pytest.raises(InvalidAnswers):
        score(instrument, answers, difficulty)


def test_item_counts_match_the_published_instruments() -> None:
    assert (len(PHQ9.items), len(GAD7.items), len(K10.items)) == (9, 7, 10)
    assert PHQ9.items[8].startswith("Thoughts that you would be better off dead")
