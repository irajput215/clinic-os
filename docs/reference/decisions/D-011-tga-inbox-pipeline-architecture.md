# D-011: The TGA inbox pipeline is backend code; cloud services do only mailbox, storage, scan and OCR

- **Status:** **Proposed** for the architecture · 🔴 **OPEN** for the cloud and the four vendors
- **Date:** 2026-11-17
- **Owner:** CTO (architecture) · Privacy Officer + Compliance Lead (vendors and residency) · Clinical Safety Officer (thresholds)
- **Source contract reference:** `clinic-os-secure-by-design/11-tga-inbox-pipeline.md`; `21-technical-design.md` §9; `26-security-gates.md` §6. Repo: [FEAT-09](../../features/09-tga-inbox/01-requirements.md), [FEAT-13](../../features/13-integration-boundaries/03-design.md), [D-004](D-004-deployment-target.md)

## Context

FEAT-09 specifies a pipeline that turns TGA approval correspondence arriving by email into an approval
record, in a fixed order:

```
email → sender auth (SPF/DKIM/DMARC) → attachment bounds → MIME/magic-byte agreement → malware scan
      → private storage (hash) → text layer, else OCR → field extraction with per-field confidence
      → patient + grain matching (proposals only) → score → HUMAN VERIFICATION → approval → audit
      → re-evaluate blocked prescriptions (never dispatch)
```

**What exists today (2026-11-17):** none of the pipeline. There is no mailbox, attachment handling,
malware scan, OCR, extraction table or review queue, and no `tga_inbox_*` table. All six Definition
of Done parts in [`07-definition-of-done.md`](../../features/09-tga-inbox/07-definition-of-done.md) are
unticked.

What the pipeline lands on **does** exist:

| Built | Where |
|---|---|
| Approvals: create, verify, revoke, supersede, point-in-time match | `backend/app/modules/tga_approvals/` |
| Grain exclusion constraint and the interim validity boundary | [D-006](D-006-approval-grain-and-validity-boundary.md) |
| Prescription safety gate (refuses a script with no active matching approval) | `backend/app/modules/prescriptions/gate.py` |
| Patient IHI, encrypted, with a blind index for exact-match search | `backend/app/modules/patients/models.py` |
| HPI-I as a practitioner identifier type | `backend/app/modules/users_roles/models.py` |
| Consult notes (SOAP), human-authored | `backend/app/modules/clinical_records/` |

Not present: **HPI-O** (no column anywhere), and IHI **verification** against the Healthcare
Identifiers Service (IHIs are stored as entered).

Two hosted options were raised for the pipeline: **Zapier** and **Azure Data Factory**. Both are
rejected below.

## Decision

### 1. The pipeline is a backend module, not a hosted workflow

All logic lives in `backend/app/modules/tga_inbox/{models,schemas,service,router}.py` plus a worker
entry point, following the module convention in `AGENTS.md`:

- stage order, state machine and terminal states (R1, R19);
- tenant resolution from the **mailbox identity**, never from message content (R11, INV-1);
- audit on every stage, in the same transaction as the state change (R20, INV-4);
- confidence scoring, per-field floors and the tenant threshold policy (R8, R12, R13);
- patient matching as proposals only: two independent identifiers, one being DOB or a national
  identifier, no auto-merge (R10);
- the review queue, claim lease and the verify endpoint, the **only** writer of `ACTIVE` (R14–R17).

Cloud services are used for four commodity jobs only, each behind a FEAT-13 adapter interface with a
simulated driver for CI:

| Job | Adapter | AWS option (source-contract shape) | Microsoft option (if the clinic runs on M365) |
|---|---|---|---|
| Receive mail | `MailboxSource` | SES inbound to S3. *Confirm SES receiving is offered in `ap-southeast-2`* | Shared mailbox read through Microsoft Graph, with the tenant's data held in Australia |
| Store originals | `ObjectStore` | S3 `ap-southeast-2`, private, versioned, SSE | Blob Storage, Australia East, private, versioned |
| Malware scan | `MalwareScanner` | GuardDuty Malware Protection for S3, or ClamAV in an isolated container | Microsoft Defender for Storage malware scanning |
| OCR / layout | `TextExtractor` | Amazon Textract, `ap-southeast-2` | Azure AI Document Intelligence, Australia East |

The text layer is read in-process first (R7); the OCR adapter is called only for pages without one.
Field extraction (approval number, patient name, DOB, IHI, Medicare, product, category, dosage form,
indication, prescriber, HPI-I, dates) is deterministic code over the text, with page and region kept on
every candidate (R9). A value that cannot be read is `NOT_FOUND`, never guessed (R8).

### 2. "Automated approval" means automated preparation, not automated activation

R14 is unchanged and cannot be waived (Gate 5 has no conditional pass for it): **no automated step
makes an approval `ACTIVE`.** The extractor's database role has no write grant on `tga_approvals`.

The automation the clinic gets is everything up to the click: the email is read, every field filled,
the patient candidates found, and the reviewer sees the PDF beside the fields with per-field confidence
and **no pre-selected candidate** (R15). Accept, correct, reject or defer (R16). The target is a usable
record or a queue item within 2 minutes of receipt (R22).

### 3. Notes are drafts until a clinician signs them

