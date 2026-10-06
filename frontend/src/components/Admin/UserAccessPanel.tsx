/**
 * One account's access: the roles it holds, its server-computed effective permission set,
 * and the two real operations on that access — assign a role, revoke one.
 *
 * ## Why an account ID and not a picker
 *
 * The tenant-scoped user directory (`GET /users`, cursor-paginated) is part of the
 * users-and-roles design but not of this release: the user-lifecycle routes are T1-03,
 * blocked by D-003. The legacy `GET /users/` template route is superuser-only and returns
 * every tenant's users, so this screen does not use it. That leaves the six administration
 * endpoints, which address one account by `user_id` — so the screen starts on the signed-in
 * account and takes an ID for any other. The awkwardness is the API's, and it is reported
 * rather than hidden.
 *
 * ## R3
 *
 * Assignment is a real `POST`, and the API enforces the grantability rule: a role whose
 * bundle contains a permission the caller does not hold is refused `403
 * GRANT_EXCEEDS_ACTOR`. This panel shows which roles are grantable (read from the caller's
 * own effective permissions) and what is missing, and it never translates the refusal into
 * a generic failure. The grant control stays available for a non-grantable role because the
 * backend is the only decision point (INV-3); the warning and the refusal are the point of
 * the screen.
 */

import { zodResolver } from "@hookform/resolvers/zod"
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query"
import { AlertTriangle, SearchX, ShieldAlert } from "lucide-react"
import { type ReactNode, useMemo, useState } from "react"
import { useForm } from "react-hook-form"
import { z } from "zod"

import { UsersService } from "@/client"
import {
  AccessDenied,
  AdminError,
  AdminLoading,
} from "@/components/Admin/AdminStates"
import RevokeRoleDialog from "@/components/Admin/RevokeRoleDialog"
import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card"
import {
  Form,
  FormControl,
  FormField,
  FormItem,
  FormLabel,
  FormMessage,
} from "@/components/ui/form"
import { Input } from "@/components/ui/input"
import { LoadingButton } from "@/components/ui/loading-button"
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select"
import useCustomToast from "@/hooks/useCustomToast"
import {
  describeAdminError,
  formatCodeList,
  GRANTABILITY_EXPLANATION,
  isForbidden,
  isGrantExceedsActor,
  retryDelayMs,
  retryOnRateLimit,
  roleGrantability,
} from "@/lib/admin"
import { formatTimestamp } from "@/lib/date"
import { apiErrorMessage, isNotFound } from "@/lib/http"
import {
  rolesQueryOptions,
  selfPermissionsQueryOptions,
  userPermissionsQueryOptions,
  userRolesQueryOptions,
} from "./adminQueries"

const lookupSchema = z.object({
  user_id: z.uuid({ message: "Enter a valid account ID" }),
})

type LookupValues = z.infer<typeof lookupSchema>

const assignSchema = z.object({
  role_id: z.string().min(1, { message: "Choose a role" }),
})

type AssignValues = z.infer<typeof assignSchema>

type AssignRefusal = {
  explanation: string
  missing: string[]
}

function AccountNotFound() {
  return (
    <Card data-testid="account-not-found">
      <CardContent className="flex flex-col items-center gap-4 py-12 text-center">
        <div className="rounded-full bg-muted p-3">
          <SearchX
            className="size-6 text-muted-foreground"
            aria-hidden="true"
          />
        </div>
        <div className="flex max-w-xl flex-col gap-1">
          <p className="font-medium">Account not found</p>
          <p className="text-sm text-muted-foreground">
            There is no account with this ID in your organisation. The API
            answers the same way for an account that does not exist and for one
            belonging to another organisation.
          </p>
        </div>
      </CardContent>
    </Card>
  )
}

