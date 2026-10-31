"""The roles and role-assignment administration API.

Design: `docs/features/03-users-and-roles/03-design.md`, "Endpoints" (the six rows this module owns:
`GET /roles`, `GET /users/{id}/permissions`, `POST /users/{id}/roles`,
`DELETE /users/{id}/roles/{role_id}`) and "Deny-by-default request path". Module ownership:
`docs/reference/build-contract.md` §7 assigns `roles`, `permissions`, `role_permissions` and
`user_roles` — and the `/api/v1/users/*` and `/api/v1/roles/*` prefixes — to `users_roles`, not to
`admin`; feature 15 also puts "role and permission change, and the permission catalogue itself" out
of its own scope (`15-admin-and-config/01-requirements.md`).

Order of the request path, as the design fixes it: authenticate the session → resolve the tenant from
the session → authorise through the central policy layer → load the target account and role under the
tenant-scoped transaction → apply the R3 grantability rule before any write → serialise through a
declared response model.

**The tenant is resolved, never supplied (INV-1).** The actor is built by `app.api.deps.get_actor`
from the session row and nothing else. No body, path, query or header can carry a tenant identifier:
a body `tenant_id` is an unknown field (`422`), and a query or header value is simply never read.

**Cross-tenant is `404`, never `403`** — a `403` confirms the record exists. Every service function
answers `None` (or `False` for a revoke) for both "absent" and "another tenant's", so the two are
indistinguishable to the caller. The permission check runs **before** the lookup, so a caller who does
not hold `users:manage` receives the same `403` whether or not the target exists.

**Revocation is a real delete.** `03-design.md` grants `clinos_app` `SELECT, INSERT, DELETE ON
role_permissions, user_roles` — *"grant/revoke is real"*. The migration that adds the `DELETE` grant
is `grant_delete_on_the_rbac_link_tables`; the append-only audit trail is the history, not the row.

## Endpoint declarations (`docs/reference/definition-of-done.md` §4)

#### `GET /api/v1/roles`
- Authentication: Yes
- Permission: `users:manage`
- Tenant scope: session
- Ownership rule: every returned role's `tenant_id` equals the session's tenant; another tenant's roles are absent, not denied
- Input schema: none — no parameters
- Output schema: `RolesPublic`
- Audit: deferred — feature 04 (audit log) is not built and `05-data-and-audit.md` names no event for a role read
- Rate limit: 20/min per session (T-03.11); a request without a verified session is counted per client address (`app/core/rate_limit.py`)
- Errors: `401` (unauthenticated), `403` (`PERMISSION_NOT_HELD`, or no organisation on the account), `429`; fails closed = yes
- Step-up: no

#### `GET /api/v1/permissions`
- Authentication: Yes
- Permission: `users:manage`
- Tenant scope: session — the actor and its tenant come from the session; the returned catalogue is global reference data with no tenant key and no RLS
- Ownership rule: not applicable — `permissions` is global read-only reference data seeded by migration (R7)
- Input schema: none — no parameters
- Output schema: `PermissionsPublic`
- Audit: deferred — feature 04 (audit log) is not built and `05-data-and-audit.md` names no event for a catalogue read
- Rate limit: 20/min per session (T-03.11); a request without a verified session is counted per client address (`app/core/rate_limit.py`)
- Errors: `401` (unauthenticated), `403` (`PERMISSION_NOT_HELD`, or no organisation on the account), `429`; fails closed = yes
- Step-up: no

#### `GET /api/v1/users/{user_id}/roles`
- Authentication: Yes
- Permission: `users:manage`
- Tenant scope: both — the session resolves the tenant, the target account is matched against it
- Ownership rule: the account's `tenant_id` equals the session's tenant; otherwise `404` with no body fields
- Input schema: none — `user_id` is a UUID path parameter
- Output schema: `UserRolesPublic`
- Audit: deferred — feature 04 (audit log) is not built and `05-data-and-audit.md` names no event for a role read
- Rate limit: 20/min per session (T-03.11); a request without a verified session is counted per client address (`app/core/rate_limit.py`)
- Errors: `401` (unauthenticated), `403` (`PERMISSION_NOT_HELD`, or no organisation on the account), `404` (absent or another tenant's account), `422` (malformed UUID), `429`; fails closed = yes
- Step-up: no

#### `GET /api/v1/users/{user_id}/permissions`
- Authentication: Yes
- Permission: `users:manage`
- Tenant scope: both — the session resolves the tenant, the target account is matched against it
- Ownership rule: the account's `tenant_id` equals the session's tenant; the effective set is computed server-side from the account's roles and nothing from the request
- Input schema: none — `user_id` is a UUID path parameter
- Output schema: `UserPermissionsRead`
- Audit: deferred — feature 04 (audit log) is not built and `05-data-and-audit.md` names no event for a permission read
- Rate limit: 20/min per session (T-03.11); a request without a verified session is counted per client address (`app/core/rate_limit.py`)
- Errors: `401` (unauthenticated), `403` (`PERMISSION_NOT_HELD`, or no organisation on the account), `404` (absent or another tenant's account), `422` (malformed UUID), `429`; fails closed = yes
- Step-up: no

#### `GET /api/v1/users/me/permissions`
- Authentication: Yes
- Permission: none beyond an authenticated, active account in an active organisation - it is the
  design's self-permissions row (`03-design.md`: "valid session", "advisory UI data only; never a
  control"), at the path the owner chose on 2026-10-07; the caller reads only its own set
- Tenant scope: session - the user and the tenant both come from the session row; the route takes no
  parameter at all, so there is no identifier a client could supply
- Ownership rule: the set is the caller's own, resolved by `get_actor` under `tenant_transaction` and
  forced RLS; another tenant's grants are unreachable by construction
- Input schema: none - no parameters
- Output schema: `OwnPermissionsRead` - `{"permissions": [code, ...]}`, sorted
- Audit: none - `04-audit-log/05-data-and-audit.md`'s action catalogue is closed and names no event for
  a permission read, exactly as for the role-read routes above
- Rate limit: none - like `GET /users/me`, it is a self-service read the shell makes on every load;
  the administrative limit would throttle ordinary navigation
- Errors: `401` (unauthenticated or deactivated account), `403` (`NO_ORGANISATION`,
  `TENANT_NOT_ACTIVE`); fails closed = yes. An account holding no role gets `200` with an empty list
- Step-up: no

It is served by `current_user_router`, which `app/api/main.py` mounts **before** `user_roles_router`,
so the literal `me` segment is never captured by `/users/{user_id}/permissions` (a UUID, so `422`).

#### `POST /api/v1/users/{user_id}/roles`
- Authentication: Yes
- Permission: `users:manage`
- Tenant scope: both — the session resolves the tenant; both the target account and the role are matched against it
- Ownership rule: the account and the role both belong to the session's tenant, and every permission in the role's bundle is held by the caller (R3) — otherwise `404`, or `403 GRANT_EXCEEDS_ACTOR`
- Input schema: `RoleAssignmentCreate` — unknown fields rejected, so `tenant_id`, `granted_by` and `user_id` in the body are `422`
- Output schema: `RoleRead` — `201` when the grant is created, `200` when the account already holds the role (the operation is idempotent rather than a `409`)
- Audit: `user.permission_change` — written in the same transaction as the grant (INV-4), with the
  target user id, the role code and the change (`GRANT`, or `NONE` when the account already held it)
- Rate limit: 20/min per session (T-03.11); a request without a verified session is counted per client address (`app/core/rate_limit.py`)
- Errors: `401` (unauthenticated), `403` (`PERMISSION_NOT_HELD`, `GRANT_EXCEEDS_ACTOR`, or no organisation on the account), `404` (absent or another tenant's account or role), `422`, `429`; fails closed = yes
- Step-up: deferred — feature 02's step-up is not built and is blocked by D-003; the design requires a fresh, single-use, 5-minute passkey/hardware-key step-up for this route

#### `DELETE /api/v1/users/{user_id}/roles/{role_id}`
- Authentication: Yes
- Permission: `users:manage`
- Tenant scope: both — the session resolves the tenant; both the target account and the role are matched against it
- Ownership rule: the account, the role and the assignment all belong to the session's tenant, and the removal must leave somebody who can manage users (R8) — otherwise `404`, or `409 LAST_ADMINISTRATOR`
- Input schema: none — `user_id` and `role_id` are UUID path parameters
- Output schema: none — `204 No Content` on success
- Audit: `user.permission_change` — written in the same transaction as the delete (INV-4), with the
  target user id, the role code and `change = REVOKE`; a `404` or `409` changes nothing and writes nothing
- Rate limit: 20/min per session (T-03.11); a request without a verified session is counted per client address (`app/core/rate_limit.py`)
- Errors: `401` (unauthenticated), `403` (`PERMISSION_NOT_HELD`, or no organisation on the account), `404` (absent account, role or assignment, or another tenant's), `409` (`LAST_ADMINISTRATOR` — R8: removing it would leave the organisation with nobody holding `users:manage`), `422` (malformed UUID), `429`; fails closed = yes
- Step-up: deferred — feature 02's step-up is not built and is blocked by D-003; the design requires a fresh, single-use, 5-minute passkey/hardware-key step-up for this route

#### `GET /api/v1/users/staff`
- Authentication: Yes
- Permission: `users:manage`
- Tenant scope: session - the organisation is the session's; a `tenant_id` query parameter is never
  read (there is no `user.*` read action in the closed audit catalogue to record it under, so it is
  ignored without an event)
- Ownership rule: every returned account's `tenant_id` equals the session's tenant; another tenant's
  accounts are absent, not denied
- Input schema: `skip` (>= 0, default 0) and `limit` (1 to 100, default 50) query parameters
- Output schema: `StaffPublic` - `{data: [{id, email, full_name, is_active, status, invitation,
  created_at, roles: [{role_id, code, name}]}], count}`, ordered by name, then email, then id.
  `status` is `INVITED`, `ACTIVE` or `INACTIVE`; `invitation` (`{sent_at, expires_at, expired}`) is
  present only while `INVITED`
- Audit: none - the closed action catalogue names no event for a user read (as for the role reads)
- Rate limit: the administrative class, 20/min per session
- Errors: `401`, `403` (`PERMISSION_NOT_HELD`, `NO_ORGANISATION`, `TENANT_NOT_ACTIVE`), `422`, `429`;
  fails closed = yes
- Step-up: no

#### `POST /api/v1/users/staff`
- Authentication: Yes
- Permission: `users:manage`, plus R3 over the union of the requested roles' bundles
- Tenant scope: session - the account is created in the session's tenant. A body `tenant_id` (or a
  `tenant_id` query parameter) is **ignored and audited** (INV-1) as `user.create` `DENIED`
  `CLIENT_TENANT_ID_IGNORED`, in the same transaction as the invitation
- Ownership rule: every role id must be the session's tenant's, otherwise `404`
- Input schema: `StaffInvite` - `{email, full_name, role_ids[1..7]}`; any other key is `422`. No
  password: the invitee sets their own through the emailed link
- Output schema: `StaffMemberRead`, `201`
- Audit: `user.create` (`SUCCESS`, target user id and role codes) and one `user.permission_change`
  `GRANT` per role, on the creating transaction; a refusal after authorisation writes `user.create`
  `DENIED` with `PERMISSION_NOT_HELD`, `GRANT_EXCEEDS_ACTOR` or `EMAIL_UNAVAILABLE`
- Rate limit: the administrative class, 20/min per session
- Errors: `401`, `403` (`PERMISSION_NOT_HELD`, `GRANT_EXCEEDS_ACTOR`, `NO_ORGANISATION`,
  `TENANT_NOT_ACTIVE`), `404` (a role absent or another tenant's), `409` (`EMAIL_UNAVAILABLE`, the
  same answer whichever organisation holds the address), `422`, `429`, `503`
  (`EMAIL_NOT_CONFIGURED`: no outgoing mail, so nothing is created); fails closed = yes
- Step-up: deferred, as for the role grant - blocked by D-003

#### `POST /api/v1/users/staff/{user_id}/invitation`
- Authentication: Yes
- Permission: `users:manage`, plus R3 over the union of the bundles of the roles the person holds now
  (exactly the invitation's check)
- Tenant scope: both - the session resolves the tenant, the account is matched against it
- Ownership rule: the account's `tenant_id` equals the session's tenant, otherwise `404`; its status
  must be `INVITED`, otherwise `409 INVITATION_NOT_PENDING`
- Input schema: none - `user_id` is a UUID path parameter; there is no body
- Output schema: `StaffMemberRead`, `200`, with the new `invitation`
- Audit: `user.create` `SUCCESS` with `change = INVITATION_RESENT` and the target, on the transaction
  that retires the old link; a refusal writes `user.create` `DENIED` with the same `change` and
  `PERMISSION_NOT_HELD`, `GRANT_EXCEEDS_ACTOR` or `INVITATION_NOT_PENDING`. A `404` writes nothing
- Rate limit: the administrative class, 20/min per session, like the invitation
- Errors: `401`, `403` (`PERMISSION_NOT_HELD`, `GRANT_EXCEEDS_ACTOR`, `NO_ORGANISATION`,
  `TENANT_NOT_ACTIVE`), `404`, `409` (`INVITATION_NOT_PENDING`), `422` (malformed UUID), `429`, `503`
  (`EMAIL_NOT_CONFIGURED`: nothing changes); fails closed = yes
- Step-up: deferred, as for the invitation - blocked by D-003

#### `POST /api/v1/users/signup`
- Authentication: No - open registration (`USERS_OPEN_REGISTRATION`); refused `403` when it is off
- Permission: none; Tenant scope: none - no organisation exists until the link is used
- Input schema: `OrganisationSignup` - `{email, password, full_name?, clinic_name?}`; any other key `422`
- Output schema: `SignupAccepted` - `{request_id, expires_in_hours}`, `202`, **the same for every
  address**: a new one is emailed a verification link, one that has an account a notice (D-008)
- Audit: none - no tenant exists, and the audit log is tenant-scoped; the request row is the record
- Rate limit: 20/min per client address (`signup`)
- Errors: `403` (registration closed), `422`, `429`, `503` (`EMAIL_NOT_CONFIGURED`: nothing is
  written); fails closed = yes

#### `POST /api/v1/users/signup/resend`
- Authentication: No; the body names one signup attempt, `{request_id}`
- Output schema: `Message`, `202`, whatever the id: the attempt's email again with a fresh link, or
  nothing for an unknown, expired or used attempt or after five emails
- Audit: none, as for the signup; Rate limit: 20/min per client address (`signup-resend`)
- Errors: `422`, `429`, `503` (`EMAIL_NOT_CONFIGURED`); fails closed = yes

#### `POST /api/v1/users/signup/verify`
- Authentication: No - the emailed token is the credential: purpose-bound, expiring, single use
- Output schema: `Token`, `200`: the organisation, the account and its Practice Owner grant now
  exist, and the person is signed in
- Audit: `user.create` `SUCCESS` in the new tenant (target and actor the new account, `added =
  [PRACTICE_OWNER]`), on the creating transaction
- Rate limit: 20/min per client address (`signup-verify`)
- Errors: `400` (`SIGNUP_LINK_INVALID`: tampered, expired, replaced, used, a notice, or the address
  has an account by now - one answer), `422`, `429`; fails closed = yes

#### `POST /api/v1/users/invitations/accept`
- Authentication: No - the emailed token is the credential. It is purpose-bound, expires after
  `STAFF_INVITATION_EXPIRE_HOURS` and is single use (`invitations.py`)
- Permission: none; Tenant scope: the account the token names, and the write runs in its tenant
- Input schema: `InvitationAccept` - `{token, new_password}` (8 to 128 characters)
- Output schema: `InvitationAccepted` - `{email}`, so the app can sign the person in
- Audit: none - the closed catalogue has no credential event (password reset writes none either);
  the onboarding itself is the `user.create` event above. Reported as an open question
- Rate limit: 5/min per client address (`invitation-accept`), like password reset: the token is a
  bearer credential
- Errors: `400` (`INVITATION_INVALID`: tampered, expired, already used, or the account is gone or
  deactivated - one answer for all), `422`, `429`; fails closed = yes

The staff routes are mounted before the legacy `/users/{user_id}` router so the literal `staff` and
`invitations` segments are never captured as an account id.

Out of scope for this slice, and why: `POST /users/{id}/deactivate` belongs to T1-03, blocked by
D-003 (the platform superuser's legacy `DELETE /users/{id}` deactivates today); `PUT /roles/{id}/permissions`
changes the fixed permission matrix and needs the step-up mechanism, so it is deferred; the advisory
capabilities are `GET /users/me/permissions`, served here. The grant and the revoke emit their audit events as of
feature 04; the role-read routes emit none, because `04-audit-log/05-data-and-audit.md` names no
action for a role read.

R8's other half — system roles are not deletable — has no route to enforce it on: there is no
`DELETE /roles/{id}` in the design's endpoint table. Its "last Administrator permission cannot be
removed" half is enforced on the revoke route above, because that is the operation that removes a
granting role from an account.
"""

