# D-006: Approval grain enforcement and the validity-window boundary

- **Status:** Accepted for the enforcement mechanism; 🔴 **OPEN — requires Clinical Safety Officer sign-off** for the validity boundary
- **Date:** 2026-10-04
- **Owner:** Clinical Safety Officer + CTO
- **Source contract references:** `08-tga-approval-model.md` §4 (grain enforcement) and §5 (validity window); `04-database-erd.md` §3.6; `20-product-requirements.md` §5; `23-sprint-plan.md` §4; `26-security-gates.md` §3 Gate 2

## Context

The source contract contradicts itself on the two things that decide whether a prescription may be
dispensed. Both contradictions sit inside the clinical safety gate — **INV-2** — so neither can be left
to the implementer.

### Contradiction 1: how the one-live-approval-per-grain rule is enforced

Source doc `08-tga-approval-model.md` §4 defines a uniqueness rule at the grain and then says, in terms:

> **"An exclusion constraint is deliberately not used."**

But three other source documents and the repository's own gate require the opposite:

| Source | Requires |
|---|---|
| `08-tga-approval-model.md` §4 | `UNIQUE (tenant_id, patient_id, tga_category, dosage_form)`; **no** exclusion constraint |
| `04-database-erd.md` §3.6 | GiST exclusion on overlapping `ACTIVE` intervals |
| `20-product-requirements.md` §5 | GiST exclusion on overlapping `ACTIVE` intervals |
| `23-sprint-plan.md` §4 | Approval register with "GiST exclusion on overlapping active intervals" |
| `26-security-gates.md` §3, Gate 2 check | "The approval grain is enforced by a GiST exclusion constraint on overlapping active intervals" |

**A uniqueness constraint at the grain is structurally incompatible with the supersede chain that doc 08
itself defines.** If only one row may exist per grain, a replacement approval cannot supersede its
predecessor — the `SUPERSEDED` row and the new `ACTIVE` row collide on the unique key. Doc 08 requires
both properties simultaneously, so doc 08 §4 cannot be implemented as written.

### Contradiction 2: whether `valid_to` is inside or outside the window

| Source | Representation | `valid_to` itself |
|---|---|---|
| `08-tga-approval-model.md` §5 | `date`, interval read as "valid_from <= service_date <= valid_to" | **Inside** — "the whole of `valid_to`" |
| `04-database-erd.md` §3.6 | `timestamptz` with `tstzrange(..., '[)')` | **Outside** |

This is not a formatting difference. It is a **one-day difference in whether a prescription may be
dispensed**, and it is a clinical safety parameter.

Note also that an approval letter reading "valid to 1 January 2028" is naturally read as *through*
1 January. A half-open interpretation blocks the final day of a legitimate approval.

## Decision

### 1. Enforcement mechanism — **GiST exclusion constraint. Adopted.**

The exclusion constraint is required by the repository's own Gate 2 checklist and by three of the four
source documents. It is the only mechanism that expresses *both* required properties at once:

- one live approval per grain — the constraint is **partial**, applying only to rows where
  `state = 'ACTIVE'`, so a `SUPERSEDED` row never collides with its replacement; and
- no overlapping validity windows for the same grain.

```sql
CREATE EXTENSION IF NOT EXISTS btree_gist;   -- required for the compound temporal exclusion

-- per (tenant_id, patient_id, tga_category, dosage_form), among ACTIVE rows only
CONSTRAINT no_overlapping_active_approvals EXCLUDE USING gist (
    tenant_id      WITH =,
    patient_id     WITH =,
    tga_category   WITH =,
    dosage_form    WITH =,
    validity_interval WITH &&
) WHERE (state = 'ACTIVE')
```

`btree_gist` is required because the exclusion mixes equality operators (`=`) with the range-overlap
operator (`&&`). The `WHERE (state = 'ACTIVE')` clause is what makes the constraint compatible with the
supersede chain.

