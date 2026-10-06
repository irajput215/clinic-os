/**
 * The roles of the organisation, each with the permission bundle it resolves to, and the
 * screen's reading of whether the signed-in user may grant it (R3).
 *
 * This panel is read-only: assignment and revocation happen in `UserAccessPanel`, against a
 * named account. What it adds is the grantability explanation, so the restriction is visible
 * before anyone attempts a grant.
 */

import { useQuery } from "@tanstack/react-query"
import { Ban, CheckCircle2, HelpCircle } from "lucide-react"
import { useMemo } from "react"

import type { RoleRead } from "@/client"
import {
  AccessDenied,
  AdminEmpty,
  AdminError,
  AdminLoading,
} from "@/components/Admin/AdminStates"
import { Badge } from "@/components/ui/badge"
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card"
import {
  describeAdminError,
  formatCodeList,
  GRANTABILITY_EXPLANATION,
  type Grantability,
  isForbidden,
  roleGrantability,
} from "@/lib/admin"
import { rolesQueryOptions, selfPermissionsQueryOptions } from "./adminQueries"

function GrantabilityBadge({
  grantability,
}: {
  grantability: Grantability | undefined
}) {
  if (!grantability) {
    return (
      <Badge variant="outline" className="text-muted-foreground">
        <HelpCircle aria-hidden="true" />
        Grantability unknown
      </Badge>
    )
  }
  if (grantability.grantable) {
    return (
      <Badge variant="secondary" data-testid="grantable-badge">
        <CheckCircle2 aria-hidden="true" />
        You can grant this
      </Badge>
    )
  }
  return (
    <Badge
      variant="outline"
      className="border-amber-500/60 text-amber-700 dark:text-amber-400"
      data-testid="cannot-grant-badge"
    >
      <Ban aria-hidden="true" />
      You cannot grant this
    </Badge>
  )
}

function RoleCard({
  role,
  held,
}: {
  role: RoleRead
  held: ReadonlySet<string> | undefined
}) {
  const grantability = roleGrantability(role, held)
  const count = role.permissions.length

  return (
    <Card data-testid={`role-${role.code}`}>
      <CardHeader>
        <div className="flex flex-wrap items-start justify-between gap-3">
          <div className="flex flex-col gap-1">
            <div className="flex flex-wrap items-center gap-2">
              <CardTitle className="text-base">{role.name}</CardTitle>
              <Badge variant="outline" className="font-mono text-xs">
                {role.code}
              </Badge>
              {role.is_system ? (
                <Badge variant="secondary" className="text-xs">
                  System role
                </Badge>
              ) : null}
            </div>
            <p className="text-sm text-muted-foreground">
              {count === 1 ? "1 permission" : `${count} permissions`}
            </p>
          </div>
          <GrantabilityBadge grantability={grantability} />
        </div>
      </CardHeader>
      <CardContent className="flex flex-col gap-3">
        {count > 0 ? (
          <ul className="flex flex-wrap gap-1.5">
            {role.permissions.map((permission) => (
              <li key={permission.code}>
                <Badge
                  variant="outline"
                  className="font-mono text-xs"
                  title={permission.description}
                >
                  {permission.code}
                </Badge>
              </li>
            ))}
          </ul>
        ) : (
          <p className="text-sm text-muted-foreground">
            This role grants no permissions.
          </p>
        )}

        {grantability && !grantability.grantable ? (
          <p
            className="text-sm text-muted-foreground"
            data-testid={`role-${role.code}-grantability-reason`}
          >
            {GRANTABILITY_EXPLANATION} Missing:{" "}
            <span className="font-mono">
              {formatCodeList(grantability.missing)}
            </span>
            .
          </p>
        ) : null}
      </CardContent>
    </Card>
  )
}

export function RolesPanel({ currentUserId }: { currentUserId?: string }) {
  const roles = useQuery(rolesQueryOptions)
  const held = useQuery(selfPermissionsQueryOptions(currentUserId))

  const heldCodes = useMemo(() => {
    if (!held.data) return undefined
    return new Set(held.data.permissions.map((permission) => permission.code))
  }, [held.data])

  if (roles.isPending) return <AdminLoading label="Loading roles" />

  if (roles.isError) {
    if (isForbidden(roles.error)) return <AccessDenied />
    return (
      <AdminError
        title="We couldn't load the roles"
        description={describeAdminError(roles.error)}
        onRetry={() => roles.refetch()}
        retrying={roles.isFetching}
      />
    )
  }

  if (roles.data.data.length === 0) {
    return <AdminEmpty message="This organisation has no roles yet." />
  }

  return (
    <div className="flex flex-col gap-4" data-testid="roles-panel">
      <p className="text-sm text-muted-foreground">
        {heldCodes
          ? "Grantability is read from your own effective permissions: you can grant only a role whose every permission you already hold."
          : "Your own effective permissions could not be read, so this screen cannot say which roles you can grant. The API still decides every grant."}
      </p>
      <ul className="flex flex-col gap-4">
        {roles.data.data.map((role) => (
          <li key={role.id}>
            <RoleCard role={role} held={heldCodes} />
          </li>
        ))}
      </ul>
    </div>
  )
}

export default RolesPanel
