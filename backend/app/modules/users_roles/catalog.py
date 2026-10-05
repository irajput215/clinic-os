"""The permission catalogue and the seven system role bundles — frozen reference data.

Sources, quoted rather than re-derived:

- The **19 permission codes** are the matrix in
  `docs/features/03-users-and-roles/01-requirements.md`, "Permission catalogue (role x permission)",
  which reconciles `04-database-erd.md` §3.3's "20 permissions" against the 19 it lists and the 19
  `06-authentication-rbac.md` §9-§10 define. Task T1-09 seeds exactly these 19; no candidate code
  from `01-requirements.md` "Candidate additions named elsewhere" is granted (OPEN-1).
- The **seven system role codes** are `PRACTICE_OWNER`, `AUTHORISED_PRESCRIBER`, `DOCTOR`, `NURSE`,
  `ADMINISTRATOR`, `PHARMACY`, `COMPLIANCE_AUDITOR`
  (`docs/features/03-users-and-roles/01-requirements.md`, "Roles are thin bundles over granular
  permissions").

Two things the design does **not** give and this module therefore supplies, flagged for the lead:

1. `permissions.description`. The column is `NOT NULL` and no text is specified anywhere, so each
   description is a one-line, non-clinical summary of the code's meaning.
2. `roles.name`. The design says only "tenant may edit the display name". The seeded display names are
   the codes in title case.

A cell that carries a modifier (`G cr`, `G su`, `G ro`, `G draft`, `G own`, `G agg`, `G dc`, `G pl`,
`G ts`, `G pr`) is a **grant**; the modifier is a resource rule the policy layer applies at decision
time, not a reason to omit the permission from the bundle. A `-` cell is not granted. The resource
rules themselves are not implemented in this slice: `care_relationships` has no table definition
(task T1-34, blocked), so `can()` has no rule hook to run yet.

`COMPLIANCE_AUDITOR` carries `G`/`-` only in the matrix in `01-requirements.md`; the `ro`/`pl`/`ts`
modifiers on its cells are resource rules, not different grants.
"""

from typing import Final

# (code, description). The nineteen codes, in the order `01-requirements.md` lists them.
PERMISSION_CATALOGUE: Final[tuple[tuple[str, str], ...]] = (
    ("patient:read", "Read patient records within the actor's organisation."),
    ("patient:create", "Create a patient record in the actor's organisation."),
    ("patient:update", "Update a patient record the actor may act on."),
    (
        "patient:export",
        "Export patient records; requires step-up and a logged purpose code.",
    ),
    ("clinical_record:read", "Read clinical records the actor may act on."),
    ("clinical_record:write", "Write clinical record versions."),
    ("prescription:create", "Create a prescription."),
    ("prescription:modify", "Modify a prescription the actor may act on."),
    ("prescription:sign", "Sign a prescription as the prescriber of record."),
    ("prescription:dispatch", "Dispatch a signed prescription."),
    ("tga_approval:read", "Read TGA approvals."),
    ("tga_approval:create", "Create a TGA approval request."),
    ("tga_approval:verify", "Verify a TGA approval."),
    ("tga_inbox:process", "Process the TGA inbox."),
    ("audit:read", "Read the organisation's audit trail."),
    ("reports:export", "Export reports."),
    ("users:manage", "Manage users, role assignment and permission grants."),
    ("tenant:configure", "Change the organisation's security configuration."),
    ("pharmacy:dispatch", "Receive and confirm a pharmacy dispatch."),
)

# (code, display name, granted permission codes). Every permission in the catalogue appears in at
# least one bundle; a code absent from a bundle is a denial (`-` in the matrix), not an omission.
SYSTEM_ROLE_CATALOGUE: Final[tuple[tuple[str, str, frozenset[str]], ...]] = (
    (
        "PRACTICE_OWNER",
        "Practice Owner",
        frozenset(code for code, _ in PERMISSION_CATALOGUE),
    ),
    (
        "AUTHORISED_PRESCRIBER",
        "Authorised Prescriber",
        frozenset(
            {
                "patient:read",
                "patient:create",
                "patient:update",
                "patient:export",
                "clinical_record:read",
                "clinical_record:write",
                "prescription:create",
                "prescription:modify",
                "prescription:sign",
                "prescription:dispatch",
                "tga_approval:read",
                "tga_approval:create",
                "tga_approval:verify",
            }
        ),
    ),
    (
        "DOCTOR",
        "Doctor",
        frozenset(
            {
                "patient:read",
                "patient:create",
                "patient:update",
                "clinical_record:read",
                "clinical_record:write",
                "prescription:create",
                "prescription:modify",
                "prescription:sign",
                "prescription:dispatch",
                "tga_approval:read",
                "tga_approval:create",
                "tga_approval:verify",
                "reports:export",
            }
        ),
    ),
    (
        "NURSE",
        "Nurse",
        frozenset(
            {
                "patient:read",
                "patient:create",
                "patient:update",
                "clinical_record:read",
                "clinical_record:write",
                "prescription:create",
                "prescription:modify",
                "tga_approval:read",
            }
        ),
    ),
    (
        "ADMINISTRATOR",
        "Administrator",
        frozenset(
            {
                "patient:read",
                "patient:create",
                "patient:update",
                "patient:export",
                "clinical_record:read",
                "tga_approval:read",
                "tga_inbox:process",
                "audit:read",
                "reports:export",
                "users:manage",
            }
        ),
    ),
    (
        "PHARMACY",
        "Pharmacy",
        frozenset({"patient:read", "pharmacy:dispatch"}),
    ),
    (
        "COMPLIANCE_AUDITOR",
        "Compliance / Auditor",
        frozenset(
            {
                "patient:read",
                "patient:export",
                "clinical_record:read",
                "tga_approval:read",
                "tga_approval:verify",
                "tga_inbox:process",
                "audit:read",
                "reports:export",
            }
        ),
    ),
)

# Convenience lookups, derived — never a second source of truth.
PERMISSION_CODES: Final[frozenset[str]] = frozenset(
    code for code, _ in PERMISSION_CATALOGUE
)
SYSTEM_ROLE_CODES: Final[tuple[str, ...]] = tuple(
    code for code, _, _ in SYSTEM_ROLE_CATALOGUE
)

# The permission the self-service organisation signup path is bootstrapped with. `PRACTICE_OWNER`
# is the only role holding `tenant:configure` and the only one that can administer its own
# organisation, which is what "signup makes the signer its administrator" means for a new tenant.
# The design does not name a bootstrap role; this is an engineering decision (reported).
BOOTSTRAP_ROLE_CODE: Final[str] = "PRACTICE_OWNER"

# The permission each of the four patient routes requires. Named here so the route declaration, the
# policy call and the access-control matrix test cannot drift apart.
PATIENT_PERMISSIONS: Final[dict[str, str]] = {
    "create": "patient:create",
    "read": "patient:read",
    "update": "patient:update",
}
