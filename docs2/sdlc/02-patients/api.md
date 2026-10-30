# Patients: API

Status: **Agreed 2026-10-07 (owner)**, as amended below to follow `docs/features/05-patients`.

| Method | Path | Source | Notes |
|---|---|---|---|
| `GET` | `/api/v1/patients?limit=1..25&cursor=` | `backend/app/modules/patients/router.py` | Keyset page `{data, count, next_cursor}`. Any other query parameter is `422 UNSUPPORTED_QUERY_PARAMETER` |
| `POST` | `/api/v1/patients/search` | same | Body `{q, cursor?, limit?}`; same response shape. Rate limited 120/min per session |
| `POST` | `/api/v1/patients` | same | `PatientCreate`; `201` gives `PatientRead` |
| `GET` | `/api/v1/patients/{patient_id}` | same | `404` when absent or another tenant's; `403 AUTHZ_CARE_RELATIONSHIP_DENIED` for a relationship-bound reader without a care relationship (T1-34). Audited. Rate limited 300/min |
| `PATCH` | `/api/v1/patients/{patient_id}` | same | `PatientUpdate`, unknown fields rejected; the same relationship rule |
| `GET` | `/api/v1/patients/{patient_id}/care-relationships` | `backend/app/modules/care_relationships/router.py` | The care team: `{data: CareTeamMember[], count}` (T1-34, D-007) |
| `POST` | `/api/v1/patients/{patient_id}/care-relationships` | same | `{practitioner_id}`; `201` gives the team. `409 ALREADY_IN_CARE_TEAM`, `422 PRACTITIONER_NOT_FOUND` |
| `POST` | `/api/v1/patients/{patient_id}/care-relationships/{care_relationship_id}/end` | same | Ends it now; `404 RELATIONSHIP_NOT_FOUND` when not active |

## The patient record (docs3 feature 04, 2026-10-30)

| Method | Path | Notes |
|---|---|---|
| `GET` | `/api/v1/patients?status=` | Repeatable lifecycle filter; without it the list holds the active patients (archived, discharged and deceased leave it). Search finds every status |
| `POST` | `/api/v1/patients/{patient_id}/status` | `{status, reason?, deceased_at?}`; a reason is required for `BLOCKED`, `ARCHIVED`, `DISCHARGED`, the date for `DECEASED` (`422 STATUS_REASON_REQUIRED`) |
| `GET`/`POST` | `/api/v1/patients/{patient_id}/alerts` | `{text, tone: INFO\|WARN\|DANGER}`; answers the active alerts |
| `POST` | `/api/v1/patients/{patient_id}/alerts/{alert_id}/remove` | Hides it; the row is kept |
| `GET`/`POST` | `/api/v1/patients/{patient_id}/emergency-contacts` | `{name, relationship, phone}` |
| `POST` | `/api/v1/patients/{patient_id}/emergency-contacts/{contact_id}/remove` | Hides it; the row is kept |

`PatientCreate`/`PatientUpdate` accept `medicare_number` (10 digits), `medicare_irn` (1-9), `ihi` (16
digits, `800360…`), `receives_communications` and `timezone`. Identifiers are encrypted with a blind
index and answered only as `medicare_masked` / `ihi_masked` (`•••• ` + last three); a 10-digit or IHI
search term matches exactly through the index. `PatientRead` also carries `status`, `status_reason`
and `escript_ready {ready, missing[]}`. A `BLOCKED` patient is refused new bookings (staff and public)
and new script drafts (`422 PATIENT_BLOCKED`); reminders skip a patient who opted out.

## The agreed search and paging contract

