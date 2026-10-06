import { zodResolver } from "@hookform/resolvers/zod"
import { useMutation, useQueryClient } from "@tanstack/react-query"
import { Loader2 } from "lucide-react"
import { useEffect } from "react"
import { Controller, useForm } from "react-hook-form"
import { toast } from "sonner"
import type { UserPublic, UserUpdate } from "@/client/types.gen"
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
import { createAccount, deactivateAccount, updateAccount } from "@/data/admin"
import { Field, FormAlert } from "@/design/primitives"
import { describeError } from "@/lib/http"
import { z } from "@/lib/zod"

// MIRROR: backend/app/models.py UserCreate / UserUpdate (password 8-128, email and name max 255).
const schema = (creating: boolean) =>
  z
    .object({
      email: z.email("Enter a valid email.").max(255),
      full_name: z.string().trim().max(255),
      password: creating
        ? z
            .string()
            .min(8, "Use at least 8 characters.")
            .max(128, "Use at most 128 characters.")
        : z
            .string()
            .max(128, "Use at most 128 characters.")
            .refine(
              (v) => v === "" || v.length >= 8,
              "Use at least 8 characters.",
            ),
      confirm_password: z.string(),
      is_superuser: z.boolean(),
      is_active: z.boolean(),
    })
    .refine((v) => v.password === v.confirm_password, {
      message: "The passwords don't match.",
      path: ["confirm_password"],
    })
type FormValues = z.infer<ReturnType<typeof schema>>

const toForm = (account?: UserPublic): FormValues => ({
  email: account?.email ?? "",
  full_name: account?.full_name ?? "",
  password: "",
  confirm_password: "",
  is_superuser: account?.is_superuser ?? false,
  is_active: account?.is_active ?? true,
})

/** Add an account, or edit one. Superuser-only on the server (`POST`/`PATCH /users/`). */
export function AccountFormDialog({
  account,
  open,
  onOpenChange,
}: {
  /** Present: edit it. Absent: create a new account. */
  account?: UserPublic
  open: boolean
  onOpenChange: (open: boolean) => void
}) {
  const creating = !account
  const queryClient = useQueryClient()
  const form = useForm<FormValues>({
    resolver: zodResolver(schema(creating)),
    defaultValues: toForm(account),
  })
  const { errors } = form.formState

  useEffect(() => {
    if (open) form.reset(toForm(account))
  }, [open, account, form])

  const save = useMutation({
    mutationFn: async ({ confirm_password: _, ...values }: FormValues) => {
      const full_name = values.full_name || null
      if (creating) return createAccount({ ...values, full_name })
      const body: UserUpdate = { ...values, full_name }
      if (!values.password) delete body.password
      return updateAccount(account.id, body)
    },
    onSuccess: async (saved) => {
      await queryClient.invalidateQueries({ queryKey: ["admin", "accounts"] })
      toast.success(creating ? `${saved.email} added` : "Account saved")
      onOpenChange(false)
    },
  })

  const input = (
    name: "email" | "full_name" | "password" | "confirm_password",
    props: React.InputHTMLAttributes<HTMLInputElement> = {},
  ) => (
    <input
      id={`acct-${name}`}
      className="field-input"
      aria-invalid={errors[name] ? "true" : undefined}
      {...props}
      {...form.register(name)}
    />
  )

  const toggle = (
    name: "is_superuser" | "is_active",
    label: string,
    hint: string,
  ) => (
    <Controller
      control={form.control}
      name={name}
      render={({ field }) => (
        <div className="flex items-start gap-2.5">
          <Checkbox
            id={`acct-${name}`}
            checked={field.value}
            onCheckedChange={(v) => field.onChange(v === true)}
            className="mt-0.5 border-stone-faint bg-paper"
          />
          <label htmlFor={`acct-${name}`} className="text-sm">
            <span className="font-medium">{label}</span>
            <span className="block text-xs text-stone">{hint}</span>
          </label>
        </div>
      )}
    />
  )

  return (
    <Dialog
      open={open}
      onOpenChange={(next) => {
        if (save.isPending) return
        if (!next) save.reset()
        onOpenChange(next)
      }}
    >
      <DialogContent className="sm:max-w-[520px]">
        <form
          onSubmit={form.handleSubmit((v) => save.mutate(v))}
          noValidate
          className="grid gap-4"
        >
          <DialogHeader>
            <DialogTitle>
              {creating ? "Add an account" : "Edit account"}
            </DialogTitle>
            <DialogDescription>
              {creating
                ? "The account is created without an organisation or roles."
                : "Leave the password blank to keep the current one."}
            </DialogDescription>
          </DialogHeader>

          <div className="grid gap-4 sm:grid-cols-2">
            <Field
              label="Email"
              htmlFor="acct-email"
              error={errors.email?.message}
              className="sm:col-span-2"
            >
              {input("email", {
                type: "email",
                autoComplete: "off",
                autoFocus: true,
              })}
            </Field>
            <Field
              label="Full name"
              htmlFor="acct-full_name"
              error={errors.full_name?.message}
              hint="Optional"
              className="sm:col-span-2"
            >
              {input("full_name", { autoComplete: "off" })}
            </Field>
            <Field
              label={creating ? "Password" : "New password"}
              htmlFor="acct-password"
              error={errors.password?.message}
              hint={creating ? "At least 8 characters" : "Optional"}
            >
              {input("password", {
                type: "password",
                autoComplete: "new-password",
              })}
            </Field>
            <Field
              label="Confirm password"
              htmlFor="acct-confirm_password"
              error={errors.confirm_password?.message}
            >
              {input("confirm_password", {
                type: "password",
                autoComplete: "new-password",
              })}
            </Field>
          </div>

          <div className="grid gap-3 rounded-inner border border-line bg-oat/50 px-4 py-3.5">
            {toggle(
              "is_active",
              "Active",
              "An inactive account can't sign in.",
            )}
            {toggle(
              "is_superuser",
              "Superuser",
              "Platform administration across every organisation.",
            )}
          </div>

          {save.isError ? (
            <FormAlert>{describeError(save.error)}</FormAlert>
          ) : null}

          <DialogFooter>
            <Button
              type="button"
              variant="outline"
              onClick={() => onOpenChange(false)}
              disabled={save.isPending}
            >
              Cancel
            </Button>
            <Button type="submit" disabled={save.isPending}>
              {save.isPending ? <Loader2 className="animate-spin" /> : null}
              {creating ? "Add account" : "Save changes"}
            </Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  )
}

