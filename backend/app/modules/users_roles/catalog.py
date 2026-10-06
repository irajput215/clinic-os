"""The permission catalogue and the seven system role bundles — frozen reference data.

Sources, quoted rather than re-derived:

- The **19 permission codes** are the matrix in
  `docs/features/03-users-and-roles/01-requirements.md`, "Permission catalogue (role x permission)",
  which reconciles `04-database-erd.md` §3.3's "20 permissions" against the 19 it lists and the 19
  `06-authentication-rbac.md` §9-§10 define. Task T1-09 seeds exactly these 19; no candidate code
  from `01-requirements.md` "Candidate additions named elsewhere" is granted (OPEN-1).
- **One twentieth code is added below, and it is a named deviation**: `tenant:read`, which
  `docs/features/01-tenancy-and-clinics/03-design.md` "Endpoints" requires for
  `GET /api/v1/tenants/current` and records as **OPEN-2** ("absent from the fixed 19-permission
  catalogue; tenancy routes cannot pass Gate 4 until reconciled"). The tenancy routes cannot be
  authorised without it, so it is added here and granted to the two roles whose user stories name the
  read — `PRACTICE_OWNER` (US-1) and `COMPLIANCE_AUDITOR` (US-7, read-only). Nothing else is granted,
  and widening the matrix stays CTO-owned under OPEN-1/OPEN-2.
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
time, not a reason to omit the permission from the bundle. A `-` cell is not granted. Of those rules,
the care-relationship one now has a table and a hook — `care_relationships` plus
`policy.PatientResourceRef`, resolved by `app.modules.care_relationships.service` — while prescriber of
record and pharmacy routing remain unbuilt with their later features.

`COMPLIANCE_AUDITOR` carries `G`/`-` only in the matrix in `01-requirements.md`; the `ro`/`pl`/`ts`
modifiers on its cells are resource rules, not different grants.
"""

from typing import Final

# (code, description). The nineteen codes of `01-requirements.md`, in the order it lists them, plus
# the one addition the module docstring records (`tenant:read`, OPEN-2).
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
    # The twentieth code, and the only one that is not in the 19 of `01-requirements.md`: the read
    # `GET /api/v1/tenants/current` requires (`01-tenancy-and-clinics/03-design.md`, "Endpoints",
    # permission `tenant:read` marked OPEN-2). Added by the Feature 01 remainder task; the grant is
    # limited to the two roles whose user stories name it (US-1 Practice Owner, US-7 Compliance /
    # Auditor) and the seed migration grants it to existing tenants.
    ("tenant:read", "Read the organisation's identity, status and data region."),
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
                # US-7: "as an auditor I want read-only visibility of tenant and clinic
                # configuration". `PRACTICE_OWNER` holds every code by construction; no other
                # bundle gains `tenant:read` (see the module docstring and the seed migration).
                "tenant:read",
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

# The permission that administers people. `03-design.md` "Endpoints" gives it to every `/users/*` and
# `/roles/*` row, and R8's "last Administrator permission" — the one whose removal would leave an
# organisation with nobody able to manage users — is this code.
ADMINISTRATION_PERMISSION: Final[str] = "users:manage"

# The permission each administration route requires. `03-design.md` "Endpoints" gives
# `ADMINISTRATION_PERMISSION` to every `/users/*` and `/roles/*` row. `role:read`/`role:manage` are
# **candidates only** (`01-requirements.md`, "Candidate additions named elsewhere") and are not
# granted while OPEN-1 and OPEN-6 are open, so no route uses them.
USERS_ROLES_PERMISSIONS: Final[dict[str, str]] = {
    "list_roles": ADMINISTRATION_PERMISSION,
    "list_permissions": ADMINISTRATION_PERMISSION,
    "read_user_roles": ADMINISTRATION_PERMISSION,
    "read_user_permissions": ADMINISTRATION_PERMISSION,
    "assign_role": ADMINISTRATION_PERMISSION,
    "revoke_role": ADMINISTRATION_PERMISSION,
}

# R8's refusal reason. `01-requirements.md` R8 fixes the rule and the status (`409`); it does not name
# a reason code, so this module names one, in the same `{code, message}` envelope every other denial
# uses. The administration screen reads the code to explain the refusal rather than guess at it.
LAST_ADMINISTRATOR: Final[str] = "LAST_ADMINISTRATOR"

# The permission each tenancy route requires. `GET /api/v1/tenants/current` is `tenant:read` —
# `01-tenancy-and-clinics/03-design.md` "Endpoints" names it and marks it OPEN-2, which is why the
# code was added to the catalogue above. `PATCH /api/v1/tenants/current` is `tenant:configure`, one of
# the fixed 19. Named here so the route declaration, the policy call and the tests cannot drift.
TENANCY_PERMISSIONS: Final[dict[str, str]] = {
    "read": "tenant:read",
    "configure": "tenant:configure",
}

# The `Action` suffix the design gives each administration endpoint's audit event
# (`05-data-and-audit.md`, "Audit events emitted"). Feature 04 is not built, so the routes declare
# these names as deferred rather than writing them; naming them here keeps the declaration honest.
USERS_ROLES_AUDIT_ACTIONS: Final[dict[str, str]] = {
    "assign_role": "ROLE_ASSIGNED",
    "revoke_role": "ROLE_REVOKED",
}
