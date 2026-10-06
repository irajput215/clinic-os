# Script queue and safety gate: requirements

**For:** Nurses who stage scripts after triage; doctors who review, sign and send them.

## User stories

- As a nurse, I stage a script with the triage outcome and the conventional therapy tried first.
- As a doctor, I see each draft with the gate's answer for its date of service before I open it.
- As a doctor, I sign and send with my password, and nothing can be sent without a covering approval.
- As a doctor, I see recent sends with their eScript tokens and pharmacies.

## Functional requirements

- R1 A draft records product (which gives category and form), quantity, repeats (0 to 5), directions, triage outcome, conventional therapy first, reviewing doctor and date of service. All are required.
- R2 Each awaiting script shows the **current** gate answer (re-evaluated against today's approvals), not the answer at staging.
- R3 Review and sign shows the gate answer for the date of service. If it refuses, the password field and Sign are disabled and the reason code is shown with a link to the patient's approvals.
- R4 Only the assigned prescriber can sign. Signing needs the password (interim step-up, ADR-F002).
- R5 The gate is evaluated again at sign **and** at dispatch, server-side. A refusal at either step leaves the script BLOCKED and nothing is sent.
- R6 Recent activity lists sent scripts with mono token, RTPM status and pharmacy. "Just my scripts" filters by prescriber.

## Non-functional

- Fail closed: if the gate can't be reached, signing is impossible and the screen says so.

## Out of scope (this phase)

- Real Parchment dispatch (adapter, outbox, reconciliation: backend).
- Cancel/void with the pharmacy.
- Drug catalogue management.
