"""The three validated screening instruments (docs3 Phase 6, feature 05; decision D18).

PHQ-9 (depression), GAD-7 (anxiety) and K10 (psychological distress), with their published item text,
response options, scoring and severity bands. They are platform definitions, versioned here like the
consent documents (`app/modules/consents/documents.py`): a response records the instrument code and the
version it was answered on, so a later wording change never re-reads old answers.

## Provenance and the open items

* **Text.** Reproduced as published: PHQ-9 and GAD-7 (Spitzer, Kroenke, Williams and colleagues; the
  developers' stated terms allow free use without permission), K10 (Kessler and colleagues; widely
  used in Australian primary care). Licensing for this product is **REQUIRES LEGAL/REGULATORY
  VALIDATION** (decision D19, Compliance Lead) before patient-facing use beyond staff entry.
* **Bands.** The published cut-offs. A band is a label for a clinician, never a diagnosis.
  K10 uses the bands common in Australian practice (10-15, 16-21, 22-29, 30-50); confirm with the
  Clinical Safety Officer.
* **Safety flags.** `FLAG_RULES` is PROVISIONAL (decision D20, Clinical Safety Officer). It holds the
  one rule D20 proposes: any answer above 0 on PHQ-9 item 9. Who is notified, how fast, and what
  happens out of hours are not decided, so a flag today is shown on the patient record and
  acknowledged there, and nothing else is sent.
* **K10 skip pattern.** The original K10 lets an interviewer skip items 3 and 6 after "none of the
  time" on items 2 and 5. Every item is required here, which scores the same.
"""

from collections.abc import Callable
from dataclasses import dataclass
from typing import Final


@dataclass(frozen=True)
class Option:
    label: str
    value: int


@dataclass(frozen=True)
class Band:
    code: str
    label: str
    low: int
    high: int


@dataclass(frozen=True)
class Instrument:
    code: str
    version: str
    title: str
    stem: str
    items: tuple[str, ...]
    options: tuple[Option, ...]
    bands: tuple[Band, ...]
    # The functional-difficulty question PHQ-9 and GAD-7 end with: asked, recorded, never scored.
    difficulty_question: str | None = None
    difficulty_options: tuple[str, ...] = ()

    @property
    def min_score(self) -> int:
        return len(self.items) * min(o.value for o in self.options)

    @property
    def max_score(self) -> int:
        return len(self.items) * max(o.value for o in self.options)

    def allowed_values(self) -> frozenset[int]:
        return frozenset(o.value for o in self.options)


_FREQUENCY_2_WEEKS: Final = (
    Option("Not at all", 0),
    Option("Several days", 1),
    Option("More than half the days", 2),
    Option("Nearly every day", 3),
)
_DIFFICULTY_QUESTION: Final = (
    "If you checked off any problems, how difficult have these problems made it for you to do your "
    "work, take care of things at home, or get along with other people?"
)
_DIFFICULTY_OPTIONS: Final = (
    "Not difficult at all",
    "Somewhat difficult",
    "Very difficult",
    "Extremely difficult",
)

PHQ9: Final = Instrument(
    code="PHQ9",
    version="1",
    title="Patient Health Questionnaire (PHQ-9)",
    stem="Over the last 2 weeks, how often have you been bothered by any of the following problems?",
    items=(
        "Little interest or pleasure in doing things",
        "Feeling down, depressed, or hopeless",
        "Trouble falling or staying asleep, or sleeping too much",
        "Feeling tired or having little energy",
        "Poor appetite or overeating",
        "Feeling bad about yourself — or that you are a failure or have let yourself or your family "
        "down",
        "Trouble concentrating on things, such as reading the newspaper or watching television",
        "Moving or speaking so slowly that other people could have noticed? Or the opposite — being "
        "so fidgety or restless that you have been moving around a lot more than usual",
        "Thoughts that you would be better off dead or of hurting yourself in some way",
    ),
    options=_FREQUENCY_2_WEEKS,
    bands=(
        Band("MINIMAL", "Minimal", 0, 4),
        Band("MILD", "Mild", 5, 9),
        Band("MODERATE", "Moderate", 10, 14),
        Band("MODERATELY_SEVERE", "Moderately severe", 15, 19),
        Band("SEVERE", "Severe", 20, 27),
    ),
    difficulty_question=_DIFFICULTY_QUESTION,
    difficulty_options=_DIFFICULTY_OPTIONS,
)