import uuid
from typing import NoReturn

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response, status

from app.api.deps import ActorDep
from app.core.config import settings
from app.core.rate_limit import (
    admin_rate_limit,
    rate_limit,
    read_rate_limit,
    signup_rate_limit,
    signup_resend_rate_limit,
    signup_verify_rate_limit,
)
from app.models import Message, Token
from app.modules.users_roles import onboarding, service, signup
from app.modules.users_roles.catalog import (
    EMAIL_NOT_CONFIGURED,
    EMAIL_UNAVAILABLE,
    INVITATION_INVALID,
    INVITATION_NOT_PENDING,
    LAST_ADMINISTRATOR,
    SIGNUP_LINK_INVALID,
    USERS_ROLES_PERMISSIONS,
)
from app.modules.users_roles.schemas import (
    AgreementCreate,
    IdentifierKind,
    IdentifierUpdate,
    InvitationAccept,
    InvitationAccepted,
    OnboardingPackRead,
    OrganisationSignup,
    OwnPermissionsRead,
    PermissionsPublic,
    RoleAssignmentCreate,
    RoleRead,
    RolesPublic,
    SignupAccepted,
    SignupResend,
    SignupVerify,
    StaffInvite,
    StaffMemberRead,
    StaffPublic,
    UserPermissionsRead,
    UserRolesPublic,
)

