/**
 * The global permission catalogue: what the 19 codes mean, grouped by the part of the
 * product they govern.
 *
 * `GET /permissions` is global read-only reference data seeded by migration (R7), so there
 * is nothing tenant-specific here and nothing to edit. The grouping is the screen's own;
 * the code and the description come from the API.
 */

import { useQuery } from "@tanstack/react-query"

import {
  AccessDenied,
  AdminEmpty,
  AdminError,
  AdminLoading,
} from "@/components/Admin/AdminStates"
import { Badge } from "@/components/ui/badge"
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card"
import { describeAdminError, groupPermissions, isForbidden } from "@/lib/admin"
import { permissionsQueryOptions } from "./adminQueries"

export function PermissionsPanel() {
  const permissions = useQuery(permissionsQueryOptions)

  if (permissions.isPending) {
    return <AdminLoading label="Loading the permission catalogue" />
  }

  if (permissions.isError) {
    if (isForbidden(permissions.error)) return <AccessDenied />
    return (
      <AdminError
        title="We couldn't load the permission catalogue"
        description={describeAdminError(permissions.error)}
        onRetry={() => permissions.refetch()}
        retrying={permissions.isFetching}
      />
    )
  }

  if (permissions.data.data.length === 0) {
    return (
      <AdminEmpty message="The permission catalogue is empty. It is seeded by migration, so this is unexpected." />
    )
  }

  const groups = groupPermissions(permissions.data.data)

  return (
    <div className="flex flex-col gap-4" data-testid="permissions-panel">
      <p className="text-sm text-muted-foreground">
        Every permission in ClinicOS, grouped by what it governs. The catalogue
        is the same for every organisation and is not editable here; a role is a
        named bundle of these codes.
      </p>
      <div className="grid gap-4 lg:grid-cols-2">
        {groups.map((group) => (
          <Card key={group.id} data-testid={`permission-group-${group.id}`}>
            <CardHeader>
              <CardTitle className="text-base">{group.title}</CardTitle>
              <p className="text-sm text-muted-foreground">
                {group.description}
              </p>
            </CardHeader>
            <CardContent>
              <dl className="flex flex-col gap-3">
                {group.permissions.map((permission) => (
                  <div
                    key={permission.code}
                    className="flex flex-col gap-1 border-b pb-3 last:border-b-0 last:pb-0"
                  >
                    <dt>
                      <Badge variant="outline" className="font-mono text-xs">
                        {permission.code}
                      </Badge>
                    </dt>
                    <dd className="text-sm text-muted-foreground">
                      {permission.description}
                    </dd>
                  </div>
                ))}
              </dl>
            </CardContent>
          </Card>
        ))}
      </div>
    </div>
  )
}

export default PermissionsPanel
