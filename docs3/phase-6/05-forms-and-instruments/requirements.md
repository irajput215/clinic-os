# Forms and instruments: requirements

**For:** clinicians and nurses who screen and monitor patients; reception who hand a patient a form;
later, patients completing one remotely (05b).

## User stories

- As a clinician I record a patient's PHQ-9, GAD-7 or K10 and see the score and its band at once.
- As a clinician I am told immediately, and cannot miss, when an answer needs a safety response.
- As a clinician I see a patient's scores over time on their record.
- As a practice manager I publish the clinic's own forms (for example a follow-up check-in) without a
  code change.

## Requirements

| ID | Requirement | Source |
|---|---|---|
| R1 | Three validated instruments ship as platform definitions: **PHQ-9, GAD-7, K10**, item text and response options exactly as published, scored by their published rules | roadmap; (manual §12: confirm) |
| R2 | Scores and severity bands use the published cut-offs only (PHQ-9 0–27, GAD-7 0–21, K10 10–50). A band is a label, never a diagnosis | published scoring |
| R3 | **Safety flags are live**: when a response meets a flag rule, the flag is raised in the same transaction that stores the response, shown on the patient record and to the responsible clinician, and audited. The rules, who is notified and the expected response are a Clinical Safety Officer decision (D20); proposed starting rule: **PHQ-9 item 9 above 0** | roadmap ("live safety flags"); D20 |
| R4 | A flag can be acknowledged only by a clinician with access to the patient (care-relationship rule, D-007), with a required action code; it is never silently cleared | D-007; D20 |
| R5 | A response is **append-only**: answers, score, band, the definition version answered and who entered it. A correction is a new response that names the one it corrects | INV-4 pattern; clinical records |
| R6 | Clinic forms: a practice manager publishes a versioned form from a small field vocabulary (text, choice, scale, date, yes/no). A published version never changes; editing publishes the next version | (manual §12: confirm) |
| R7 | Responses are clinical information: `clinical_record:read` / `write` under the care-relationship rule; never in a log, an error body or an audit payload; `404` across clinics | INV-1, INV-5, D-007 |
| R8 | Phase 6 entry is by staff in clinic (or on a call). Remote completion by the patient is 05b and waits for D21 | D21 |
| R9 | Scores over time appear on the patient record as a list and a simple trend; no clinical interpretation is added | (manual §12: confirm) |

## Out of scope for Phase 6

Instrument licensing beyond the three named (D19); automated outreach on a score; scores feeding a
prescribing decision.