export function UserAccessPanel({ currentUserId }: { currentUserId: string }) {
  const [accountId, setAccountId] = useState(currentUserId)
  const [refusal, setRefusal] = useState<AssignRefusal | null>(null)
  const queryClient = useQueryClient()
  const { showSuccessToast } = useCustomToast()

  const roles = useQuery(rolesQueryOptions)
  const held = useQuery(selfPermissionsQueryOptions(currentUserId))
  const assignments = useQuery(userRolesQueryOptions(accountId))
  const effective = useQuery(userPermissionsQueryOptions(accountId))

  const heldCodes = useMemo(() => {
    if (!held.data) return undefined
    return new Set(held.data.permissions.map((permission) => permission.code))
  }, [held.data])

  const grantabilityByRole = useMemo(() => {
    const map = new Map<string, ReturnType<typeof roleGrantability>>()
    for (const role of roles.data?.data ?? []) {
      map.set(role.id, roleGrantability(role, heldCodes))
    }
    return map
  }, [roles.data, heldCodes])

  const lookupForm = useForm<LookupValues>({
    resolver: zodResolver(lookupSchema),
    mode: "onSubmit",
    defaultValues: { user_id: currentUserId },
  })

  const assignForm = useForm<AssignValues>({
    resolver: zodResolver(assignSchema),
    mode: "onSubmit",
    defaultValues: { role_id: "" },
  })

  const assign = useMutation({
    mutationFn: (roleId: string) =>
      UsersService.assignRole({
        path: { user_id: accountId },
        body: { role_id: roleId },
      }),
    retry: retryOnRateLimit,
    retryDelay: retryDelayMs,
    onSuccess: () => {
      showSuccessToast("Role assigned")
      assignForm.reset({ role_id: "" })
      setRefusal(null)
      queryClient.invalidateQueries({
        queryKey: ["admin", "user-roles", accountId],
      })
      queryClient.invalidateQueries({
        queryKey: ["admin", "user-permissions", accountId],
      })
    },
    onError: (error, roleId) => {
      if (isGrantExceedsActor(error)) {
        // The API refused the bundle because it confers a permission the actor does not
        // hold (R3). Say exactly that, and name what is missing where it can be read.
        setRefusal({
          explanation: GRANTABILITY_EXPLANATION,
          missing: grantabilityByRole.get(roleId)?.missing ?? [],
        })
        return
      }
      if (isForbidden(error)) {
        setRefusal({
          explanation:
            "You do not have permission to assign roles in this organisation.",
          missing: [],
        })
        return
      }
      setRefusal({
        explanation:
          apiErrorMessage(error) ??
          "The role could not be assigned. Try again.",
        missing: [],
      })
    },
  })

  const selectedRoleId = assignForm.watch("role_id")
  const selectedGrantability = selectedRoleId
    ? grantabilityByRole.get(selectedRoleId)
    : undefined

  const onLookup = (values: LookupValues) => {
    setAccountId(values.user_id.trim())
    setRefusal(null)
    assignForm.reset({ role_id: "" })
  }

  const onUseMyAccount = () => {
    lookupForm.setValue("user_id", currentUserId)
    setAccountId(currentUserId)
    setRefusal(null)
    assignForm.reset({ role_id: "" })
  }

  const onAssign = (values: AssignValues) => {
    if (assign.isPending) return
    setRefusal(null)
    assign.mutate(values.role_id)
  }

  const lookupCard = (
    <Card>
      <CardHeader>
        <CardTitle className="text-base">Account</CardTitle>
        <CardDescription>
          Look up an account by its user ID. This release has no organisation
          user directory, so the screen starts on your own account and takes an
          ID for another.
        </CardDescription>
      </CardHeader>
      <CardContent>
        <Form {...lookupForm}>
          <form
            noValidate
            onSubmit={lookupForm.handleSubmit(onLookup)}
            className="flex flex-col gap-3 sm:flex-row sm:items-start"
          >
            <FormField
              control={lookupForm.control}
              name="user_id"
              render={({ field }) => (
                <FormItem className="flex-1">
                  <FormLabel>Account ID</FormLabel>
                  <FormControl>
                    <Input
                      {...field}
                      placeholder="00000000-0000-0000-0000-000000000000"
                      className="font-mono"
                      autoComplete="off"
                      spellCheck={false}
                      data-testid="account-id-input"
                    />
                  </FormControl>
                  <FormMessage />
                </FormItem>
              )}
            />
            <div className="flex gap-2 pt-0 sm:pt-7">
              <Button
                type="submit"
                variant="outline"
                disabled={assign.isPending}
                data-testid="lookup-account"
              >
                View access
              </Button>
              <Button
                type="button"
                variant="ghost"
                onClick={onUseMyAccount}
                disabled={assign.isPending}
              >
                Use my account
              </Button>
            </div>
          </form>
        </Form>
      </CardContent>
    </Card>
  )

  const forbidden = [roles, held, assignments, effective].some((query) =>
    isForbidden(query.error),
  )
  const accountMissing =
    (assignments.isError && isNotFound(assignments.error)) ||
    (effective.isError && isNotFound(effective.error))

  const failed = assignments.isError || effective.isError || roles.isError

  let body: ReactNode
  if (forbidden) {
    body = <AccessDenied />
  } else if (accountMissing) {
    body = <AccountNotFound />
  } else if (assignments.isPending || effective.isPending || roles.isPending) {
    body = <AdminLoading label="Loading this account's access" />
  } else if (failed) {
    body = (
      <AdminError
        title="We couldn't load this account's access"
        description={describeAdminError(
          assignments.error ?? effective.error ?? roles.error,
        )}
        onRetry={() => {
          assignments.refetch()
          effective.refetch()
          roles.refetch()
        }}
        retrying={
          assignments.isFetching || effective.isFetching || roles.isFetching
        }
      />
    )
  } else {
    body = (
      <div className="flex flex-col gap-6">
        <Card>
          <CardHeader>
            <CardTitle className="text-base">Assigned roles</CardTitle>
            <CardDescription>
              {assignments.data.count === 1
                ? "1 role held by this account."
                : `${assignments.data.count} roles held by this account.`}
            </CardDescription>
          </CardHeader>
          <CardContent>
            {assignments.data.data.length === 0 ? (
              <p
                className="text-sm text-muted-foreground"
                data-testid="user-roles-empty"
              >
                This account holds no roles, so it has no permissions at all.
                Assign one below to give it access.
              </p>
            ) : (
              <ul className="flex flex-col gap-2" data-testid="user-roles">
                {assignments.data.data.map((assignment) => (
                  <li
                    key={assignment.role_id}
                    className="flex flex-wrap items-center justify-between gap-3 rounded-md border p-3"
                  >
                    <div className="flex flex-col gap-1">
                      <div className="flex flex-wrap items-center gap-2">
                        <span className="font-medium">{assignment.name}</span>
                        <Badge variant="outline" className="font-mono text-xs">
                          {assignment.code}
                        </Badge>
                        {assignment.is_system ? (
                          <Badge variant="secondary" className="text-xs">
                            System role
                          </Badge>
                        ) : null}
                      </div>
                      <span className="text-xs text-muted-foreground">
                        Granted {formatTimestamp(assignment.granted_at)}
                      </span>
                    </div>
                    <RevokeRoleDialog
                      userId={accountId}
                      assignment={assignment}
                    />
                  </li>
                ))}
              </ul>
            )}
          </CardContent>
        </Card>

        <Card>
          <CardHeader>
            <CardTitle className="text-base">Effective permissions</CardTitle>
            <CardDescription>
              Computed by the API as the union of this account's role bundles.{" "}
              {effective.data.count === 1
                ? "1 permission"
                : `${effective.data.count} permissions`}
              .
            </CardDescription>
          </CardHeader>
          <CardContent>
            {effective.data.permissions.length === 0 ? (
              <p
                className="text-sm text-muted-foreground"
                data-testid="effective-permissions-empty"
              >
                This account has no effective permissions.
              </p>
            ) : (
              <ul
                className="flex flex-wrap gap-1.5"
                data-testid="effective-permissions"
              >
                {effective.data.permissions.map((permission) => (
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
            )}
          </CardContent>
        </Card>

        <Card>
          <CardHeader>
            <CardTitle className="text-base">Assign a role</CardTitle>
            <CardDescription>
              You can grant only roles whose permissions you hold. Your role
              does not include the permissions in a role you cannot grant.
            </CardDescription>
          </CardHeader>
          <CardContent>
            <Form {...assignForm}>
              <form
                noValidate
                onSubmit={assignForm.handleSubmit(onAssign)}
                className="flex flex-col gap-4"
              >
                <FormField
                  control={assignForm.control}
                  name="role_id"
                  render={({ field }) => (
                    <FormItem className="max-w-xl">
                      <FormLabel>Role</FormLabel>
                      <Select
                        value={field.value}
                        onValueChange={field.onChange}
                      >
                        <FormControl>
                          <SelectTrigger
                            className="w-full"
                            data-testid="assign-role-select"
                          >
                            <SelectValue placeholder="Choose a role" />
                          </SelectTrigger>
                        </FormControl>
                        <SelectContent>
                          {roles.data.data.map((role) => {
                            const grantability = grantabilityByRole.get(role.id)
                            const suffix =
                              grantability && !grantability.grantable
                                ? " — you cannot grant this"
                                : ""
                            return (
                              <SelectItem key={role.id} value={role.id}>
                                {`${role.code} — ${role.name}${suffix}`}
                              </SelectItem>
                            )
                          })}
                        </SelectContent>
                      </Select>
                      <FormMessage />
                    </FormItem>
                  )}
                />

                {selectedGrantability && !selectedGrantability.grantable ? (
                  <Alert
                    variant="destructive"
                    data-testid="assign-presubmit-warning"
                  >
                    <AlertTriangle aria-hidden="true" />
                    <AlertTitle>
                      You cannot grant this role with your own permissions
                    </AlertTitle>
                    <AlertDescription>
                      {GRANTABILITY_EXPLANATION} Missing from your permissions:{" "}
                      <span className="font-mono">
                        {formatCodeList(selectedGrantability.missing)}
                      </span>
                      . The API enforces this rule and will refuse the grant.
                    </AlertDescription>
                  </Alert>
                ) : null}

                {refusal ? (
                  <Alert variant="destructive" data-testid="assign-refused">
                    <ShieldAlert aria-hidden="true" />
                    <AlertTitle>We couldn't assign this role</AlertTitle>
                    <AlertDescription>
                      {refusal.explanation}
                      {refusal.missing.length > 0 ? (
                        <>
                          {" "}
                          Missing from your permissions:{" "}
                          <span className="font-mono">
                            {formatCodeList(refusal.missing)}
                          </span>
                          .
                        </>
                      ) : null}
                    </AlertDescription>
                  </Alert>
                ) : null}

                <div>
                  <LoadingButton
                    type="submit"
                    loading={assign.isPending}
                    data-testid="assign-role-submit"
                  >
                    Grant role
                  </LoadingButton>
                </div>
              </form>
            </Form>
          </CardContent>
        </Card>
      </div>
    )
  }

  return (
    <div className="flex flex-col gap-6" data-testid="user-access-panel">
      {lookupCard}
      {body}
    </div>
  )
}

export default UserAccessPanel
