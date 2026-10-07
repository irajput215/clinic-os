"""The closed action catalogue and the payload allow-list — frozen reference data.

Sources, quoted rather than re-derived:

- The **action names** are the closed vocabulary of `docs/features/04-audit-log/05-data-and-audit.md`
  §"The action catalogue (doc 07 §1)", which is normative here. *"No new action name may be invented.
  A new action must be registered in doc 07 §1 first, by a change to the source contract, before any
  code emits it."*
- The `resource_type` vocabulary is the same document's envelope table: `PATIENT, CLINICAL_RECORD,
  PRESCRIPTION, TGA_APPROVAL, TGA_DOCUMENT, USER, TENANT, SESSION, AUDIT, REPORT, INTEGRATION, EXPORT`.
- The **payload allow-list** is requirement R11 and `04-threat-model.md` T-AUD-4: *"Per-action
  `metadata` allow-list enforced by type and by a runtime schema check before insert; an unlisted key
  throws, request fails `500 AUDIT_PAYLOAD_REJECTED`."*

## Two naming conflicts in the source, and which way this module resolves them

Neither is resolved silently. Both are engineering decisions on an open item, recorded for the lead.

1. **`patient.create` / `patient.update` vs `patient.created` / `patient.updated`.** `05-patients/05-data-and-audit.md`
   lists `patient.created` and `patient.updated`, and then says, in the same section, *"Action names use
   doc 07's **lowercase dotted** form"* — under which its own two rows are misspelled. Doc 07 §1, the
   document that owns the closed catalogue, names `patient.create` and `patient.update`. The catalogue
   is the authority, so those are the two names this module emits; the feature document's own header
   line is the instruction being followed, and its table is the typo.
2. **`ROLE_ASSIGNED` / `ROLE_REVOKED` vs `user.permission_change`.** `03-users-and-roles/05-data-and-audit.md`
   names `ROLE_ASSIGNED` and `ROLE_REVOKED` in its table and then records OPEN-1 — *"one naming
   authority must be chosen before the writer is built"* — because doc 07 §1 names
   `user.permission_change` instead. `user.permission_change` is the only name in the closed
   catalogue, so a role grant and a role revoke both emit it, distinguished by the `change` key in the
   payload. Inventing `ROLE_ASSIGNED` would break the closed-catalogue rule outright; the cost of this
   choice is that "which of the two happened" is in the payload rather than in the action, and it is
   recorded as a gap in the PR.
"""

from types import MappingProxyType
from typing import Final

# The twelve `resource_type` values the design's envelope table names. Closed, like the actions.
RESOURCE_TYPES: Final[frozenset[str]] = frozenset(
    {
        "PATIENT",
        "CLINICAL_RECORD",
        "PRESCRIPTION",
        "TGA_APPROVAL",
        "TGA_DOCUMENT",
        "USER",
        "TENANT",
        "SESSION",
        "AUDIT",
        "REPORT",
        "INTEGRATION",
        "EXPORT",
    }
)

# The `result` vocabulary. `UNKNOWN` is a provider timeout or an unresolved outcome.
RESULTS: Final[frozenset[str]] = frozenset({"SUCCESS", "DENIED", "FAILED", "UNKNOWN"})

# The closed action catalogue, grouped by the resource type doc 07 §1 groups it by. Values are
# lowercase dotted; nothing outside this tuple may ever be written to `audit_log`.
ACTION_CATALOGUE: Final[tuple[tuple[str, tuple[str, ...]], ...]] = (
    (
        "SESSION",
        (
            "auth.login",
            "auth.logout",
            "auth.login_failed",
            "auth.step_up",
            "auth.step_up_failed",
        ),
    ),
    (
        "PATIENT",
        (
            "patient.read",
            "patient.create",
            "patient.update",
            "patient.export",
        ),
    ),
    (
        "CLINICAL_RECORD",
        ("clinical_record.read", "clinical_record.write"),
    ),
    (
        "PRESCRIPTION",
        (
            "prescription.create",
            "prescription.modify",
            "prescription.sign",
            "prescription.dispatch",
            "prescription.dispatch_blocked",
            "prescription.reject",
            "prescription.dispatch_failed",
        ),
    ),
    (
        "TGA_APPROVAL",
        (
            "tga_approval.create",
            "tga_approval.modify",
            "tga_approval.state_change",
            "tga_approval.match",
            "tga_approval.verify",
        ),
    ),
    ("TGA_DOCUMENT", ("tga_document.ingest", "tga_document.extract")),
    ("USER", ("user.permission_change", "user.create", "user.deactivate")),
    ("TENANT", ("tenant.security_config_change",)),
    ("INTEGRATION", ("integration.request",)),
    ("AUDIT", ("audit.read",)),
)

# Derived, never a second source of truth.
ACTIONS: Final[frozenset[str]] = frozenset(
    action for _resource_type, actions in ACTION_CATALOGUE for action in actions
)

