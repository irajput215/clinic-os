"""The S3 Object Lock adapter seam — **not wired**, and it says so out loud.

`docs/features/04-audit-log/03-design.md` §"Immutable export path" specifies an outbox row, an SQS
queue, and an S3 Object Lock bucket in `ap-southeast-2` in `COMPLIANCE` mode, versioned, written by a
write-only role, with a bucket policy that denies `s3:DeleteObject` to every principal except an
audited break-glass role. Requirement R10 and `07-definition-of-done.md` part 6 depend on it.

This module is the seam that specification plugs into and nothing more. It needs three things this
slice does not have:

1. an AWS account and a bucket with Object Lock enabled at creation (it cannot be enabled later);
2. credentials for the write-only role, which is a secret and does not belong in the repository;
3. `boto3`, which is a **new runtime dependency** and therefore a decision for the lead, not a
   convenience (`AGENTS.md`, "Ask first: any new dependency").

So `S3ObjectLockSink` raises `AuditArchiveNotConfigured` rather than importing `boto3`, constructing
a client, or pretending to upload. It is deliberately not reachable from any route: the export
function in `service.py` produces the verified bundle, and where that bundle goes is the deployment's
decision. The PR records this as an explicit gap.
"""

from dataclasses import dataclass
from typing import Final

from app.modules.audit.service import ExportBundle

# The one thing this module must not do is look like it worked. A silent no-op here would mean a
# compliance export that reports success and stores nothing.
NOT_CONFIGURED: Final[str] = "S3_OBJECT_LOCK_NOT_CONFIGURED"


class AuditArchiveNotConfigured(RuntimeError):
    """Raised instead of uploading. The bundle is produced; the immutable store is not wired."""


@dataclass(frozen=True)
class S3ObjectLockSink:
    """The documented wiring point for the immutable export.

    Wiring it is a deployment change, and it is small: construct a `boto3` client with the
    write-only role's credentials, `put_object` the JSONL to `bucket/prefix/<manifest generated_at>`,
    write the manifest alongside it, and return the object URI. Object Lock does the rest — the
    bucket's `COMPLIANCE` retention makes the object undeletable and unshortenable, and the bucket
    policy denies `s3:DeleteObject` to every principal but the break-glass role.

    Until then, every call raises. That is the honest behaviour for an unimplemented control: an
    operator who tries to use it gets a failure, not a false record of an export that never left the
    host.
    """

    bucket: str
    prefix: str = "audit"
    region: str = "ap-southeast-2"

    def put(self, bundle: ExportBundle) -> str:
        """Refuse. See the module docstring for what wiring this requires."""
        raise AuditArchiveNotConfigured(
            f"{NOT_CONFIGURED}: the immutable export is not wired. The bundle for tenant "
            f"{bundle.tenant_id} ({bundle.manifest['event_count']} events, head "
            f"{bundle.manifest['head_hash']}) was produced and verified; storing it needs an S3 "
            f"Object Lock bucket in {bundle.manifest.get('region', self.region)!r} and credentials "
            "for the write-only role. See docs/features/04-audit-log/03-design.md "
            "'Immutable export path'."
        )


__all__ = [
    "NOT_CONFIGURED",
    "AuditArchiveNotConfigured",
    "S3ObjectLockSink",
]