# The administrative class carries one rate limit (T-03.11). It is a router-level dependency, so it
# runs before the endpoint's own authentication and authorisation: an unauthenticated flood is also
# bounded, and the RLS-scoped transaction is not opened for a request that will be refused `429`.
_ADMIN_DEPENDENCIES = [Depends(admin_rate_limit)]

roles_router = APIRouter(
    prefix="/roles", tags=["roles"], dependencies=_ADMIN_DEPENDENCIES
)
permissions_router = APIRouter(
    prefix="/permissions", tags=["permissions"], dependencies=_ADMIN_DEPENDENCIES
)
user_roles_router = APIRouter(
    prefix="/users", tags=["users"], dependencies=_ADMIN_DEPENDENCIES
)
# The caller's own surface. Not administrative, so it carries neither the `users:manage` check nor
# the administrative rate limit. It must be mounted before `user_roles_router` (see the declaration).
current_user_router = APIRouter(prefix="/users", tags=["users"])
# The organisation's staff directory and onboarding. Administrative, so the same limit applies. It
# must be mounted before the legacy `/users/{user_id}` routes (see the declarations).
staff_router = APIRouter(
    prefix="/users/staff", tags=["users"], dependencies=_ADMIN_DEPENDENCIES
)
# Spending an invitation link. Unauthenticated: the token is the credential, so it is limited like
# password reset (5/min per client address), in a window of its own.
invitation_accept_rate_limit = rate_limit(scope="invitation-accept", limit=5)
invitations_router = APIRouter(
    prefix="/users/invitations",
    tags=["users"],
    dependencies=[Depends(invitation_accept_rate_limit)],
)

