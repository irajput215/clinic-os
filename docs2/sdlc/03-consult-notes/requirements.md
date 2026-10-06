# Consult notes: requirements

**For:** Doctors and nurses charting a consult.

## User stories

- As a doctor, I chart a consult in SOAP sections and sign it.
- As a doctor, I correct a signed note without destroying what was signed.

## Functional requirements

- R1 A note is authored as four SOAP sections. At least one is required. It is stored as one narrative (the backend's single body column).
- R2 A saved note is a draft until signed. Only the author can sign.
- R3 A signed note is immutable. A correction is an amendment: a new version with a mandatory reason. The original stays.
- R4 History is newest first, showing signed/draft and amended version.

## Non-functional

- Note bodies are HIGHLY_SENSITIVE: never logged, never in a URL, never in a toast.

## Out of scope (this phase)

- Attachments (feature 07).
- Templates and autosave.