The proposal here was `GET /api/v1/patients?q=&cursor=`. `docs/` is normative and forbids that shape:
`05-patients/01-requirements.md` R12 (*"Search terms never appear in a URL ... a `q=` query string is not
routed"*) and OPEN-5. So the contract is split in two:

- **List** - `GET /patients?limit=&cursor=`. Backward compatible: `limit` keeps its meaning and `count`
  stays the tenant's live total; `next_cursor` is new. A `q` (or any unknown parameter) is refused, not
  ignored, so a client that puts the term in the URL gets an error instead of the unfiltered list.
- **Search** - `POST /patients/search` with the term in the body.

**Order and cursor.** Keyset on `(family_name, given_name, id)`, never `OFFSET`. `next_cursor` is opaque:
the boundary row's id plus an HMAC over the tenant, the request's scope (the list, or one normalised
search) and the id. It cannot be forged, replayed in another tenant, or reused for a different search
(`422 INVALID_CURSOR`). It carries no name, so the list's cursor is safe in a URL.

**What is searchable** (`05-patients/03-design.md`: the plaintext search keys). Each word must match:

| Word | Matches |
|---|---|
| `1980-03-14` or `14/03/1980` | `date_of_birth`, exactly |
| `PT-` + 4..32 hex digits | the on-screen reference (the id's prefix) |
| anything else | case-insensitive **prefix** of `family_name`, `given_name` or `preferred_name`; `%`, `_` and `\` are escaped |

Not searchable: Medicare and IHI (exact match on a keyed blind index only, R8; no identifier is stored
yet), contact and address fields (direct identifiers, not search keys). `q` is 1..100 characters and at
most 6 words; the minimum length is an open item (O3), so the floor is one character.

**Audit.** Every list and search page writes `patient.read` on the same transaction with `result_count`
and, for a search, `query_filters` (the kinds of word used: `name_prefix`, `date_of_birth`,
`reference`) - never the term. Refusals (permission, unknown parameter, bad cursor) are audited `DENIED`.
The term is never logged.

**Index.** `(tenant_id, lower(<name>) text_pattern_ops)` on the three name columns, migration
`b9fa64996260`; the EXPLAIN evidence is in its docstring.

## The treating-relationship rule (T1-34, agreed 2026-10-08; decision D-007)

`docs/features/05-patients` R7 and `06-clinical-records` R11, as built:

- **Who it binds.** The matrix's `cr` grants: a `DOCTOR`'s or `NURSE`'s `patient:read`,
  `patient:update`, `clinical_record:read` and `clinical_record:write`. An account that holds the code
  through any other role (owner, authorised prescriber, administrator) is not bound. `GET
  /users/me/permissions` adds `relationship_bound: string[]` (advisory) so the screen can explain.
- **Where.** `GET`/`PATCH /patients/{id}`, every clinical-record route, a patient's appointments,
  scripts (`GET /prescriptions?patient_id=`) and TGA approvals, and staging a script. Across a tenant
  boundary the answer stays `404`; inside the tenant without a relationship it is
  `403 {code: "AUTHZ_CARE_RELATIONSHIP_DENIED"}`. The relationship is resolved in the route's first
  statement (no extra round trip), under the request's RLS policy.
- **Lists.** For a bound reader, `GET /patients` and `POST /patients/search` return only the patients
  they have an active relationship with, and `count` counts only those.
- **Audit.** A direct read writes `patient.read` `SUCCESS` with `care_relationship_id` (when one
  authorised it) and `purpose` (`TREATMENT` when a relationship authorised the read,
  `PRACTICE_ADMINISTRATION` when an unconditional grant did; server-derived, never sent by the client).
  Lists and searches add `purpose` too. Every refusal - not found, permission, relationship - is
  `DENIED` with its reason.

## Care team (T1-34, interim source of truth; decision D-007)

Who maintains `care_relationships` is OPEN (open-questions C13). Until it is decided, a relationship
exists only because somebody recorded it on the patient's **Care team** card: an account whose own
`patient:update` is not relationship-bound (owner, authorised prescriber, administrator); everybody
else is `403 PERMISSION_NOT_HELD`. The practitioner must be an active doctor, authorised prescriber or
nurse of the practice. Nothing creates a relationship implicitly (not a booking, not a consult note).

| Shape | Fields |
|---|---|
| `CareRelationshipCreate` | `practitioner_id` (unknown fields `422`) |
| `CareTeamMember` | `id`, `practitioner_id`, `practitioner_name` (`null` for a former staff member), `active_from`, `source` |
| `CareTeamPublic` | `data`, `count` |

Audited on the same transaction: `care_relationship.create` (`care_relationship_id`, `target_user_id`,
`source`) and `care_relationship.end` (`care_relationship_id`, `target_user_id`); the list writes
`patient.read` with `query_filters: ["care_team"]`. Writes are rate limited 20/min per session (the
administrative class). An ended relationship keeps its row (`active_to`); there is no delete.