# Organisation signup (D-008). Unauthenticated; each route carries its own per-address limit, so
# the router has none of its own. Mounted before the legacy `/users/{user_id}` routes.
signup_router = APIRouter(prefix="/users/signup", tags=["users"])

MAX_STAFF_PAGE_SIZE = 100


def _not_found(what: str) -> HTTPException:
    """One answer for "absent" and "another tenant's", so the response leaks no existence."""
    return HTTPException(
        status_code=status.HTTP_404_NOT_FOUND, detail=f"{what} not found"
    )


@roles_router.get("", response_model=RolesPublic)
def list_roles(*, actor: ActorDep) -> RolesPublic:
    """List the organisation's roles with each role's permission bundle."""
    service.authorize(actor, USERS_ROLES_PERMISSIONS["list_roles"])
    return service.list_roles(tenant_id=actor.tenant_id)


@permissions_router.get("", response_model=PermissionsPublic)
def list_permissions(*, actor: ActorDep) -> PermissionsPublic:
    """List the global permission catalogue (read-only reference data; R7)."""
    service.authorize(actor, USERS_ROLES_PERMISSIONS["list_permissions"])
    return service.list_permissions(tenant_id=actor.tenant_id)


@current_user_router.get("/me/permissions", response_model=OwnPermissionsRead)
def read_own_permissions(*, actor: ActorDep) -> OwnPermissionsRead:
    """The caller's own effective permission codes. Advisory UI data; never a control."""
    return service.own_permissions(actor)


