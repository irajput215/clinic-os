import { keepPreviousData, useQuery } from "@tanstack/react-query"
import { Pencil, Plus, UserX } from "lucide-react"
import { useState } from "react"
import type { UserPublic } from "@/client/types.gen"
import { Button } from "@/components/ui/button"
import { ACCOUNTS_PAGE_SIZE, accountsQuery } from "@/data/admin"
import {
  Card,
  EmptyState,
  ErrorState,
  Mono,
  Pill,
  SkeletonRows,
} from "@/design/primitives"
import { displayName } from "@/lib/session"
import { AccountFormDialog, DeactivateAccountDialog } from "./AccountDialogs"

/**
 * Platform accounts: the template's superuser-only user management (`/users/`). It is not scoped to
 * an organisation, which is why only a superuser sees this tab and why the server refuses anyone
 * else.
 */
export function AccountsPanel({ me }: { me: UserPublic }) {
  const [page, setPage] = useState(0)
  const accounts = useQuery({
    ...accountsQuery(page),
    placeholderData: keepPreviousData,
  })
  const [editing, setEditing] = useState<UserPublic | "new" | null>(null)
  const [deactivating, setDeactivating] = useState<UserPublic | null>(null)

  const total = accounts.data?.count ?? 0
  const pages = Math.max(1, Math.ceil(total / ACCOUNTS_PAGE_SIZE))

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <p className="max-w-[640px] text-sm text-stone">
          Every account on this server, across organisations. Deactivating keeps
          the account and its history; it can no longer sign in.
        </p>
        <Button onClick={() => setEditing("new")}>
          <Plus /> Add account
        </Button>
      </div>

      <Card bodyClassName="-mx-5 -my-[18px]">
        {accounts.isPending ? (
          <div className="p-5">
            <SkeletonRows rows={5} />
          </div>
        ) : accounts.isError ? (
          <div className="p-5">
            <ErrorState
              error={accounts.error}
              onRetry={() => accounts.refetch()}
            />
          </div>
        ) : accounts.data.data.length === 0 ? (
          <EmptyState
            title="No accounts yet."
            action={
              <Button size="sm" onClick={() => setEditing("new")}>
                <Plus /> Add account
              </Button>
            }
          />
        ) : (
          <div className="relative overflow-x-auto">
            <table className="data-table" data-testid="accounts-table">
              <thead>
                <tr>
                  <th className="rounded-tl-card pl-5">Name</th>
                  <th className="max-md:hidden">Email</th>
                  <th className="max-sm:hidden">Type</th>
                  <th className="max-lg:hidden">Organisation</th>
                  <th>Status</th>
                  <th className="rounded-tr-card pr-5">
                    <span className="sr-only">Actions</span>
                  </th>
                </tr>
              </thead>
              <tbody>
                {accounts.data.data.map((u) => {
                  const self = u.id === me.id
                  return (
                    <tr key={u.id} data-testid={`account-${u.email}`}>
                      <td className="max-w-[260px] pl-5">
                        <div className="flex items-center gap-2">
                          <span
                            className={
                              u.full_name
                                ? "truncate font-semibold"
                                : "truncate text-stone"
                            }
                          >
                            {u.full_name || displayName(u)}
                          </span>
                          {self ? <Pill tone="clay">You</Pill> : null}
                        </div>
                        <div className="truncate text-xs text-stone md:hidden">
                          {u.email}
                        </div>
                      </td>
                      <td className="max-w-[280px] truncate max-md:hidden">
                        {u.email}
                      </td>
                      <td className="max-sm:hidden">
                        {u.is_superuser ? (
                          <Pill tone="purple">Superuser</Pill>
                        ) : (
                          <Pill>Staff</Pill>
                        )}
                      </td>
                      <td className="max-lg:hidden">
                        {u.tenant_id ? (
                          <Mono className="text-stone">
                            {u.tenant_id.slice(0, 8)}
                          </Mono>
                        ) : (
                          <span className="text-stone-faint">None</span>
                        )}
                      </td>
                      <td>
                        {u.is_active === false ? (
                          <Pill>Inactive</Pill>
                        ) : (
                          <Pill tone="ok">Active</Pill>
                        )}
                      </td>
                      <td className="pr-5">
                        {self ? (
                          <div className="h-[30px]" />
                        ) : (
                          <div className="flex justify-end gap-1">
                            <Button
                              size="icon-sm"
                              variant="ghost"
                              aria-label={`Edit ${u.email}`}
                              title="Edit"
                              onClick={() => setEditing(u)}
                            >
                              <Pencil />
                            </Button>
                            {u.is_active === false ? (
                              <span aria-hidden className="size-[30px]" />
                            ) : (
                              <Button
                                size="icon-sm"
                                variant="ghost"
                                className="hover:bg-danger-tint hover:text-danger-deep"
                                aria-label={`Deactivate ${u.email}`}
                                title="Deactivate"
                                onClick={() => setDeactivating(u)}
                              >
                                <UserX />
                              </Button>
                            )}
                          </div>
                        )}
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
          aria-label="Accounts pages"
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

      <AccountFormDialog
        account={editing === "new" ? undefined : (editing ?? undefined)}
        open={editing !== null}
        onOpenChange={(open) => {
          if (!open) setEditing(null)
        }}
      />
      <DeactivateAccountDialog
        account={deactivating}
        onOpenChange={(open) => {
          if (!open) setDeactivating(null)
        }}
      />
    </div>
  )
}
