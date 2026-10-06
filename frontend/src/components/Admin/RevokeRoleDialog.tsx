/**
 * Confirm and perform a real revocation (`DELETE /users/{id}/roles/{role_id}`).
 *
 * The delete is hard on the API side — the append-only audit trail is the history — so the
 * dialog says what will happen. A refusal is shown in the dialog rather than as a toast, so
 * a `403` reads as "you do not have permission", not as a generic failure.
 */

import { useMutation, useQueryClient } from "@tanstack/react-query"
import { useState } from "react"

import { type UserRoleRead, UsersService } from "@/client"
import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert"
import { Button } from "@/components/ui/button"
import {
  Dialog,
  DialogClose,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
  DialogTrigger,
} from "@/components/ui/dialog"
import { LoadingButton } from "@/components/ui/loading-button"
import useCustomToast from "@/hooks/useCustomToast"
import { isForbidden, retryDelayMs, retryOnRateLimit } from "@/lib/admin"
import { apiErrorCode, httpStatus } from "@/lib/http"

export function RevokeRoleDialog({
  userId,
  assignment,
}: {
  userId: string
  assignment: UserRoleRead
}) {
  const [isOpen, setIsOpen] = useState(false)
  const [errorMessage, setErrorMessage] = useState<string | null>(null)
  const queryClient = useQueryClient()
  const { showSuccessToast } = useCustomToast()

  const mutation = useMutation({
    mutationFn: () =>
      UsersService.revokeRole({
        path: { user_id: userId, role_id: assignment.role_id },
      }),
    retry: retryOnRateLimit,
    retryDelay: retryDelayMs,
    onSuccess: () => {
      showSuccessToast(`${assignment.name} revoked`)
      setIsOpen(false)
      setErrorMessage(null)
      queryClient.invalidateQueries({
        queryKey: ["admin", "user-roles", userId],
      })
      queryClient.invalidateQueries({
        queryKey: ["admin", "user-permissions", userId],
      })
    },
    onError: (error) => {
      if (apiErrorCode(error) === "LAST_ADMINISTRATOR") {
        // R8. Nothing was removed, and the API's own sentence is the accurate one: say it
        // rather than a generic failure, and leave the list as it is.
        setErrorMessage(
          "This is the organisation's last account that can manage users. Assign another administrator before revoking this role.",
        )
        return
      }
      if (isForbidden(error)) {
        setErrorMessage(
          "You do not have permission to revoke roles in this organisation.",
        )
        return
      }
      if (httpStatus(error) === 404) {
        // The assignment is already gone — another administrator, or a stale list. Show
        // what happened and let the list catch up rather than pretending the click failed.
        queryClient.invalidateQueries({
          queryKey: ["admin", "user-roles", userId],
        })
        queryClient.invalidateQueries({
          queryKey: ["admin", "user-permissions", userId],
        })
        setErrorMessage(
          "This role is no longer assigned to the account. The list has been refreshed.",
        )
        return
      }
      setErrorMessage("The role could not be revoked. Try again.")
    },
  })

  const onOpenChange = (open: boolean) => {
    if (mutation.isPending) return
    setIsOpen(open)
    if (!open) setErrorMessage(null)
  }

  return (
    <Dialog open={isOpen} onOpenChange={onOpenChange}>
      <DialogTrigger asChild>
        <Button
          variant="outline"
          size="sm"
          aria-label={`Revoke ${assignment.name}`}
          data-testid={`revoke-role-${assignment.code}`}
        >
          Revoke
        </Button>
      </DialogTrigger>
      <DialogContent className="sm:max-w-md">
        <DialogHeader>
          <DialogTitle>Revoke {assignment.name}?</DialogTitle>
          <DialogDescription>
            The account loses every permission this role carries. Revocation is
            recorded; the role can be assigned again later.
          </DialogDescription>
        </DialogHeader>

        {errorMessage ? (
          <Alert variant="destructive" data-testid="revoke-error">
            <AlertTitle>We couldn't revoke this role</AlertTitle>
            <AlertDescription>{errorMessage}</AlertDescription>
          </Alert>
        ) : null}

        <DialogFooter>
          <DialogClose asChild>
            <Button variant="outline" disabled={mutation.isPending}>
              Cancel
            </Button>
          </DialogClose>
          <LoadingButton
            variant="destructive"
            loading={mutation.isPending}
            onClick={() => mutation.mutate()}
            data-testid="confirm-revoke-role"
          >
            Revoke role
          </LoadingButton>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}

export default RevokeRoleDialog