@user_roles_router.get("/{user_id}/roles", response_model=UserRolesPublic)
def read_user_roles(*, actor: ActorDep, user_id: uuid.UUID) -> UserRolesPublic:
    """List the roles one account of the caller's tenant holds. Another tenant's account is `404`."""
    service.authorize(actor, USERS_ROLES_PERMISSIONS["read_user_roles"])
    assignments = service.read_user_roles(tenant_id=actor.tenant_id, user_id=user_id)
    if assignments is None:
        raise _not_found("User")
    return assignments


@user_roles_router.get("/{user_id}/permissions", response_model=UserPermissionsRead)
def read_user_permissions(
    *, actor: ActorDep, user_id: uuid.UUID
) -> UserPermissionsRead:
    """The effective permission set of one account, computed server-side. Cross-tenant is `404`."""
    service.authorize(actor, USERS_ROLES_PERMISSIONS["read_user_permissions"])
    effective = service.effective_permissions(
        tenant_id=actor.tenant_id, user_id=user_id
    )
    if effective is None:
        raise _not_found("User")
    return effective


@user_roles_router.post(
    "/{user_id}/roles",
    response_model=RoleRead,
    status_code=status.HTTP_201_CREATED,
    # The endpoint is idempotent rather than a `409`: a second POST for a role the account already
    # holds answers `200` with the same body. Declaring it here is what keeps the contract and the
    # generated client honest — without it the OpenAPI document advertises `201` only, and the SDK
    # has no type for the answer the route actually sends.
    responses={
        status.HTTP_200_OK: {
            "model": RoleRead,
            "description": "The account already held the role; nothing was written",
        }
    },
)
def assign_role(
    *,
    actor: ActorDep,
    user_id: uuid.UUID,
    role_in: RoleAssignmentCreate,
    response: Response,
) -> RoleRead:
    """Grant a role to an account. `201` when created, `200` when the account already holds it.

    The grantability rule (R3) is applied in the service before the row is written: a bundle
    containing a permission the caller does not hold is refused `403 GRANT_EXCEEDS_ACTOR`.
    """
    service.authorize(actor, USERS_ROLES_PERMISSIONS["assign_role"])
    assigned = service.assign_role(
        actor=actor, user_id=user_id, role_id=role_in.role_id
    )
    if assigned is None:
        raise _not_found("User or role")
    role, created = assigned
    if not created:
        response.status_code = status.HTTP_200_OK
    return role


