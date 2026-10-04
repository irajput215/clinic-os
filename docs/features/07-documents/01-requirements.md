---
doc_id: FEAT-DOC-01
title: Documents, requirements
owner: Head of Platform
status: DRAFT
last_reviewed: 2026-10-04
classification: RESTRICTED
related: 05-tenant-isolation, 21-technical-design, 12-data-classification
---

# Documents: requirements

## Purpose

Accept a clinical document, validate and scan it, store it privately under a tenant-prefixed object
key, and serve it back — to an authorised user, for five minutes, through a link the client cannot
retarget. The document is frequently the evidence behind a TGA approval, so its integrity and its
access path both matter.

## Requirements

| ID | Requirement | Acceptance criteria | Verified by |
| --- | --- | --- | --- |
| **R1** | An authorised user uploads a document against a patient | `POST` returns `201` with a `document_id`; `tenant_id` resolved from the session, never from the body; `patient_id` must resolve inside the caller's tenant or `404` | `tests/documents/test_upload.py::test_upload_tenant_from_session` |
| **R2** | The request body is strictly validated | Unknown fields (`tenant_id`, `object_key`, `scan_state`, `sha256`) rejected `422` with zero rows and zero objects written; mass assignment blocked | `tests/security/test_documents_validation.py::test_body_mass_assignment_rejected` |
| **R3** | The object key is generated server-side | Key matches `tenants/{tenant_id}/documents/{document_id}/v{n}/{sanitised_filename}`; a client-supplied key is refused, and no key path escapes the tenant prefix | `tests/documents/test_object_key.py::test_object_key_generated_server_side` |
| **R4** | Every upload passes validation before it is visible | Extension allow-list, declared MIME check, magic-byte check, 25 MB cap, antivirus scan; each failure returns its coded status and is audited | `tests/documents/test_validation.py::test_upload_validation_pipeline` |
| **R5** | An unclean object is never served | Any `scan_state` other than `CLEAN` returns `409 DOCUMENT_NOT_SCANNED`; no presigned URL is minted; the failure is audited | `tests/documents/test_presign.py::test_scan_state_gate_blocks_unclean` |
| **R6** | A download link is short-lived, key-bound and authorised per request | Minted only after an authorisation check on the document row, TTL exactly 300 s, bound to the exact key, logged; a URL altered to another key fails S3 signature and IAM prefix checks | `tests/documents/test_presign.py::test_presigned_url_ttl_is_300_seconds` |
| **R7** | Tenant isolation holds on read, list and download | Cross-tenant `GET` or mint returns `404`, never `403`; RLS returns zero rows without a tenant setting; a URL minted for A cannot reach B's object | `tests/isolation/test_documents_isolation.py::test_cross_tenant_document_returns_404` |
| **R8** | The bucket is private and objects cannot be overwritten silently | Block Public Access on; SSE-KMS; versioning on; no public ACL or policy; no unauthenticated read | `tests/documents/test_bucket_config.py::test_bucket_is_private_versioned_and_encrypted` |
| **R9** | Document bytes never persist outside the object store | Bytes are never written to a log, an audit payload, an error body or a temporary path outside the request; `sha256` is stored, the content is not | `tests/security/test_no_phi_in_log_payload.py::test_document_payloads_contain_no_content` |
| **R10** | Every action is audited, refusals included | `document.uploaded`, `document.viewed`, `document.scan_failed`, `document.deleted` written with the standard envelope; denied and failed attempts audited with the same fidelity as successes | `tests/documents/test_audit.py::test_document_events_and_denials_audited` |
| **R11** | An object is never hard-deleted by the application | No `DELETE` endpoint and no `DELETE` grant on the row; deletion is a `deleted_at` soft delete plus a lifecycle transition to a retention prefix | `tests/security/test_documents_grants.py::test_app_cannot_delete_document_rows_or_objects` |

## Out of scope

- OCR, extraction and confidence scoring — feature 09 (`11-tga-inbox-pipeline.md` §3, §4).
- Email and mailbox ingestion — feature 09.
- Linking a document to a TGA approval record — feature 08 consumes `documents`; it does not own it.
- Content disarm and reconstruction; deliberately not applied by default (`11-tga-inbox-pipeline.md` §9).
- Retention schedule authoring — feature 15 and the Privacy Officer.
- Bulk export of documents — feature 14.

## Open items

| # | Item | Owner | Status |
| --- | --- | --- | --- |
| OPEN-1 | Object-key layout diverges: `05-tenant-isolation.md` §243 fixes the prefix `tenants/{tenant_id}/...`; `11-tga-inbox-pipeline.md` §8 and `04-database-erd.md` §3.9 write `documents/{tenant_id}/{document_id}/...` and `tenants/{tenant_id}/patients/{patient_id}/{uuid}`. R3 adopts the tenant-prefixed form, which satisfies all three prefix rules | Head of Platform | OPEN |
| OPEN-2 | The malware-scanning service receives document content. Its region, sub-processor status and terms are unvalidated | Privacy Officer | REQUIRES LEGAL/REGULATORY VALIDATION |
| OPEN-3 | The 25 MB cap and the 10-files-per-message cap are source figures (`11 §9`); the per-tenant storage quota is undefined | Head of Platform | OPEN |
| OPEN-4 | Whether documents are served inline for any format at all, or always attachment-only | Clinical Safety Officer | OPEN |
| OPEN-5 | Retention period for document rows and objects | Privacy Officer | REQUIRES LEGAL/REGULATORY VALIDATION |
| OPEN-6 | Four audit event names do not exist in `07-audit-architecture.md` §1; see `05-data-and-audit.md` | Security Lead | OPEN |