**Doc 08 §4 must be corrected**, not worked around. That correction is a change to a security and clinical
control and therefore requires CTO **and** Clinical Safety Officer approval, and a **Gate 2 re-run**.

### 2. Validity-window boundary — **half-open `[valid_from, valid_to)` applies, as an interim fail-safe
position only, pending Clinical Safety Officer sign-off.**

Until the Clinical Safety Officer rules, the implementation uses the **narrower** window:

```
valid_from <= date_of_service < valid_to          in Australia/Sydney
```

The reasoning is asymmetric and deliberate:

- **Failing narrow** refuses a prescription on the final day of a legitimate approval. The clinician
  obtains a renewal or escalates. The consequence is inconvenience and delay.
- **Failing wide** dispenses an unapproved therapeutic good outside its regulatory authorisation. The
  consequence is a statutory breach and a potential criminal or civil liability.

When the two failure modes differ by that much, the interim position must be the fail-safe one. The
narrower window is therefore correct **as a default**, not necessarily as the final answer.

**This is a clinical safety parameter and it is not ours to settle.** The Clinical Safety Officer must
confirm the intended reading of a TGA approval letter's end date, and the confirmation must be recorded
here. If the ruling is "inclusive", the change is a clinical behaviour change carrying a **Gate 4
re-run** and a fresh Clinical Safety Officer sign-off — the sign-off cannot be waived.
([`definition-of-done.md`](../definition-of-done.md) §5.)

**Regardless of the ruling**, the gate must:

- evaluate the boundary in a single named timezone (`Australia/Sydney`), never the server's local zone;
- carry an explicit boundary test at 23:59 on `valid_to` and at 00:01 the following day; and
- emit an audit event naming the boundary outcome, so a disputed dispense can be reconstructed.

## Consequences

**Resolved:** the schema can express supersede chains and the non-overlap rule simultaneously. Gate 2's
approval-grain check has an implementable target.

**Still open:** the one-day boundary. Every document in this set that states `[valid_from, valid_to)`
states the **interim** position and must be revisited when the Clinical Safety Officer rules. The
affected documents are
[`docs/features/08-tga-approvals/01-requirements.md`](../../features/08-tga-approvals/01-requirements.md),
[`docs/features/08-tga-approvals/01-requirements.md`](../../features/08-tga-approvals/01-requirements.md) and
[`docs/features/10-prescription-safety-gate/01-requirements.md`](../../features/10-prescription-safety-gate/01-requirements.md).

**Evidence substitution:** the source's own test matrix already contains the boundary test
(`safety_gate.validity_boundary_inclusive_in_sydney`). Under this decision it is **re-specified** as a
half-open boundary test until the ruling changes it — a test whose name and assertion disagree with each
other is worse than no test, so the name must change with the behaviour.

## Effect on the gates

- **Gate 2 (Database):** the approval-grain check now has a specified mechanism. **Gate 2 cannot be
  signed until the constraint exists and its test passes.** Gate 2 has no conditional pass.
- **Gate 4 (APIs):** the boundary ruling is a clinical behaviour change, so closing Contradiction 2 in
  either direction requires a Gate 4 re-run.
- **Gate 6:** the security test matrix must contain the boundary test in its final form.
- No gate is blocked *by this record* — it unblocks Gate 2's grain check and quarantines the boundary
  question behind a named clinical owner.

## Open items

| # | Item | Owner |
|---|---|---|
| 1 | Rule on the `valid_to` reading and record the answer here | **Clinical Safety Officer** |
| 2 | Correct `08-tga-approval-model.md` §4 ("an exclusion constraint is deliberately not used") | CTO + Clinical Safety Officer |
| 3 | Re-run Gate 2 after the constraint lands | Security Lead |
| 4 | Rename or re-specify `safety_gate.validity_boundary_inclusive_in_sydney` to match the final ruling | Clinical Safety Officer |
| 5 | Confirm `btree_gist` is available in the target PostgreSQL build before the migration is written | Head of Platform |