@user_roles_router.delete(
    "/{user_id}/roles/{role_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    # R8's refusal is part of the contract, so it is declared: an organisation cannot lose its last
    # holder of `users:manage`, and the generated client can type the answer.
    responses={
        status.HTTP_409_CONFLICT: {
            "description": (
                "Refused: this is the organisation's last role granting `users:manage` (R8). "
                "Assign another administrator first."
            )
        }
    },
)
def revoke_role(*, actor: ActorDep, user_id: uuid.UUID, role_id: uuid.UUID) -> Response:
    """Revoke a role from an account. The delete is real; the audit trail is the history.

    R8: the removal that would leave the organisation with nobody holding `users:manage` is refused
    `409 LAST_ADMINISTRATOR` and nothing is removed.
    """
    service.authorize(actor, USERS_ROLES_PERMISSIONS["revoke_role"])
    outcome = service.revoke_role(actor=actor, user_id=user_id, role_id=role_id)
    if outcome is service.RevokeOutcome.LAST_ADMINISTRATOR:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={
                "code": LAST_ADMINISTRATOR,
                "message": (
                    "This is the organisation's last account that can manage users; assign "
                    "another administrator before revoking this role."
                ),
            },
        )
    if outcome is not service.RevokeOutcome.REVOKED:
        raise _not_found("Role assignment")
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@staff_router.get("", response_model=StaffPublic)
def list_staff(
    *,
    actor: ActorDep,
    skip: int = Query(default=0, ge=0),
    limit: int = Query(default=50, ge=1, le=MAX_STAFF_PAGE_SIZE),
) -> StaffPublic:
    """List the caller's organisation's accounts and the roles each holds."""
    service.authorize(actor, USERS_ROLES_PERMISSIONS["list_staff"])
    return service.list_staff(tenant_id=actor.tenant_id, skip=skip, limit=limit)


