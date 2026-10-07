import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query"
import { Loader2, TriangleAlert } from "lucide-react"
import { type FormEvent, useId, useState } from "react"
import { toast } from "sonner"
import type {
  RoleRead,
  StaffPublic,
  UserPublic,
  UserRoleRead,
} from "@/client/types.gen"
import { Button } from "@/components/ui/button"
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog"
import {
  ADMIN_WRITE,
  applyAccessChange,
  assignRole,
  describeAccessError,
  formatList,
  GRANT_RULE,
  missingToGrant,
  revokeRole,
  rolesQuery,
  userPermissionsQuery,
  userRolesQuery,
} from "@/data/admin"
import {
  Card,
  EmptyState,
  ErrorState,
  Field,
  FormAlert,
  Mono,
  Pill,
  SkeletonRows,
} from "@/design/primitives"
import { formatDate } from "@/lib/format"
import { describeError, isNotFound } from "@/lib/http"
import { useHeldCodes } from "./held"

const UUID = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i

/**
 * One account's access: the roles it holds, the effective set the server computes from them, and
 * the two real operations on it, grant and revoke.
 *
 * The usual way here is Staff (`GET /users/staff`), whose "Manage access" opens this tab on that
 * account (`initial`). An account can still be addressed by its ID, which each person can copy from
 * Settings; without one the tab starts on the signed-in account.
 */
export function AccessPanel({
  me,
  initial,
}: {
  me: UserPublic
  initial?: string
}) {
  const [accountId, setAccountId] = useState(initial ?? me.id)
  const [draft, setDraft] = useState(initial ?? me.id)
  const [draftError, setDraftError] = useState<string>()
  const inputId = useId()

  const lookup = (e: FormEvent) => {
    e.preventDefault()
    const value = draft.trim()
    if (!UUID.test(value)) {
      setDraftError("Enter an account ID, like the one shown in Settings.")
      return
    }
    setDraftError(undefined)
    setAccountId(value.toLowerCase())
  }

  return (
    <div className="space-y-5">
      <Card title="Account">
        <form
          onSubmit={lookup}
          noValidate
          className="flex flex-wrap items-start gap-3"
        >
          <Field
            label="Account ID"
            htmlFor={inputId}
            error={draftError}
            hint="Each person can copy their account ID from Settings."
            className="min-w-0 basis-full sm:min-w-[260px] sm:flex-1 sm:basis-auto"
          >
            <input
              id={inputId}
              className="field-input font-mono text-[13px]"
              value={draft}
              onChange={(e) => setDraft(e.target.value)}
              autoComplete="off"
              spellCheck={false}
              aria-invalid={draftError ? "true" : undefined}
            />
          </Field>
          <div className="flex gap-2 sm:pt-[23px]">
            <Button type="submit" variant="outline" size="lg">
              View access
            </Button>
            {accountId !== me.id ? (
              <Button
                type="button"
                variant="ghost"
                size="lg"
                onClick={() => {
                  setDraft(me.id)
                  setDraftError(undefined)
                  setAccountId(me.id)
                }}
              >
                Use my account
              </Button>
            ) : null}
          </div>
        </form>
      </Card>

      <AccountAccess key={accountId} accountId={accountId} me={me} />
    </div>
  )
}

