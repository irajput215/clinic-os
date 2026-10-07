"""Static evidence for the no-bypass rule (FEAT-10 S15, S16, S18; T-10.10).

The checks read the source, so a new route, worker, CLI or test that reaches the gate's lookup or the
transport another way fails the build rather than a review.
"""

import re
from pathlib import Path

APP = Path(__file__).parents[2] / "app"
TESTS = Path(__file__).parents[1]
GATE = APP / "modules" / "prescriptions" / "gate.py"


def _python_files(*roots: Path) -> list[Path]:
    return [path for root in roots for path in root.rglob("*.py")]


def test_the_gate_takes_no_bypass_parameter() -> None:
    """S16: no `skip`, `force` or `override` anywhere in the gate module, code or prose."""
    source = GATE.read_text().lower()
    for word in ("skip", "force", "override", "bypass_"):
        assert word not in source, word


def test_only_the_gate_asks_for_a_locked_match() -> None:
    """S18: the deciding lookup (`evaluate_match(..., lock=...)`) has exactly one caller."""
    users = sorted(
        path.as_posix()
        for path in _python_files(APP, TESTS)
        if "evaluate_match(" in path.read_text() and path != Path(__file__)
    )
    # The definition (and the TGA module's own unlocked match route), and the gate.
    assert users == sorted(
        [
            (APP / "modules" / "tga_approvals" / "service.py").as_posix(),
            GATE.as_posix(),
        ]
    )


def test_every_state_writer_in_the_module_reaches_the_gate() -> None:
    """The three code paths that move a prescription towards a pharmacy all call `gate.decide`."""
    service = (APP / "modules" / "prescriptions" / "service.py").read_text()
    outbox = (APP / "modules" / "prescriptions" / "outbox.py").read_text()
    sign_body = service.split("def sign(", 1)[1].split("\ndef ", 1)[0]
    dispatch_body = service.split("def dispatch(", 1)[1].split("\ndef ", 1)[0]
    claim_body = outbox.split("def _claim(", 1)[1].split("\ndef ", 1)[0]
    for body in (sign_body, dispatch_body, claim_body):
        assert "gate.decide(session" in body


def test_only_the_outbox_sends() -> None:
    """S15: `.send(` on a transport appears in the outbox drain and nowhere else in the app."""
    senders = [
        path.relative_to(APP).as_posix()
        for path in _python_files(APP)
        if re.search(r"transport\.send\(", path.read_text())
    ]
    assert senders == ["modules/prescriptions/outbox.py"]


def test_the_transport_interface_is_imported_only_inside_the_module() -> None:
    importers = sorted(
        path.relative_to(APP).as_posix()
        for path in _python_files(APP)
        if "prescriptions.transport import" in path.read_text()
    )
    assert importers == [
        "modules/prescriptions/outbox.py",
        "modules/prescriptions/service.py",
    ]
