import { zodResolver } from "@hookform/resolvers/zod"
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query"
import { Loader2 } from "lucide-react"
import { useEffect, useId } from "react"
import { Controller, useForm } from "react-hook-form"
import { toast } from "sonner"
import type { RoleRead, UserPublic } from "@/client/types.gen"
import { Button } from "@/components/ui/button"
import { Checkbox } from "@/components/ui/checkbox"
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
  describeAccessError,
  GRANT_RULE,
  inviteStaff,
  missingToGrant,
  rolesQuery,
} from "@/data/admin"
import { Field, FormAlert, SkeletonRows } from "@/design/primitives"
import { describeError, refusalCode } from "@/lib/http"
import { cn } from "@/lib/utils"
import { z } from "@/lib/zod"
import { useHeldCodes } from "./held"

// MIRROR: backend/app/modules/users_roles/schemas.py StaffInvite (email and name at most 255, one to
// seven roles). The server validates again and decides; this only saves a round trip.
const schema = z.object({
  email: z.email("Enter a valid email.").max(255),
  full_name: z
    .string()
    .trim()
    .min(1, "Enter the person's name.")
    .max(255, "Use 255 characters or fewer."),
  role_ids: z.array(z.string()).min(1, "Choose at least one role.").max(7),
})
type Values = z.infer<typeof schema>

const EMPTY: Values = { email: "", full_name: "", role_ids: [] }

/**
 * Invite a staff member into the signed-in administrator's own organisation. The administrator
 * picks the roles; roles whose permissions they don't hold are shown but can't be picked (R3, read in
 * advance; the server decides and answers `403 GRANT_EXCEEDS_ACTOR`). No password is set here: the
 * server emails the person a single-use link to choose their own.
 */
