import {
  keepPreviousData,
  useMutation,
  useQuery,
  useQueryClient,
} from "@tanstack/react-query"
import { KeyRound, Loader2, MailPlus, UserPlus } from "lucide-react"
import { useState } from "react"
import { toast } from "sonner"
import type { StaffMemberRead, UserPublic } from "@/client/types.gen"
import { Button } from "@/components/ui/button"
import {
  ADMIN_WRITE,
  describeAccessError,
  resendInvitation,
  STAFF_PAGE_SIZE,
  staffQuery,
} from "@/data/admin"
import {
  Card,
  EmptyState,
  ErrorState,
  FormAlert,
  Pill,
  SkeletonRows,
} from "@/design/primitives"
import { formatDayMonthTime } from "@/lib/format"
import { describeError, refusalCode } from "@/lib/http"
import { displayName } from "@/lib/session"
import { InviteStaffDialog } from "./InviteStaffDialog"

/**
 * The organisation's staff (`GET /users/staff`): every account of the signed-in person's own
 * organisation, the roles each holds and where each stands (active, inactive, or invited and not yet
 * signed up). The server resolves the organisation from the session and refuses anyone without
 * `users:manage`. Inviting creates the account with its roles and emails the person a link to choose
 * their own password; "Resend invite" emails a fresh link and retires the old one; "Manage access"
 * opens User access on that account.
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

  const queryClient = useQueryClient()
  const resend = useMutation({
    mutationFn: (member: StaffMemberRead) => resendInvitation(member.id),
    ...ADMIN_WRITE,
    onSuccess: (updated) => {
      // The answer is the row as it now stands, so it replaces the row in place: no second read of
      // the list, which shares the administrative 20-a-minute budget.
      queryClient.setQueryData(staffQuery(page).queryKey, (list) =>
        list
          ? {
              ...list,
              data: list.data.map((m) => (m.id === updated.id ? updated : m)),
            }
          : list,
      )
      toast.success(`New invitation sent to ${updated.email}`)
    },
    onError: (error) => {
      // A row the server says has no invitation any more is out of date: read the list again.
      if (refusalCode(error) === "INVITATION_NOT_PENDING")
        void queryClient.invalidateQueries({ queryKey: ["admin", "staff"] })
    },
  })
  const resendFailure = resend.isError
    ? refusalCode(resend.error) === "GRANT_EXCEEDS_ACTOR"
      ? "You can't resend this invitation: the person's roles include permissions your own roles don't. Ask someone who holds them to resend it."
      : (describeAccessError(resend.error) ?? describeError(resend.error))
    : null

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
          <div className="relative overflow-x-auto">
            <table className="data-table" data-testid="staff-table">
              <thead>
                <tr>
                  <th className="rounded-tl-card pl-5">Name</th>
                  <th className="max-xl:hidden">Email</th>
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
                      <td className="w-[55%] max-w-0 pl-5 max-sm:w-full">
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
                        <div className="truncate text-xs text-stone xl:hidden">
                          {member.email}
                        </div>
                        <div className="mt-1 flex flex-wrap gap-1 sm:hidden">
                          <RolePills roles={member.roles} />
                          {member.status === "ACTIVE" ? null : (
                            <StatusPill member={member} />
                          )}
                        </div>
                      </td>
                      <td className="w-[45%] max-w-0 truncate max-xl:hidden">
                        {member.email}
                      </td>
                      <td className="max-sm:hidden">
                        <div className="flex flex-wrap gap-1">
                          <RolePills roles={member.roles} />
                        </div>
                      </td>
                      <td className="max-sm:hidden">
                        <StatusPill member={member} />
                      </td>
                      <td className="pr-5">
                        <div className="flex items-center justify-end gap-2">
                          {member.status === "INVITED" ? (
                            <Button
                              size="sm"
                              variant="outline"
                              aria-label={`Resend invite to ${name}`}
                              title="Resend invite"
                              disabled={resend.isPending}
                              onClick={() => resend.mutate(member)}
                            >
                              {resend.isPending &&
                              resend.variables?.id === member.id ? (
                                <Loader2 className="animate-spin" />
                              ) : (
                                <MailPlus />
                              )}
                              <span className="max-xl:hidden">Resend</span>
                            </Button>
                          ) : null}
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
                        </div>
                      </td>
                    </tr>
                  )
                })}
              </tbody>
            </table>
          </div>
        )}
      </Card>

      {resendFailure ? <FormAlert>{resendFailure}</FormAlert> : null}

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

/**
 * Where one person stands. An invitation shows when its link stops working (the server decides
 * whether it already has), in the clinic's timezone like every other time in the app.
 */
function StatusPill({ member }: { member: StaffMemberRead }) {
  if (member.status === "INACTIVE") return <Pill>Inactive</Pill>
  const invitation = member.invitation
  if (member.status !== "INVITED" || !invitation)
    return <Pill tone="ok">Active</Pill>
  if (invitation.expired)
    return (
      <Pill
        tone="danger"
        title={`The link expired ${formatDayMonthTime(invitation.expires_at)}`}
      >
        Invitation expired
      </Pill>
    )
  return (
    <span className="inline-flex flex-wrap items-center gap-x-1.5 gap-y-0.5">
      <Pill tone="warn">Invited</Pill>
      <span className="text-xs whitespace-nowrap text-stone">
        expires {formatDayMonthTime(invitation.expires_at)}
      </span>
    </span>
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