An accepted approval may produce a **draft** note in `clinical_records`, built from the accepted values
(not from raw OCR output). It becomes a clinical record only when a clinician with
`clinical_record:write` and a care relationship (D-007) signs it, with that clinician as author. This
follows the intake briefing-note pattern (`docs3/03-patient-intake/design.md`): a clinical note has a
human author.

### 4. Build order

| Step | Content | Depends on |
|---|---|---|
| 1 | Tables (`tga_inbox_messages`, `tga_inbox_attachments`, `tga_extraction_results`, `tga_extraction_candidates`, review queue), RLS, grants, audit actions | Schema approval |
| 2 | Ingest endpoint `POST /api/v1/tga-inbox/messages` (mailbox service role), with the simulated mailbox, store and scanner | Step 1 |
| 3 | Text-layer extraction, field rules, scoring, matching; simulated OCR | Step 2; a labelled golden set (open-questions F1) |
| 4 | Review queue UI and the verify path into `tga_approvals` | Step 3 |
| 5 | Draft note on accept | Step 4 |
| 6 | Real adapters, one per vendor, each enabled only after its sign-off | Cloud choice; V-04, F3 |

Steps 1–5 run end to end in CI and staging with no third-party data flow.

**Progress (2026-11-17):** the backend for steps 1–4 is built in `backend/app/modules/tga_inbox/`, with
stand-ins for every vendor (`adapters.py`) and a standard-library text-layer reader (`pdf_text.py`),
tested in `backend/tests/tga_inbox/`. The review screen (2026-11-21) is `frontend/src/features/inbox/` at
`/tga-inbox`. The draft note (2026-11-21) is built at read time by `GET /patients/{id}/tga-letters` and offered in the
patient's Notes tab ("Start note from letter"); it is never stored and becomes a record only when a
clinician saves it as their own note and signs it. Not yet built: a separate extractor database role, a platform-level quarantine for mail to an
unknown address, and the real vendors (step 6). Choices made in the build, each recorded in the module
docstrings:

- Review routes use the existing `tga_inbox:process` permission rather than adding `tga_inbox:read`
  and `tga_inbox:verify` (a permission-matrix change needs approval).
- Accept creates a `PENDING` approval with `source = INBOX_EXTRACTION`; activation stays with
  `POST /tga-approvals/{id}/verify` by a second clinician, so four-eyes holds.
- Decisions are audited as `tga_approval.verify` and reads as `tga_approval.read` (no new audit
  actions); ingestion as `tga_document.ingest` / `tga_document.extract`, already in the catalogue.
- Extraction thresholds and confidences are provisional until the Clinical Safety Officer signs them
  off; the composite score is shown and never decides.

## Alternatives considered

- **Zapier.** Rejected. Clinical documents (name, IHI, condition) would transit a US-hosted automation
  service, against INV-6. It cannot write the audit event in the same transaction as the change
  (INV-4), performs no MIME or malware checks, holds the clinical mailbox credentials outside our
  secret store, and its flows are not in the repository, so they cannot be tested in CI, reviewed in a
  PR or offered as Gate 5 evidence.
- **Azure Data Factory.** Rejected. It is a batch data-movement and ETL service; it does not receive
  email, scan files, read PDFs or host a review queue, so the real work would still need Logic Apps,
  Functions and Document Intelligence around it. Choosing it would also choose Azure for one feature
  while D-004 is open.
- **An LLM to extract fields.** Not adopted for the first build. It is a new third-party flow for
  highly sensitive content, its output is not deterministic for the cross-check FEAT-09 requires, and
  it would need its own residency and clinical-safety position. It may be revisited as a further
  `TextExtractor` behind the same human verification.

## Consequences

- Easier: one codebase owns the safety controls; every stage is unit- and integration-testable with
  simulated drivers; vendors can be swapped without touching the logic.
- Harder: we run a worker (the source's "one API, one worker" shape), which the FastAPI Cloud + Neon
  deployment does not have today. Until D-004 settles it, the worker can run as the D-009 pattern: an
  idempotent job behind a token-protected internal endpoint.
- Evidence: CI tests S1–S20 and F1–F21 in [`06-test-plan.md`](../../features/09-tga-inbox/06-test-plan.md),
  the grant inspection showing the extractor cannot write `tga_approvals`, and staging runs against a
  sandbox mailbox.

## Effect on the gates

- **Gate 5:** this record is the architecture it reviews. The human-verification control is unchanged.
- **Gate 1:** each vendor adds a data flow to the residency register.
- No gate is blocked by the architecture; step 6 is blocked by the open items below.

## Open items

| Item | Owner | Status |
|---|---|---|
| Cloud for the four adapters: AWS (source shape) or Microsoft (if the clinic already runs M365 in Australia). Ties to D-004 | CTO + Head of Platform | 🔴 OPEN |
| Mailbox provider residency and processing position (V-04) | Privacy Officer | REQUIRES LEGAL/REGULATORY VALIDATION |
| OCR component and its data-processing position (open-questions F3) | Compliance Lead | OPEN |
| Malware scanner and the quarantine boundary | Security Lead | OPEN |
| Threshold values per field and composite (R13, open-questions F2) | Clinical Safety Officer | OPEN |
| Golden set: size, labelling owner, storage (F1) | Clinical Safety Officer | OPEN |
| HPI-O on `clinics` (schema change) and IHI verification via the HI Service (new data flow) | CTO + Privacy Officer | Proposed, not approved |