export function InviteStaffDialog({
  me,
  open,
  onOpenChange,
}: {
  me: UserPublic
  open: boolean
  onOpenChange: (open: boolean) => void
}) {
  const queryClient = useQueryClient()
  const roles = useQuery({ ...rolesQuery, enabled: open })
  const held = useHeldCodes(me.id)
  const form = useForm<Values>({
    resolver: zodResolver(schema),
    defaultValues: EMPTY,
  })
  const { errors } = form.formState
  const rolesLabelId = useId()

  useEffect(() => {
    if (open) form.reset(EMPTY)
  }, [open, form])

  const invite = useMutation({
    mutationFn: (values: Values) => inviteStaff(values),
    ...ADMIN_WRITE,
    onSuccess: (member) => {
      void queryClient.invalidateQueries({ queryKey: ["admin", "staff"] })
      toast.success(`Invitation sent to ${member.email}`)
      onOpenChange(false)
    },
    onError: (error) => {
      // A taken address belongs to the email field, in the API's terms.
      if (refusalCode(error) === "EMAIL_UNAVAILABLE")
        form.setError("email", {
          message: describeAccessError(error),
        })
    },
  })

  const sorted = [...(roles.data?.data ?? [])].sort((a, b) =>
    a.name.localeCompare(b.name),
  )
  const failure =
    invite.isError && refusalCode(invite.error) !== "EMAIL_UNAVAILABLE"
      ? (describeAccessError(invite.error) ?? describeError(invite.error))
      : null

  return (
    <Dialog
      open={open}
      onOpenChange={(next) => {
        if (invite.isPending) return
        if (!next) invite.reset()
        onOpenChange(next)
      }}
    >
      <DialogContent className="sm:max-w-[540px]">
        <form
          onSubmit={form.handleSubmit((values) => invite.mutate(values))}
          noValidate
          className="grid min-w-0 gap-4"
          aria-label="Invite a staff member"
        >
          <DialogHeader>
            <DialogTitle>Invite a staff member</DialogTitle>
            <DialogDescription>
              They join your organisation with the roles you choose, and get an
              email with a link to set their own password. The link works once.
            </DialogDescription>
          </DialogHeader>

          <div className="grid gap-4">
            <Field
              label="Full name"
              htmlFor="invite-full_name"
              error={errors.full_name?.message}
            >
              <input
                id="invite-full_name"
                className="field-input"
                autoComplete="off"
                aria-invalid={errors.full_name ? "true" : undefined}
                {...form.register("full_name")}
              />
            </Field>
            <Field
              label="Email"
              htmlFor="invite-email"
              error={errors.email?.message}
            >
              <input
                id="invite-email"
                type="email"
                className="field-input"
                autoComplete="off"
                spellCheck={false}
                aria-invalid={errors.email ? "true" : undefined}
                {...form.register("email", {
                  onChange: () => {
                    if (invite.isError) invite.reset()
                  },
                })}
              />
            </Field>
          </div>

          <fieldset aria-labelledby={rolesLabelId} className="min-w-0">
            <legend id={rolesLabelId} className="field-label">
              Roles
            </legend>
            {roles.isError ? (
              <FormAlert>{describeError(roles.error)}</FormAlert>
            ) : !roles.data ? (
              <SkeletonRows rows={3} />
            ) : (
              <Controller
                control={form.control}
                name="role_ids"
                render={({ field }) => (
                  <ul
                    className="grid grid-cols-2 gap-2"
                    data-testid="invite-roles"
                  >
                    {sorted.map((role) => (
                      <RoleOption
                        key={role.id}
                        role={role}
                        missing={missingToGrant(role, held)}
                        checked={field.value.includes(role.id)}
                        onChange={(on) =>
                          field.onChange(
                            on
                              ? [...field.value, role.id]
                              : field.value.filter((id) => id !== role.id),
                          )
                        }
                      />
                    ))}
                  </ul>
                )}
              />
            )}
            {errors.role_ids ? (
              <p className="mt-2 text-xs text-danger" role="alert">
                {errors.role_ids.message}
              </p>
            ) : (
              <p className="mt-2 text-xs text-stone-faint">{GRANT_RULE}</p>
            )}
          </fieldset>

          {failure ? <FormAlert>{failure}</FormAlert> : null}

          <DialogFooter>
            <Button
              type="button"
              variant="outline"
              onClick={() => onOpenChange(false)}
              disabled={invite.isPending}
            >
              Cancel
            </Button>
            <Button type="submit" disabled={invite.isPending}>
              {invite.isPending ? <Loader2 className="animate-spin" /> : null}
              Send invitation
            </Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  )
}

function RoleOption({
  role,
  missing,
  checked,
  onChange,
}: {
  role: RoleRead
  missing: string[] | undefined
  checked: boolean
  onChange: (on: boolean) => void
}) {
  const id = `invite-role-${role.code}`
  const blocked = Boolean(missing?.length)
  const count = role.permissions.length
  return (
    <li className="min-w-0">
      <label
        htmlFor={id}
        title={
          blocked
            ? `It includes ${missing?.join(", ")}, which you don't hold.`
            : undefined
        }
        className={cn(
          "flex h-full items-start gap-3 rounded-inner border px-3 py-2.5 transition-colors",
          blocked
            ? "cursor-not-allowed border-line-faint bg-oat/60"
            : checked
              ? "cursor-pointer border-clay bg-clay-tint/40"
              : "cursor-pointer border-line bg-paper hover:border-stone-faint",
        )}
      >
        <Checkbox
          id={id}
          checked={checked}
          disabled={blocked}
          onCheckedChange={(v) => onChange(v === true)}
          className="mt-0.5 border-stone-faint bg-paper"
        />
        <span className="min-w-0">
          <span
            className={cn(
              "block text-sm font-medium",
              blocked ? "text-stone" : "text-ink",
            )}
          >
            {role.name}
          </span>
          <span className="block text-xs text-stone">
            {blocked
              ? "You can't grant this"
              : count === 1
                ? "1 permission"
                : `${count} permissions`}
          </span>
        </span>
      </label>
    </li>
  )
}
