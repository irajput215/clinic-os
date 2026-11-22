# Consent library: requirements

| ID | Requirement | Source |
|---|---|---|
| R1 | Consents move from code constants to versioned documents a clinic can publish: platform defaults remain until a clinic publishes its own | `intake/consents.py` today; (manual §12.3: confirm) |
| R2 | A published version is immutable; a patient's agreement keeps pointing at the exact version and text hash they saw (as `patient_consents` does today) | existing |
| R3 | When a clinic publishes a new version of a consent, patients on the old version are shown as **needing re-consent**; nothing is assumed | D22 |
| R4 | A patient can withdraw a consent; withdrawal is a new append-only record, effective from that moment, and what it stops (for example telehealth bookings) is shown to staff | D22 |
| R5 | Consent text is checked by the comms guardrail before publishing (07) | 07 |

Schema change (ask first): `consent_documents`, `consent_document_versions`; withdrawals as a new
`patient_consents` row kind or a `consent_withdrawals` table (D22).