GAD7: Final = Instrument(
    code="GAD7",
    version="1",
    title="Generalised Anxiety Disorder scale (GAD-7)",
    stem="Over the last 2 weeks, how often have you been bothered by the following problems?",
    items=(
        "Feeling nervous, anxious or on edge",
        "Not being able to stop or control worrying",
        "Worrying too much about different things",
        "Trouble relaxing",
        "Being so restless that it is hard to sit still",
        "Becoming easily annoyed or irritable",
        "Feeling afraid as if something awful might happen",
    ),
    options=_FREQUENCY_2_WEEKS,
    bands=(
        Band("MINIMAL", "Minimal", 0, 4),
        Band("MILD", "Mild", 5, 9),
        Band("MODERATE", "Moderate", 10, 14),
        Band("SEVERE", "Severe", 15, 21),
    ),
    difficulty_question=_DIFFICULTY_QUESTION,
    difficulty_options=_DIFFICULTY_OPTIONS,
)

K10: Final = Instrument(
    code="K10",
    version="1",
    title="Kessler Psychological Distress Scale (K10)",
    stem="During the last 30 days, about how often did you feel…",
    items=(
        "…tired out for no good reason?",
        "…nervous?",
        "…so nervous that nothing could calm you down?",
        "…hopeless?",
        "…restless or fidgety?",
        "…so restless you could not sit still?",
        "…depressed?",
        "…that everything was an effort?",
        "…so sad that nothing could cheer you up?",
        "…worthless?",
    ),
    options=(
        Option("None of the time", 1),
        Option("A little of the time", 2),
        Option("Some of the time", 3),
        Option("Most of the time", 4),
        Option("All of the time", 5),
    ),
    bands=(
        Band("LOW", "Low", 10, 15),
        Band("MODERATE", "Moderate", 16, 21),
        Band("HIGH", "High", 22, 29),
        Band("VERY_HIGH", "Very high", 30, 50),
    ),
)

INSTRUMENTS: Final[dict[str, Instrument]] = {i.code: i for i in (PHQ9, GAD7, K10)}


@dataclass(frozen=True)
class FlagRule:
    code: str
    instrument: str
    description: str
    test: Callable[[tuple[int, ...]], bool]


# PROVISIONAL (D20): the one rule proposed. Item numbers are 1-based in prose, 0-based in code.
FLAG_RULES: Final[tuple[FlagRule, ...]] = (
    FlagRule(
        code="PHQ9_ITEM9_POSITIVE",
        instrument="PHQ9",
        description="Thoughts of being better off dead or of self-harm reported (PHQ-9 item 9 above 0).",
        test=lambda answers: answers[8] > 0,
    ),
)

# PROVISIONAL (D20): what a clinician records when acknowledging a flag.
ACKNOWLEDGE_ACTIONS: Final[dict[str, str]] = {
    "SAFETY_ASSESSED_NO_IMMEDIATE_RISK": "Assessed: no immediate risk",
    "SAFETY_PLAN_AGREED": "Safety plan agreed with the patient",
    "URGENT_REFERRAL_MADE": "Urgent referral made",
    "EMERGENCY_SERVICES_CONTACTED": "Emergency services contacted",
}


class InvalidAnswers(ValueError):
    """The answers do not fit the instrument. The message names the rule, never an answer."""


@dataclass(frozen=True)
class Scored:
    total: int
    band: Band
    flags: tuple[FlagRule, ...]


def score(
    instrument: Instrument, answers: tuple[int, ...], difficulty: int | None
) -> Scored:
    """Score by the published rule (the sum of item values) and apply the flag rules."""
    if len(answers) != len(instrument.items):
        raise InvalidAnswers(f"{instrument.code} has {len(instrument.items)} items")
    allowed = instrument.allowed_values()
    if any(answer not in allowed for answer in answers):
        raise InvalidAnswers(
            f"{instrument.code} answers must be one of {sorted(allowed)}"
        )
    if difficulty is not None and not (
        instrument.difficulty_options
        and 0 <= difficulty < len(instrument.difficulty_options)
    ):
        raise InvalidAnswers(f"{instrument.code} has no such difficulty answer")
    total = sum(answers)
    band = next(b for b in instrument.bands if b.low <= total <= b.high)
    flags = tuple(
        rule
        for rule in FLAG_RULES
        if rule.instrument == instrument.code and rule.test(answers)
    )
    return Scored(total=total, band=band, flags=flags)
