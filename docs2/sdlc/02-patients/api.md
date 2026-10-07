# Patients: API

Status: **Agreed 2026-10-07 (owner)**, as amended below to follow `docs/features/05-patients`.

| Method | Path | Source | Notes |
|---|---|---|---|
| `GET` | `/api/v1/patients?limit=1..25&cursor=` | `backend/app/modules/patients/router.py` | Keyset page `{data, count, next_cursor}`. Any other query parameter is `422 UNSUPPORTED_QUERY_PARAMETER` |
| `POST` | `/api/v1/patients/search` | same | Body `{q, cursor?, limit?}`; same response shape. Rate limited 120/min per session |
| `POST` | `/api/v1/patients` | same | `PatientCreate`; `201` gives `PatientRead` |
| `GET` | `/api/v1/patients/{patient_id}` | same | `404` when absent or another tenant's |
| `PATCH` | `/api/v1/patients/{patient_id}` | same | `PatientUpdate`, unknown fields rejected |

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