/** Deactivate (never delete) an account: it keeps its history and can't sign in. */
export function DeactivateAccountDialog({
  account,
  onOpenChange,
}: {
  account: UserPublic | null
  onOpenChange: (open: boolean) => void
}) {
  const queryClient = useQueryClient()
  const deactivate = useMutation({
    mutationFn: () => deactivateAccount(account!.id),
    onSuccess: async () => {
      await queryClient.invalidateQueries({ queryKey: ["admin", "accounts"] })
      toast.success(`${account!.email} deactivated`)
      onOpenChange(false)
    },
  })

  return (
    <Dialog
      open={account !== null}
      onOpenChange={(open) => {
        if (deactivate.isPending) return
        if (!open) deactivate.reset()
        onOpenChange(open)
      }}
    >
      <DialogContent>
        {account ? (
          <div className="grid gap-4">
            <DialogHeader>
              <DialogTitle>Deactivate this account?</DialogTitle>
              <DialogDescription>
                <span className="font-medium text-ink">{account.email}</span> is
                signed out and can no longer sign in. The account, its roles and
                its history are kept, and it can be reactivated from Edit.
              </DialogDescription>
            </DialogHeader>
            {deactivate.isError ? (
              <FormAlert>{describeError(deactivate.error)}</FormAlert>
            ) : null}
            <DialogFooter>
              <Button
                type="button"
                variant="outline"
                onClick={() => onOpenChange(false)}
                disabled={deactivate.isPending}
              >
                Cancel
              </Button>
              <Button
                variant="destructive"
                disabled={deactivate.isPending}
                onClick={() => deactivate.mutate()}
              >
                {deactivate.isPending ? (
                  <Loader2 className="animate-spin" />
                ) : null}
                Deactivate
              </Button>
            </DialogFooter>
          </div>
        ) : null}
      </DialogContent>
    </Dialog>
  )
}
