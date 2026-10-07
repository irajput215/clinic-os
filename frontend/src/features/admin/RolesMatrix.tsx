import { useQuery } from "@tanstack/react-query"
import { Check } from "lucide-react"
import { Fragment } from "react"
import {
  formatList,
  GRANT_RULE,
  groupPermissions,
  missingToGrant,
  permissionCatalogueQuery,
  rolesQuery,
} from "@/data/admin"
import {
  Card,
  EmptyState,
  ErrorState,
  Mono,
  Pill,
  SkeletonRows,
} from "@/design/primitives"
import { currentUserQuery } from "@/lib/session"
import { useHeldCodes } from "./held"

/**
 * The permission catalogue as a roles x permissions matrix. Rows are the global catalogue
 * (`GET /permissions`, read-only reference data); columns are this organisation's roles
 * (`GET /roles`). Nothing here is editable: a role is a fixed bundle of codes.
 */
export function RolesMatrix() {
  const roles = useQuery(rolesQuery)
  const catalogue = useQuery(permissionCatalogueQuery)
  const me = useQuery(currentUserQuery)
  const held = useHeldCodes(me.data?.id ?? "")

  const failed = roles.error ?? catalogue.error
  if (failed)
    return (
      <ErrorState
        error={failed}
        onRetry={() => {
          void roles.refetch()
          void catalogue.refetch()
        }}
      />
    )

  if (!roles.data || !catalogue.data)
    return (
      <Card>
        <SkeletonRows rows={8} />
      </Card>
    )

  if (roles.data.data.length === 0 || catalogue.data.data.length === 0)
    return (
      <Card>
        <EmptyState
          title={
            roles.data.data.length === 0
              ? "This organisation has no roles yet."
              : "The permission catalogue is empty."
          }
          body="Roles and the catalogue are created by the server when an organisation is registered. Contact support if this persists."
        />
      </Card>
    )

  const roleList = roles.data.data
  const groups = groupPermissions(catalogue.data.data)
  const columns = roleList.map((role) => ({
    role,
    codes: new Set(role.permissions.map((p) => p.code)),
    missing: missingToGrant(role, held),
  }))
  const ungrantable = columns.filter((c) => c.missing && c.missing.length > 0)

  return (
    <div className="space-y-4">
      <p className="max-w-[720px] text-sm text-stone">
        {catalogue.data.count} permissions across {roleList.length} roles. A
        role is a fixed bundle of permissions; an account holds the union of its
        roles. {GRANT_RULE}
      </p>

      <Card bodyClassName="-mx-5 -my-[18px]">
        <div className="relative overflow-x-auto rounded-card">
          <table className="data-table" data-testid="permission-matrix">
            <caption className="sr-only">
              Which permissions each role includes
            </caption>
            <thead>
              <tr>
                <th
                  scope="col"
                  className="sticky left-0 z-10 min-w-[180px] pl-5 sm:min-w-[240px]"
                >
                  Permission
                </th>
                {columns.map(({ role }) => (
                  <th
                    key={role.id}
                    scope="col"
                    data-testid={`role-${role.code}`}
                    className="px-2.5 text-center align-bottom normal-case last:pr-5"
                  >
                    <span className="block text-[12.5px] font-semibold tracking-normal whitespace-nowrap text-ink">
                      {role.name}
                    </span>
                    <span className="mt-0.5 block font-mono text-[10.5px] font-normal tracking-normal text-stone-faint">
                      {role.permissions.length} of {catalogue.data.count}
                    </span>
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {groups.map((group) => (
                <Fragment key={group.id}>
                  <tr>
                    <th
                      scope="colgroup"
                      colSpan={columns.length + 1}
                      className="sticky left-0 border-line-faint border-t bg-oat/50 pt-3.5 pb-1.5 pl-5 text-left"
                    >
                      {group.title}
                    </th>
                  </tr>
                  {group.permissions.map((permission) => (
                    <tr
                      key={permission.code}
                      data-testid={`perm-${permission.code}`}
                    >
                      <th
                        scope="row"
                        className="sticky left-0 z-10 border-line-faint border-t bg-paper py-2.5 pl-5 text-left font-normal tracking-normal normal-case"
                      >
                        <Mono className="text-[12px] text-ink">
                          {permission.code}
                        </Mono>
                        <span className="mt-0.5 block text-xs text-stone">
                          {permission.description}
                        </span>
                      </th>
                      {columns.map(({ role, codes }) => (
                        <td
                          key={role.id}
                          className="px-2.5 text-center last:pr-5"
                        >
                          {codes.has(permission.code) ? (
                            <>
                              <Check
                                aria-hidden
                                className="mx-auto size-4 text-ok"
                                strokeWidth={2.4}
                              />
                              <span className="sr-only">
                                {role.name} includes {permission.code}
                              </span>
                            </>
                          ) : (
                            <>
                              <span aria-hidden className="text-stone-faint">
                                -
                              </span>
                              <span className="sr-only">
                                {role.name} does not include {permission.code}
                              </span>
                            </>
                          )}
                        </td>
                      ))}
                    </tr>
                  ))}
                </Fragment>
              ))}
            </tbody>
            <tfoot>
              <tr>
                <th
                  scope="row"
                  className="sticky left-0 z-10 border-line border-t bg-oat py-3 pl-5 text-left"
                >
                  You can grant
                </th>
                {columns.map(({ role, missing }) => (
                  <td
                    key={role.id}
                    className="border-line border-t bg-oat px-2.5 py-3 text-center last:pr-5"
                    data-testid={`grant-${role.code}`}
                  >
                    {missing === undefined ? (
                      <Pill title="Your own permissions could not be read">
                        Unknown
                      </Pill>
                    ) : missing.length === 0 ? (
                      <Pill tone="ok">Yes</Pill>
                    ) : (
                      <Pill
                        tone="warn"
                        title={`Missing: ${formatList(missing)}`}
                      >
                        No
                      </Pill>
                    )}
                  </td>
                ))}
              </tr>
            </tfoot>
          </table>
        </div>
      </Card>

      {ungrantable.length > 0 ? (
        <Card title="Roles you can't grant">
          <p className="mb-3 text-sm text-stone">
            {GRANT_RULE} The server refuses any grant that would give someone
            more than you hold.
          </p>
          <ul className="space-y-2 text-sm" data-testid="ungrantable-roles">
            {ungrantable.map(({ role, missing }) => (
              <li key={role.id}>
                <span className="font-semibold">{role.name}</span>
                <span className="text-stone">: you don't hold </span>
                <span className="break-words">
                  {missing?.map((code, i) => (
                    <Fragment key={code}>
                      {i > 0 ? ", " : null}
                      <Mono className="text-[12px]">{code}</Mono>
                    </Fragment>
                  ))}
                </span>
              </li>
            ))}
          </ul>
        </Card>
      ) : null}
    </div>
  )
}