function AccountAccess({
  accountId,
  me,
}: {
  accountId: string
  me: UserPublic
}) {
  const assignments = useQuery(userRolesQuery(accountId))
  const effective = useQuery(userPermissionsQuery(accountId))
  const roles = useQuery(rolesQuery)
  const held = useHeldCodes(me.id)
  const [revoking, setRevoking] = useState<UserRoleRead | null>(null)
  const isMe = accountId === me.id
  const queryClient = useQueryClient()
  // The name, when Staff already loaded this account: no extra read on the administrative budget.
  const known = queryClient
    .getQueriesData<StaffPublic>({ queryKey: ["admin", "staff"] })
    .flatMap(([, page]) => page?.data ?? [])
    .find((member) => member.id === accountId)

  const error = assignments.error ?? effective.error ?? roles.error
  if (error) {
    if (isNotFound(error))
      return (
        <Card>
          <EmptyState
            title="That account isn't available."
            body="There's no account with this ID in your organisation. An account in another organisation looks the same, by design."
          />
        </Card>
      )
    return (
      <ErrorState
        error={error}
        onRetry={() => {
          void assignments.refetch()
          void effective.refetch()
          void roles.refetch()
        }}
      />
    )
  }

  if (!assignments.data || !effective.data || !roles.data)
    return (
      <Card>
        <SkeletonRows rows={4} />
      </Card>
    )

  return (
    <>
      <div className="grid gap-5 lg:grid-cols-2">
        <Card
          title="Assigned roles"
          action={
            <span className="text-xs text-stone">
              {isMe ? (
                "Your account"
              ) : known ? (
                known.full_name || known.email
              ) : (
                <Mono>{accountId.slice(0, 8)}</Mono>
              )}
            </span>
          }
        >
          {assignments.data.data.length === 0 ? (
            <EmptyState
              title="No roles."
              body="Without a role this account can't do anything. Grant one below."
            />
          ) : (
            <ul
              className="-mx-5 divide-y divide-line-faint border-line-faint border-t"
              data-testid="assigned-roles"
            >
              {[...assignments.data.data]
                .sort((x, y) => x.name.localeCompare(y.name))
                .map((a) => (
                  <li
                    key={a.role_id}
                    data-testid={`assigned-${a.code}`}
                    className="flex items-center justify-between gap-3 px-5 py-3"
                  >
                    <div className="min-w-0">
                      <div className="flex flex-wrap items-center gap-2">
                        <span className="font-semibold">{a.name}</span>
                        {a.is_system ? <Pill>System</Pill> : null}
                      </div>
                      <div className="mt-0.5 text-xs text-stone">
                        <Mono className="text-[11.5px]">{a.code}</Mono>
                        <span className="mx-1.5">·</span>granted{" "}
                        {formatDate(a.granted_at)}
                      </div>
                    </div>
                    <Button
                      size="sm"
                      variant="outline"
                      aria-label={`Revoke ${a.name}`}
                      onClick={() => setRevoking(a)}
                    >
                      Revoke
                    </Button>
                  </li>
                ))}
            </ul>
          )}
        </Card>

        <Card
          title="Effective permissions"
          action={
            <span className="text-xs text-stone">
              {effective.data.count === 1
                ? "1 permission"
                : `${effective.data.count} permissions`}
            </span>
          }
        >
          <p className="mb-3 text-xs text-stone">
            Computed by the server from the roles above.
          </p>
          {effective.data.permissions.length === 0 ? (
            <p className="text-sm text-stone">No permissions.</p>
          ) : (
            <ul
              className="flex flex-wrap gap-1.5"
              data-testid="effective-permissions"
            >
              {effective.data.permissions.map((p) => (
                <li key={p.code} title={p.description}>
                  <Mono className="inline-block rounded-chip bg-fill px-2 py-0.5 text-[11.5px] text-ink">
                    {p.code}
                  </Mono>
                </li>
              ))}
            </ul>
          )}
        </Card>
      </div>

      <GrantRoleCard
        accountId={accountId}
        roles={roles.data.data}
        held={held}
        heldRoleIds={new Set(assignments.data.data.map((a) => a.role_id))}
      />

      <RevokeRoleDialog
        accountId={accountId}
        assignment={revoking}
        onOpenChange={(open) => {
          if (!open) setRevoking(null)
        }}
      />
    </>
  )
}

