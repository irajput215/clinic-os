# Forms and instruments: design (draft, for decision)

## Data model (schema change: ask first)

All tenant tables with the forced RLS pair; `tenant_id` resolved, never supplied; no `DELETE` for
`clinos_app`.

| Table | Purpose |
|---|---|
| `form_definitions` | One form: platform instrument or clinic form; `kind` (`INSTRUMENT`, `CLINIC_FORM`), `code` (`PHQ9`, `GAD7`, `K10`, or the clinic's), status |
| `form_definition_versions` | Immutable version: items as JSON (id, text, response type, options), scoring rule id, flag rules, published by and when. Platform instruments are seeded rows with a `NULL` tenant, read-only |
| `form_responses` | Append-only: patient, definition version, answers (encrypted at rest like other clinical text), total score, band, entered by, entry method (`STAFF`, later `PATIENT_LINK`), `corrects_id` |
| `safety_flags` | Raised by a response: rule code, raised at, acknowledged by / at / action code. Shown as a patient alert while open |

Scoring and flag rules live in code (`app/modules/forms/instruments.py`), one function per
instrument, keyed by the version's `scoring_rule`. A clinic form has no score unless its fields
declare one.

## Screens

- Patient record, new **Forms** tab: "Record a form" (choose instrument or clinic form), the history
  with scores and bands, open safety flags at the top.
- Entry screen: one item per row, keyboard-friendly, the running score shown, the band on submit.
- A raised flag: a banner on submit and a red alert chip on the record until acknowledged.
- Settings, **Forms**: publish and version clinic forms.

## Routes (sketch)

`GET /forms` · `GET /forms/{id}/versions/{v}` · `POST /patients/{id}/form-responses` ·
`GET /patients/{id}/form-responses` · `POST /safety-flags/{id}/acknowledge` ·
`POST /forms` and `POST /forms/{id}/versions` (practice manager).

## Audit

New actions (registered in the catalogue first): `form_response.create`, `form_response.read`,
`safety_flag.raise`, `safety_flag.acknowledge`, `form.publish`. Payloads carry codes, scores, bands
and ids only, never an answer.

## Tests to write first (denial paths)

Cross-clinic `404`; no relationship `403`; a response cannot be updated or deleted (grant test); a
flag cannot be acknowledged without an action code or by a role without access; every published
scoring example from each instrument's manual scores exactly.
