"""Onboarding tests reuse the prescriptions fixtures: a clinic with an owner, a second doctor and a
patient, and helpers to approve, stage and sign through the real API."""

from tests.prescriptions.conftest import _open_registration, clinic, rx

__all__ = ["_open_registration", "clinic", "rx"]
