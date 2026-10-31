"""Intake tests reuse the appointments fixtures: a clinic with an owner, a doctor and a nurse."""

from tests.appointments.conftest import _open_registration, api, clinic

__all__ = ["_open_registration", "api", "clinic"]
