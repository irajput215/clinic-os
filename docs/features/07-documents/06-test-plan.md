---
doc_id: FEAT-DOC-06
title: Documents, test plan
owner: Head of Platform
status: DRAFT
last_reviewed: 2026-10-04
classification: RESTRICTED
related: 05-tenant-isolation, 21-technical-design, 12-data-classification
---

# Documents: test plan

All tests run in CI on synthetic data. A failing security test blocks merge. Every row carries the
command that proves it.

```bash
cd backend && uv run pytest tests/documents tests/isolation/test_documents_isolation.py tests/security/test_documents_validation.py tests/security/test_documents_grants.py -v
```

## Functional

| ID | Case | Expected result | Command |
| --- | --- | --- | --- |
| **F1** | Upload a clean PDF as an authorised clinician | `201`; row `PENDING` then `CLEAN`; listed for that patient | `cd backend && uv run pytest tests/documents/test_upload.py::test_upload_clean_pdf -v` |
| **F2** | Tenant comes from the session, not the body | `201` in the caller's tenant; a `tenant_id` field in the body returns `422` | `cd backend && uv run pytest tests/documents/test_upload.py::test_upload_tenant_from_session -v` |
| **F3** | Object key is generated server-side in the tenant prefix | Key matches `tenants/{tenant_id}/documents/{document_id}/v1/{name}`; prefix assertion passes | `cd backend && uv run pytest tests/documents/test_object_key.py::test_object_key_generated_server_side -v` |
| **F4** | Re-upload creates a new version, not an overwrite | `v2` key; `v1` object still present | `cd backend && uv run pytest tests/documents/test_object_key.py::test_re_upload_increments_version -v` |
| **F5** | Filename traversal attempt (`../../etc/passwd`, `a.pdf.exe`) | Sanitised or refused `415`; no object written outside the prefix | `cd backend && uv run pytest tests/documents/test_validation.py::test_filename_traversal_and_double_extension_rejected -v` |
| **F6** | Oversized upload (> 25 MB) | `413`; rejected before storage; no row | `cd backend && uv run pytest tests/documents/test_validation.py::test_oversized_upload_rejected_before_storage -v` |
| **F7** | Disallowed type (`.exe`, `.svg`, `.html`) | `415`; no row, no object | `cd backend && uv run pytest tests/documents/test_validation.py::test_disallowed_type_rejected -v` |
| **F8** | Declared MIME does not match magic bytes | `415`; quarantined; `mime_type` set from bytes | `cd backend && uv run pytest tests/documents/test_validation.py::test_magic_byte_mismatch_quarantined -v` |
| **F9** | Scan verdict `CLEAN` | `scan_state = 'CLEAN'`; document becomes listable and mintable | `cd backend && uv run pytest tests/documents/test_scan.py::test_clean_verdict_publishes_document -v` |
| **F10** | Scan verdict `INFECTED` | Quarantined; CSO alert raised; never served | `cd backend && uv run pytest tests/documents/test_scan.py::test_infected_verdict_quarantines_and_alerts -v` |
| **F11** | Soft delete of an unreferenced document | `deleted_at` set; row retained; object untouched | `cd backend && uv run pytest tests/documents/test_delete.py::test_soft_delete_retains_row -v` |
| **F12** | Delete of a document referenced by an approval | Refused `409 DOCUMENT_IN_USE`; nothing changes | `cd backend && uv run pytest tests/documents/test_delete.py::test_delete_referenced_document_refused -v` |
| **F13** | Hash mismatch on retrieval | Retrieval refused; alert raised | `cd backend && uv run pytest tests/documents/test_integrity.py::test_hash_mismatch_blocks_retrieval -v` |

## Security

