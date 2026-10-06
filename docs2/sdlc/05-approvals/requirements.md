# TGA approvals: requirements

**For:** Clinicians and the practice manager who record SAS-B / Authorised Prescriber approvals and keep them current.

## User stories

- As a nurse, I record a new approval exactly as the TGA letter states it.
- As a second clinician, I verify it against the letter so it can authorise scripts.
- As the principal, I see which approvals need action: pending verification or expiring within 30 days.
- As a clinician, I revoke an approval with a reason code.

## Functional requirements

- R1 The grain is patient + TGA category + dosage form, never brand.
- R2 Record: category, dosage form, reference (as printed), reason code, valid from, **valid to as printed on the letter**. At most two years. It starts PENDING.
- R3 **D-006:** the end date is sent unchanged. The UI states that the end date itself is not covered until the clinical safety ruling ([ADR-F003](../../adr/ADR-F003-validity-boundary-in-the-ui.md)).
- R4 Four-eyes: whoever recorded it can't verify it. The verifier re-types the reference from the letter, and a mismatch is refused.
- R5 An overlapping ACTIVE approval at the same grain is refused (GiST exclusion server-side). The UI points to supersede.
- R6 Revoke needs a reason code; PENDING and ACTIVE only.
- R7 Register filters: Needs action, Active, Pending, Expired & revoked, All, each with a count.

## Non-functional

- Reason codes, never free text, in revoke (free text would reach the audit trail).

## Out of scope (this phase)

- Supersede flow UI (API exists on the branch).
- TGA inbox extraction (feature 09).
