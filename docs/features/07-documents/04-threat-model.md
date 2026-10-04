---
doc_id: FEAT-DOC-04
title: Documents, threat model
owner: Head of Platform
status: DRAFT
last_reviewed: 2026-10-04
classification: RESTRICTED
related: 05-tenant-isolation, 21-technical-design, 12-data-classification
---

# Documents: threat model

## Method

Inherent risk is the unfixed score; residual risk is the score after the control below is in place.
Both are `Likelihood (1–5) × Impact (1–5)`. Bands: **Low ≤4 · Medium 5–9 · High 10–16 ·
Critical ≥17**. A residual of High or above blocks the gate. Method: `03-threat-model.md` §2.

## STRIDE register

| ID | STRIDE | Threat / attack path | Control | Residual (L×I, band) | Owner | Source |
| --- | --- | --- | --- | --- | --- | --- |
| **D-01** | Info disclosure | Attacker with a valid session guesses the bucket URL and fetches an object directly, bypassing the API and its authorisation check | Private bucket, Block Public Access, no public object or ACL; IAM and bucket policy require the tenant prefix; no object path is guessable in place of an authorisation decision | 1×4 = 4 **Low** | Head of Platform | `21 §5; 03 §8; 05 §242` |
| **D-02** | Info disclosure | A presigned URL is replayed or shared beyond its window — pasted into chat, kept in browser history, harvested from a proxy log | TTL exactly 300 s; bound to the exact key; issued per request and never cached or stored; every issue logged so a replay is attributable | 2×3 = 6 **Medium** | Security Lead | `05 §243; 11 §8; 03 §260` |
| **D-03** | Spoofing / Info disclosure | A URL minted for tenant A is edited to point at B's object key — cross-tenant key confusion | Signature covers the path, so an edited path fails signature verification; the IAM prefix condition independently refuses a key outside A's prefix; the mint checks the document row before signing | 1×4 = 4 **Low** | Security Lead | `05 §243, §292; 03 §260` |
| **D-04** | Info disclosure | Key enumeration: object keys are predictable or tenant-identifying, so an attacker walks the keyspace | Opaque UUID document id inside a tenant prefix; no list-objects permission for the app role; keys never returned in a body or a log line | 1×4 = 4 **Low** | Cloud Lead | `03 §348 (TH-018)` |
| **D-05** | Tampering | A malicious file with an embedded payload, a macro or a double extension is uploaded and later opened by a clinician | Extension allow-list, declared-MIME check, magic-byte check, antivirus scan before visibility, quarantine with a separate IAM boundary, download-only disposition; parsing runs isolated with no network egress | 2×4 = 8 **Medium** | Security Lead | `03 §8; 11 §9` |
| **D-06** | Info disclosure / Tampering | A document is served before the scan completes, so an unscanned object reaches a clinician's workstation | `scan_state` gate: every state except `CLEAN` refuses the mint with `409`; the object is not reachable from the record until the verdict lands; the row defaults to `PENDING` | 1×4 = 4 **Low** | Clinical Safety Officer | `11 §9, §10; 04 §3.9` |
| **D-07** | Spoofing | MIME/extension confusion: a file declares `application/pdf` but carries an executable, or an SVG/HTML payload renders inline and executes | `mime_type` is set from magic bytes, not the header; content delivered as `application/octet-stream` with `X-Content-Type-Options: nosniff` and `Content-Disposition: attachment`; no inline rendering of untrusted types; CSP `object-src 'none'` | 2×3 = 6 **Medium** | Security Lead | `03 §260; 11 §8, §9` |
| **D-08** | Denial of service | Storage exhaustion: bulk or repeated uploads, or a decompression bomb, exhausts the bucket, the scan worker or the per-tenant quota | 25 MB per file, 10 files per message, 100 MB per bulk request, rejection before storage; decompression ratio cap; scan with resource and wall-clock limits; per-tenant upload quota and rate limit | 2×3 = 6 **Medium** | Head of Platform | `11 §9; 02 §11; 03 §8` |
| **D-09** | Info disclosure | SSRF: a client-supplied URL is used as the document source (fetch-from-URL import), reaching instance metadata or an internal service | There is no client-supplied URL path in this feature — bytes arrive as an upload only; where an import path is later added it must use a strict URL allow-list, block internal address ranges, restrict egress and defend against DNS rebinding | 1×5 = 5 **Medium** | Security Lead | `03 §9; 27 §2.5` |
| **D-10** | Tampering | Integrity loss: the stored object is replaced or corrupted, and the record no longer matches what the clinician reviewed | `sha256` recorded at ingest and recomputed on retrieval, mismatch raises an alert; bucket versioning keeps prior versions; Object Lock where the record is evidentiary | 1×4 = 4 **Low** | Compliance Lead | `11 §8; 12 §5.2` |
| **D-11** | Info disclosure | Metadata leakage: EXIF carries device, location or author data out with the image | Metadata stripped on ingest and images re-encoded; the delivery path serves our own determination of the type | 2×2 = 4 **Low** | Head of Platform | `03 §8` |
| **D-12** | Info disclosure | PHI in logs: the original filename, the OCR text or an error body carries a patient name into a log sink, a crash report or analytics | `original_filename`, document content and extracted text are `HIGHLY_SENSITIVE`: never in an application log line, an analytics pipeline or error telemetry; the audit event records the action, not the content | 2×4 = 8 **Medium** | Security Lead | `12 §2, §5.2; 07 §2` |
| **D-13** | Elevation of privilege | A user mints a URL for a document in their own tenant that they are not entitled to see (no treating relationship) | Step 7 of the request path re-checks permission and the treating relationship on the document row before signing, not only the tenant | 2×4 = 8 **Medium** | Clinical Safety Officer | `05 §243; 02 §1 control 2` |
| **D-14** | Repudiation | A clinician or an administrator denies having uploaded, viewed or deleted a document | Append-only `documents_events` written in the same transaction as the change, carrying actor, role, timestamp, source IP, request id and result; denied attempts recorded with equal fidelity | 2×3 = 6 **Medium** | Compliance Lead | `07 §5; 02 §1 control 6` |

## Assumptions

- The bucket is private and the account has Block Public Access on; a public object is a
  misconfiguration, not a design choice.
- Scan verdicts arrive over a signed, authenticated callback; an unsigned callback is rejected.
- The application role is not the bucket owner and cannot delete objects.
- The 300-second TTL is treated as a security invariant, not a configurable default.

## Open items

| Item | Owner | Status |
| --- | --- | --- |
| The malware-scanning service receives document content: its region, sub-processor status and contract terms are unvalidated. This is the same data-flow question as `05-data-and-audit.md` | Privacy Officer | REQUIRES LEGAL/REGULATORY VALIDATION |
| Whether an inline preview is ever permitted, and for which formats | Clinical Safety Officer | OPEN |
| D-09 becomes a live threat the moment a fetch-from-URL import is proposed; no such path may merge without a control and a test | Security Lead | OPEN |
| Whether a residual **Medium** on D-02, D-05, D-07, D-08, D-12 or D-13 is acceptable for the pilot, or requires a compensating control | CTO + Security Lead | OPEN |