# The action → resource-type mapping, derived from the same tuple so the two cannot drift.
RESOURCE_TYPE_BY_ACTION: Final[MappingProxyType[str, str]] = MappingProxyType(
    {
        action: resource_type
        for resource_type, actions in ACTION_CATALOGUE
        for action in actions
    }
)

# Every key any action may carry in its `metadata` payload. A key that is not listed here is refused
# before insert — R11, T-AUD-4. The union is deliberately not "anything an action wants": adding a
# key is a deliberate change with a test.
#
# **No value.** Every key names a field, a code, or a count. `changed_fields`, `field_set`,
# `added` and `removed` carry *names*, never clinical content; `reason` carries a controlled code
# (`04-design.md` "Failure behaviour"). Clinical narrative, medicine or dose text, diagnosis codes,
# Medicare numbers, IHIs, OCR text, document bodies and full request bodies are refused by
# construction: there is no key for them, and an unknown key throws.
PAYLOAD_KEYS: Final[frozenset[str]] = frozenset(
    {
        "added",
        "approval_id",
        "block_reason",
        "care_relationship_id",
        "change",
        "changed_fields",
        "field_set",
        "patient_id",
        "purpose",
        "query_filters",
        "reason",
        "record_count",
        "removed",
        "result_count",
        "role_code",
        "step_up",
        "supersedes_version",
        "target_user_id",
        "version",
    }
)

# The keys each action may carry. An action absent from this mapping may carry **no** payload at all:
# the allow-list is deny-by-default, so a new action starts with nothing and earns each key.
#
# Only the actions this slice emits are enumerated. The remaining catalogue entries are emitted by
# later features and will add their own row here with the test the change needs (T1-22).
PAYLOAD_ALLOW_LIST: Final[MappingProxyType[str, frozenset[str]]] = MappingProxyType(
    {
        # `05-patients/05-data-and-audit.md`: `resource_id` and `field_set` — field **names** only.
        "patient.create": frozenset({"field_set"}),
        # The same table: `resource_id`, `changed_fields` (names only) and `reason`.
        "patient.update": frozenset({"changed_fields", "reason"}),
        # `05-patients/05-data-and-audit.md` names `resource_id`, `care_relationship_id`, `purpose`.
        "patient.read": frozenset({"care_relationship_id", "purpose"}),
        # `04-audit-log/05-data-and-audit.md`: `audit.read` carries `query_filters` and `result_count`.
        "audit.read": frozenset({"query_filters", "result_count"}),
        # `06-clinical-records/05-data-and-audit.md` maps its four story labels onto the two
        # `CLINICAL_RECORD` actions doc 07 §1 already carries, and fixes the key fields they may
        # record — identifiers and version numbers, never the narrative, never the typed amendment
        # reason. `patient_id`/`version`/`supersedes_version` are registered here for it.
        "clinical_record.write": frozenset(
            {"patient_id", "version", "supersedes_version"}
        ),
        # The same table's `CLINICAL_RECORD_VIEWED` row: the patient, the relationship and purpose
        # that authorised the read when those exist, and how many versions were returned.
        "clinical_record.read": frozenset(
            {"patient_id", "care_relationship_id", "purpose", "result_count"}
        ),
        # Doc 07 §1's `user.permission_change`, carrying what `03-users-and-roles/05-data-and-audit.md`
        # asks `ROLE_ASSIGNED`/`ROLE_REVOKED` to carry: the target, the role code, and the change.
        "user.permission_change": frozenset(
            {"target_user_id", "role_code", "change", "added", "removed", "step_up"}
        ),
        # Doc 07 §1's `user.create`, emitted by the staff invitation
        # (`POST /api/v1/users/staff`). `03-users-and-roles/05-data-and-audit.md` asks
        # `USER_CREATED` to carry "target user id, roles, inviter, invitation expiry": the inviter is
        # the envelope's `actor_id`, the roles are `added` (role **codes**), and no key is invented
        # for the expiry, which is the event's timestamp plus `STAFF_INVITATION_EXPIRE_HOURS`.
        # Only keys already in the vocabulary; a refused invitation carries `added` and no target.
        "user.create": frozenset({"target_user_id", "added", "step_up"}),
    }
)

# The refusal reason code. Requirement R11 and T-AUD-4 name it exactly: an unlisted `metadata` key
# throws `AUDIT_PAYLOAD_REJECTED` and the request fails.
PAYLOAD_REJECTED: Final[str] = "AUDIT_PAYLOAD_REJECTED"


def resource_type_for(action: str) -> str:
    """The `resource_type` the catalogue binds to `action`.

    Raises `KeyError` for an action outside the catalogue, so a typo cannot reach the writer: the
    caller that invented a name fails at its own call site rather than writing an event no catalogue
    names.
    """
    return RESOURCE_TYPE_BY_ACTION[action]