@staff_router.post(
    "",
    response_model=StaffMemberRead,
    status_code=status.HTTP_201_CREATED,
    responses={
        status.HTTP_404_NOT_FOUND: {
            "description": "A role is absent, or belongs to another organisation"
        },
        status.HTTP_409_CONFLICT: {
            "description": (
                "Refused: the address already has an account. The same answer whichever "
                "organisation holds it, so no organisation is disclosed."
            )
        },
        status.HTTP_503_SERVICE_UNAVAILABLE: {
            "description": "Outgoing mail is not configured, so no invitation can be sent"
        },
    },
)
def invite_staff(
    *, actor: ActorDep, invite: StaffInvite, request: Request
) -> StaffMemberRead:
    """Onboard a staff member: create the account in the caller's organisation with the chosen
    roles, and email them a link to set their own password.

    The caller can grant only roles whose permissions they hold (R3, `403 GRANT_EXCEEDS_ACTOR`).
    """
    decision = service.can(actor, USERS_ROLES_PERMISSIONS["invite_staff"])
    if not decision.allowed:
        service.record_invitation_denial(actor=actor, reason=decision.code.value)
        service.enforce(decision)
    if not settings.emails_enabled:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail={
                "code": EMAIL_NOT_CONFIGURED,
                "message": "Outgoing email is not configured, so invitations can't be sent.",
            },
        )
    result = service.invite_staff(
        actor=actor,
        invite=invite,
        client_tenant_id_supplied=(
            invite.client_tenant_id_supplied or "tenant_id" in request.query_params
        ),
    )
    if result.outcome is service.InvitationOutcome.ROLE_NOT_FOUND:
        raise _not_found("Role")
    if result.denial is not None:
        service.enforce(
            result.denial
        )  # R3: the policy layer's own `403 GRANT_EXCEEDS_ACTOR`
    if result.outcome is service.InvitationOutcome.EMAIL_UNAVAILABLE:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={
                "code": EMAIL_UNAVAILABLE,
                "message": "This email address can't be invited. It may already have an account.",
            },
        )
    assert result.member is not None
    return result.member


@staff_router.post(
    "/{user_id}/invitation",
    response_model=StaffMemberRead,
    responses={
        status.HTTP_404_NOT_FOUND: {
            "description": "The account is absent, or belongs to another organisation"
        },
        status.HTTP_409_CONFLICT: {
            "description": (
                "Refused: no invitation is outstanding (it was accepted, the person never needed "
                "one, or the account is deactivated)"
            )
        },
        status.HTTP_503_SERVICE_UNAVAILABLE: {
            "description": "Outgoing mail is not configured, so no invitation can be sent"
        },
    },
)
def resend_invitation(*, actor: ActorDep, user_id: uuid.UUID) -> StaffMemberRead:
    """Resend an invitation: email a fresh link, retire the previous one and restart the window.

    Checked exactly like sending one: `users:manage`, then R3 over the roles the person holds now
    (`403 GRANT_EXCEEDS_ACTOR`). Only an outstanding invitation can be resent (`409`).
    """
    decision = service.can(actor, USERS_ROLES_PERMISSIONS["resend_invitation"])
    if not decision.allowed:
        service.record_invitation_denial(
            actor=actor, reason=decision.code.value, resend=True
        )
        service.enforce(decision)
    if not settings.emails_enabled:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail={
                "code": EMAIL_NOT_CONFIGURED,
                "message": "Outgoing email is not configured, so invitations can't be sent.",
            },
        )
    result = service.resend_invitation(actor=actor, user_id=user_id)
    if result.outcome is service.ResendOutcome.NOT_FOUND:
        raise _not_found("Staff member")
    if result.denial is not None:
        service.enforce(result.denial)
    if result.outcome is service.ResendOutcome.NOT_PENDING:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={
                "code": INVITATION_NOT_PENDING,
                "message": (
                    "There is no invitation to resend: this person has already set a password, "
                    "or their account is deactivated."
                ),
            },
        )
    assert result.member is not None
    return result.member


def _require_open_registration_and_mail() -> None:
    """Configuration only, decided before the address is read, so it discloses nothing about one."""
    if not settings.USERS_OPEN_REGISTRATION:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Open user registration is forbidden on this server",
        )
    if not settings.emails_enabled:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail={
                "code": EMAIL_NOT_CONFIGURED,
                "message": (
                    "Outgoing email is not configured, so new organisations can't be "
                    "registered on this server."
                ),
            },
        )


@signup_router.post(
    "",
    response_model=SignupAccepted,
    status_code=status.HTTP_202_ACCEPTED,
    dependencies=[Depends(signup_rate_limit)],
    responses={
        status.HTTP_403_FORBIDDEN: {"description": "Open registration is off"},
        status.HTTP_503_SERVICE_UNAVAILABLE: {
            "description": "Outgoing mail is not configured, so nothing is created"
        },
    },
)
def register_user(*, body: OrganisationSignup) -> SignupAccepted:
    """Register an organisation: email a link that creates it (D-008).

    The answer is the same for every address. A new address is emailed a single-use link that
    creates the organisation and signs its owner in; an address that already has an account is
    emailed a notice instead. Nothing exists until the link is used.
    """
    _require_open_registration_and_mail()
    requested = signup.request_signup(
        email=str(body.email),
        password=body.password,
        full_name=body.full_name,
        clinic_name=body.clinic_name,
    )
    return SignupAccepted(
        request_id=requested.request_id,
        expires_in_hours=settings.SIGNUP_VERIFICATION_EXPIRE_HOURS,
    )


