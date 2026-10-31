"""Practice tests reuse the prescriptions fixtures: a clinic with an owner, a second doctor and a
patient."""

from tests.prescriptions.conftest import _open_registration, clinic, rx

__all__ = ["_open_registration", "clinic", "rx"]