function GrantRoleCard({
  accountId,
  roles,
  held,
  heldRoleIds,
}: {
  accountId: string
  roles: readonly RoleRead[]
  held: readonly string[] | undefined
  heldRoleIds: ReadonlySet<string>
}) {
  const queryClient = useQueryClient()
  const [roleId, setRoleId] = useState("")
  const [choiceError, setChoiceError] = useState<string>()
  const selectId = useId()
  const selected = roles.find((r) => r.id === roleId)
  const missing = selected ? missingToGrant(selected, held) : undefined

  const grant = useMutation({
    mutationFn: () => assignRole(accountId, roleId),
    ...ADMIN_WRITE,
    onSuccess: (role) => {
      applyAccessChange(queryClient, accountId, { kind: "granted", role })
      toast.success(`${role.name} granted`)
      setRoleId("")
    },
  })

  const submit = (e: FormEvent) => {
    e.preventDefault()
    if (!roleId) {
      setChoiceError("Choose a role.")
      return
    }
    setChoiceError(undefined)
    grant.mutate()
  }

  return (
    <Card title="Grant a role">
      <form onSubmit={submit} noValidate className="grid max-w-[560px] gap-3">
        <Field label="Role" htmlFor={selectId} error={choiceError}>
          <select
            id={selectId}
            className="field-input"
            value={roleId}
            onChange={(e) => {
              setRoleId(e.target.value)
              grant.reset()
            }}
            aria-invalid={choiceError ? "true" : undefined}
          >
            <option value="">Choose a role</option>
            {roles.map((r) => {
              const lacks = missingToGrant(r, held)
              const notes = [
                heldRoleIds.has(r.id) ? "already held" : null,
                lacks?.length ? "you can't grant this" : null,
              ].filter(Boolean)
              return (
                <option key={r.id} value={r.id}>
                  {r.name}
                  {notes.length ? ` (${notes.join(", ")})` : ""}
                </option>
              )
            })}
          </select>
        </Field>

        {missing?.length ? (
          <div
            role="note"
            className="flex items-start gap-2.5 rounded-btn bg-warn-tint px-3 py-2.5 text-[13px] text-warn-deep"
          >
            <TriangleAlert className="mt-0.5 size-4 shrink-0" />
            <p>
              {GRANT_RULE} You don't hold {formatList(missing)}, so the server
              will refuse this grant.
            </p>
          </div>
        ) : null}

        {grant.isError ? (
          <FormAlert>
            {describeAccessError(grant.error) ?? describeError(grant.error)}
          </FormAlert>
        ) : null}

        <div>
          <Button type="submit" disabled={grant.isPending}>
            {grant.isPending ? <Loader2 className="animate-spin" /> : null}
            Grant role
          </Button>
        </div>
      </form>
    </Card>
  )
}

function RevokeRoleDialog({
  accountId,
  assignment,
  onOpenChange,
}: {
  accountId: string
  assignment: UserRoleRead | null
  onOpenChange: (open: boolean) => void
}) {
  const queryClient = useQueryClient()
  const revoke = useMutation({
    mutationFn: async (target: UserRoleRead) => {
      await revokeRole(accountId, target.role_id)
      return target
    },
    ...ADMIN_WRITE,
    onSuccess: (target) => {
      applyAccessChange(queryClient, accountId, {
        kind: "revoked",
        roleId: target.role_id,
      })
      toast.success(`${target.name} revoked`)
      onOpenChange(false)
    },
    onError: (error) => {
      // Already gone (another administrator, or a stale list): let the list catch up.
      if (isNotFound(error))
        applyAccessChange(queryClient, accountId, { kind: "unknown" })
    },
  })

  return (
    <Dialog
      open={assignment !== null}
      onOpenChange={(open) => {
        if (revoke.isPending) return
        if (!open) revoke.reset()
        onOpenChange(open)
      }}
    >
      <DialogContent>
        {assignment ? (
          <div className="grid gap-4">
            <DialogHeader>
              <DialogTitle>Revoke {assignment.name}?</DialogTitle>
              <DialogDescription>
                The account loses every permission this role carries, unless
                another of its roles also grants it. The change is recorded, and
                the role can be granted again later.
              </DialogDescription>
            </DialogHeader>
            {revoke.isError ? (
              <FormAlert>
                {describeAccessError(revoke.error) ??
                  (isNotFound(revoke.error)
                    ? "This role is no longer assigned to the account. The list has been refreshed."
                    : describeError(revoke.error))}
              </FormAlert>
            ) : null}
            <DialogFooter>
              <Button
                type="button"
                variant="outline"
                onClick={() => onOpenChange(false)}
                disabled={revoke.isPending}
              >
                Keep role
              </Button>
              <Button
                variant="destructive"
                disabled={revoke.isPending}
                onClick={() => revoke.mutate(assignment)}
              >
                {revoke.isPending ? <Loader2 className="animate-spin" /> : null}
                Revoke role
              </Button>
            </DialogFooter>
          </div>
        ) : null}
      </DialogContent>
    </Dialog>
  )
}