@signup_router.post(
    "/resend",
    response_model=Message,
    status_code=status.HTTP_202_ACCEPTED,
    dependencies=[Depends(signup_resend_rate_limit)],
)
def resend_signup_email(*, body: SignupResend) -> Message:
    """Send a signup's email again with a fresh link. The same answer whatever the id."""
    _require_open_registration_and_mail()
    signup.resend_signup_email(request_id=body.request_id)
    return Message(
        message="If that signup is still waiting, its email is on its way again."
    )


@signup_router.post(
    "/verify",
    response_model=Token,
    dependencies=[Depends(signup_verify_rate_limit)],
    responses={
        status.HTTP_400_BAD_REQUEST: {
            "description": "The link is invalid, expired, replaced or already used"
        }
    },
)
def verify_signup(*, body: SignupVerify) -> Token:
    """Spend a signup link: create the organisation and its owner, and sign the owner in."""
    access_token = signup.verify_signup(token=body.token)
    if access_token is None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={
                "code": SIGNUP_LINK_INVALID,
                "message": "This link is invalid, has expired or was already used.",
            },
        )
    return Token(access_token=access_token)


@invitations_router.post(
    "/accept",
    response_model=InvitationAccepted,
    responses={
        status.HTTP_400_BAD_REQUEST: {
            "description": "The link is invalid, expired or already used"
        }
    },
)
def accept_invitation(*, body: InvitationAccept) -> InvitationAccepted:
    """Spend an emailed invitation link: the invitee chooses their own password."""
    accepted = service.accept_invitation(
        token=body.token, new_password=body.new_password
    )
    if accepted is None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={
                "code": INVITATION_INVALID,
                "message": "This invitation link is invalid, has expired or was already used.",
            },
        )
    return accepted


# -- docs3 feature 02: the onboarding pack and credential vault --------------------------------------

# No router-wide limit: the pack read is a person's own everyday read (the Today card), limited like
# other reads; the vault writes are administrative and carry the administrative limit.
onboarding_router = APIRouter(prefix="/users", tags=["users"])


def _onboarding_refused(refused: onboarding.OnboardingRefused) -> NoReturn:
    raise HTTPException(
        status_code=refused.status_code,
        detail={"code": refused.code, "message": refused.message},
    )


@onboarding_router.get(
    "/{user_id}/onboarding",
    response_model=OnboardingPackRead,
    dependencies=[Depends(read_rate_limit)],
)
def read_onboarding_pack(*, actor: ActorDep, user_id: uuid.UUID) -> OnboardingPackRead:
    """A person's onboarding pack: themself, or `tenant:configure` / `audit:read`. Values masked;
    the read is audited. `404` for an account of another organisation."""
    try:
        return onboarding.read_pack(actor=actor, user_id=user_id)
    except onboarding.OnboardingRefused as refused:
        _onboarding_refused(refused)


@onboarding_router.put(
    "/{user_id}/identifiers/{kind}",
    response_model=OnboardingPackRead,
    dependencies=_ADMIN_DEPENDENCIES,
)
def update_identifier(
    *,
    actor: ActorDep,
    user_id: uuid.UUID,
    kind: IdentifierKind,
    body: IdentifierUpdate,
) -> OnboardingPackRead:
    """Record or re-verify one identifier (`tenant:configure` + a step-up bound to
    `practitioner.identifier_update` and this person). `422 IDENTIFIER_FORMAT` names the format."""
    service.authorize(actor, onboarding.CONFIGURE)
    try:
        return onboarding.update_identifier(
            actor=actor, user_id=user_id, kind=kind, body=body
        )
    except onboarding.OnboardingRefused as refused:
        _onboarding_refused(refused)


@onboarding_router.post(
    "/{user_id}/agreements",
    response_model=OnboardingPackRead,
    status_code=status.HTTP_201_CREATED,
    dependencies=_ADMIN_DEPENDENCIES,
)
def record_agreement(
    *, actor: ActorDep, user_id: uuid.UUID, body: AgreementCreate
) -> OnboardingPackRead:
    """Record the practitioner agreement the person signed (`tenant:configure`); attested by the
    caller."""
    service.authorize(actor, onboarding.CONFIGURE)
    try:
        return onboarding.record_agreement(actor=actor, user_id=user_id, body=body)
    except onboarding.OnboardingRefused as refused:
        _onboarding_refused(refused)