| ID | Case | Expected result | Command |
| --- | --- | --- | --- |
| **S1** | Mint a URL for a `CLEAN` document | URL returned; expiry is **exactly 300 s**; query params carry `X-Amz-Expires=300`; bound to that exact key | `cd backend && uv run pytest tests/documents/test_presign.py::test_presigned_url_ttl_is_300_seconds -v` |
| **S2** | Use the URL after 301 s | S3 returns `403`; the attempt is recorded | `cd backend && uv run pytest tests/documents/test_presign.py::test_presigned_url_expires -v` |
| **S3** | Mint a URL for a document in another tenant | `404`, no URL minted, `document.denied` audited | `cd backend && uv run pytest tests/isolation/test_documents_isolation.py::test_presign_cross_tenant_denied -v` (source `I-013`) |
| **S4** | Take a URL minted for tenant A and alter it to B's object key | Rejected by signature **and** by the IAM prefix condition; no object bytes returned | `cd backend && uv run pytest tests/isolation/test_documents_isolation.py::test_signed_url_is_tenant_bound -v` — **Staging** (source `I-014`) |
| **S5** | Supply `object_key` in the request body | `422` unknown field; the server-generated key is the only key used | `cd backend && uv run pytest tests/security/test_documents_validation.py::test_client_cannot_supply_object_key -v` |
| **S6** | Assert the stored key carries the tenant prefix | Prefix equals `tenants/{tenant_id}/documents/`; no key without it exists in the bucket | `cd backend && uv run pytest tests/documents/test_object_key.py::test_object_key_prefix_matches_tenant -v` |
| **S7** | Mint for a document whose `scan_state` is `PENDING`, `INFECTED` or `ERROR` | `409 DOCUMENT_NOT_SCANNED`; **no URL minted**; audited — an unclean object is never served | `cd backend && uv run pytest tests/documents/test_presign.py::test_scan_state_gate_blocks_unclean -v` |
| **S8** | List/detail a document whose `scan_state` is not `CLEAN` | Absent from the patient's list; direct `GET` returns `409`, not the metadata | `cd backend && uv run pytest tests/documents/test_scan.py::test_unclean_document_not_listed -v` |
| **S9** | Upload validation stack, end to end | Size cap, extension allow-list, MIME and magic-byte checks each return their coded status and zero rows on failure | `cd backend && uv run pytest tests/documents/test_validation.py::test_upload_validation_pipeline -v` |
| **S10** | Cross-tenant `GET /documents/{id}` | `404`, never `403`, no body fields | `cd backend && uv run pytest tests/isolation/test_documents_isolation.py::test_cross_tenant_document_returns_404 -v` |
| **S11** | Raw SQL as `clinos_app` with no tenant predicate | Only the caller's tenant rows return | `cd backend && uv run pytest tests/isolation/test_documents_isolation.py::test_rls_holds_without_app_filter -v` (source `I-016`) |
| **S12** | Raw SQL as `clinos_app` with `app.tenant_id` unset | Zero rows, no error; the negative is asserted | `cd backend && uv run pytest tests/isolation/test_documents_isolation.py::test_missing_tenant_setting_returns_zero_rows -v` (source `I-017`) |
| **S13** | Insert with another tenant's `tenant_id` while A's context is set | Database rejection: `new row violates row-level security policy` | `cd backend && uv run pytest tests/isolation/test_documents_isolation.py::test_with_check_blocks_cross_tenant_insert -v` (source `I-018`) |
| **S14** | Connection-pool reuse across alternating tenants | No response contains another tenant's document | `cd backend && uv run pytest tests/isolation/test_documents_isolation.py::test_pool_reuse_no_leak -v` — **Staging** (source `I-015`) |
| **S15** | Upload must not be reachable without permission or without a session | `401` unauthenticated; `403` authenticated but unpermitted; both audited | `cd backend && uv run pytest tests/security/test_documents_rbac.py::test_role_endpoint_matrix -v` |
| **S16** | Bucket configuration inspection | Block Public Access on; SSE-KMS on; versioning on; no public ACL or policy; no unauthenticated read | `cd backend && uv run pytest tests/documents/test_bucket_config.py::test_bucket_is_private_versioned_and_encrypted -v` |
| **S17** | Upload rate limit and per-tenant quota | `429 Too Many Requests` with `Retry-After` after the limit | `cd backend && uv run pytest tests/security/test_documents_rate_limits.py::test_upload_rate_limit_and_quota -v` |
| **S18** | Log, error-body and audit-payload inspection with a sentinel document | Zero content bytes, zero filenames, zero full object keys; `sha256` absent too | `cd backend && uv run pytest tests/security/test_no_phi_in_log_payload.py::test_document_payloads_contain_no_content -v` |
| **S19** | Grant inspection on `documents` and `documents_events` | `documents` has no `DELETE`/`TRUNCATE`; `documents_events` has exactly `{SELECT, INSERT}` | `cd backend && uv run pytest tests/security/test_documents_grants.py::test_app_cannot_delete_document_rows_or_objects -v` |
| **S20** | Direct `DELETE` on `documents` as `clinos_app` | `42501 insufficient_privilege` | `cd backend && uv run pytest tests/security/test_documents_grants.py::test_app_delete_document_denied -v` |
| **S21** | SSRF probe: any request field containing a URL | No outbound request; unknown field rejected `422`; egress carries no user-supplied host | `cd backend && uv run pytest tests/security/test_documents_ssrf.py::test_no_client_supplied_url_fetch -v` (source `api.ssrf`) |
| **S22** | Signed scan callback with a bad signature or a replayed event id | `401`; no state change; audited | `cd backend && uv run pytest tests/documents/test_scan.py::test_scan_callback_signature_and_replay_rejected -v` |

## Audit

| ID | Case | Expected result | Command |
| --- | --- | --- | --- |
| **A1** | Successful upload, view, scan failure and delete | One matching event each, full envelope, same transaction as the change; action names registered in `07 §1` | `cd backend && uv run pytest tests/documents/test_audit.py::test_document_events_and_denials_audited -v` |
| **A2** | Each refusal (`404`, `403`, `409`, `413`, `415`, `422`) | `document.denied` with a controlled reason code, same fidelity as a success | `cd backend && uv run pytest tests/documents/test_audit.py::test_denials_audited_with_equal_fidelity -v` |
| **A3** | Audit write fails | The action does not complete and does not commit; alert raised | `cd backend && uv run pytest tests/security/test_audit_writes_in_same_transaction.py::test_document_action_rolls_back_when_audit_fails -v` |

## Traceability

F1–F13 cover R1–R11. S1–S22 cover the security criteria in `02-user-stories.md` and the controls in
`04-threat-model.md`; S3/S4 map to isolation tests `I-013`/`I-014`, S11–S14 to `I-016`–`I-018` and
`I-015`, and S16–S20 to the Gate 2 grant and bucket evidence. A1–A3 cover the event catalogue in
`05-data-and-audit.md`.
