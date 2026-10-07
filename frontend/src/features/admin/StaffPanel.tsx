import { keepPreviousData, useQuery } from "@tanstack/react-query"
import { KeyRound, UserPlus } from "lucide-react"
import { useState } from "react"
import type { UserPublic } from "@/client/types.gen"
import { Button } from "@/components/ui/button"
import { STAFF_PAGE_SIZE, staffQuery } from "@/data/admin"
import {
  Card,
  EmptyState,
  ErrorState,
  Pill,
  SkeletonRows,
} from "@/design/primitives"
import { displayName } from "@/lib/session"
import { InviteStaffDialog } from "./InviteStaffDialog"

/**
 * The organisation's staff (`GET /users/staff`): every account of the signed-in person's own
 * organisation and the roles each holds. The server resolves the organisation from the session and
 * refuses anyone without `users:manage`. Inviting creates the account with its roles and emails the
 * person a link to choose their own password; "Manage access" opens User access on that account.
 */
export function StaffPanel({
  me,
  onManageAccess,
}: {
  me: UserPublic
  onManageAccess: (accountId: string) => void
}) {
  const [page, setPage] = useState(0)
  const [inviting, setInviting] = useState(false)
  const staff = useQuery({
    ...staffQuery(page),
    placeholderData: keepPreviousData,
  })

  const total = staff.data?.count ?? 0
  const pages = Math.max(1, Math.ceil(total / STAFF_PAGE_SIZE))
  const refused = staff.isError

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <p className="max-w-[640px] text-sm text-stone">
          Everyone who can sign in to your organisation. An invited person
          chooses their own password from the email they receive.
        </p>
        {refused ? null : (
          <Button onClick={() => setInviting(true)}>
            <UserPlus /> Invite staff member
          </Button>
        )}
      </div>

      <Card bodyClassName="-mx-5 -my-[18px]">
        {staff.isPending ? (
          <div className="p-5">
            <SkeletonRows rows={4} />
          </div>
        ) : staff.isError ? (
          <div className="p-5">
            <ErrorState error={staff.error} onRetry={() => staff.refetch()} />
          </div>
        ) : staff.data.data.length === 0 ? (
          <EmptyState title="No staff on this page." />
        ) : (
          <div className="overflow-x-auto">
            <table className="data-table" data-testid="staff-table">
              <thead>
                <tr>
                  <th className="rounded-tl-card pl-5">Name</th>
                  <th className="max-md:hidden">Email</th>
                  <th className="max-sm:hidden">Roles</th>
                  <th className="max-sm:hidden">Status</th>
                  <th className="rounded-tr-card pr-5">
                    <span className="sr-only">Actions</span>
                  </th>
                </tr>
              </thead>
              <tbody>
                {staff.data.data.map((member) => {
                  const self = member.id === me.id
                  const name = member.full_name || displayName(member)
                  return (
                    <tr key={member.id} data-testid={`staff-${member.email}`}>
                      <td className="pl-5 max-sm:w-full max-sm:max-w-0 sm:max-w-[260px]">
                        <div className="flex min-w-0 items-center gap-2">
                          <span
                            className={
                              member.full_name
                                ? "truncate font-semibold"
                                : "truncate text-stone"
                            }
                          >
                            {name}
                          </span>
                          {self ? <Pill tone="clay">You</Pill> : null}
                        </div>
                        <div className="truncate text-xs text-stone md:hidden">
                          {member.email}
                        </div>
                        <div className="mt-1 flex flex-wrap gap-1 sm:hidden">
                          <RolePills roles={member.roles} />
                          {member.is_active ? null : <Pill>Inactive</Pill>}
                        </div>
                      </td>
                      <td className="max-w-[280px] truncate max-md:hidden">
                        {member.email}
                      </td>
                      <td className="max-sm:hidden">
                        <div className="flex flex-wrap gap-1">
                          <RolePills roles={member.roles} />
                        </div>
                      </td>
                      <td className="max-sm:hidden">
                        {member.is_active ? (
                          <Pill tone="ok">Active</Pill>
                        ) : (
                          <Pill>Inactive</Pill>
                        )}
                      </td>
                      <td className="pr-5 text-right">
                        <Button
                          size="sm"
                          variant="outline"
                          aria-label={`Manage access for ${name}`}
                          onClick={() => onManageAccess(member.id)}
                        >
                          <KeyRound />
                          <span className="max-sm:hidden">Manage access</span>
                          <span className="sm:hidden">Access</span>
                        </Button>
                      </td>
                    </tr>
                  )
                })}
              </tbody>
            </table>
          </div>
        )}
      </Card>

      {pages > 1 ? (
        <nav
          aria-label="Staff pages"
          className="flex items-center justify-end gap-2 text-sm text-stone"
        >
          <span>
            Page {page + 1} of {pages}
          </span>
          <Button
            size="sm"
            variant="outline"
            disabled={page === 0}
            onClick={() => setPage((p) => p - 1)}
          >
            Previous
          </Button>
          <Button
            size="sm"
            variant="outline"
            disabled={page + 1 >= pages}
            onClick={() => setPage((p) => p + 1)}
          >
            Next
          </Button>
        </nav>
      ) : null}

      <InviteStaffDialog me={me} open={inviting} onOpenChange={setInviting} />
    </div>
  )
}

function RolePills({
  roles,
}: {
  roles: ReadonlyArray<{ role_id: string; name: string }>
}) {
  if (roles.length === 0)
    return <span className="text-xs text-stone-faint">No role</span>
  return (
    <>
      {roles.map((role) => (
        <Pill key={role.role_id} tone="info">
          {role.name}
        </Pill>
      ))}
    </>
  )
}
