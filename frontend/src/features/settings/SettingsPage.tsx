import { zodResolver } from "@hookform/resolvers/zod"
import {
  useMutation,
  useQueryClient,
  useSuspenseQuery,
} from "@tanstack/react-query"
import { useNavigate } from "@tanstack/react-router"
import { Copy, Loader2 } from "lucide-react"
import { useEffect, useState } from "react"
import { useForm } from "react-hook-form"
import { toast } from "sonner"
import type { UserPublic } from "@/client/types.gen"
import { Button } from "@/components/ui/button"
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog"
import { changePassword, deactivateMe, updateMe } from "@/data/account"
import {
  Card,
  Field,
  FormAlert,
  Mono,
  PageHeader,
  Pill,
  TabBar,
} from "@/design/primitives"
import { focusFirstError } from "@/lib/form"
import { describeError } from "@/lib/http"
import { currentUserQuery, signOut } from "@/lib/session"
import { z } from "@/lib/zod"
import { SETTINGS_TAB_KEYS, SETTINGS_TABS, type SettingsTab } from "./tabs"

export function SettingsPage({ tab }: { tab: SettingsTab }) {
  const navigate = useNavigate()
  const { data: me } = useSuspenseQuery(currentUserQuery)

  return (
    <>
      <PageHeader
        title="Settings"
        subtitle="Your own account: how you appear, how you sign in. Changes here apply only to you."
      />
      <TabBar
        label="Settings"
        tabs={SETTINGS_TAB_KEYS.map((key) => ({
          key,
          label: SETTINGS_TABS[key],
        }))}
        value={tab}
        onSelect={(key) =>
          navigate({ to: ".", search: { tab: key }, replace: true })
        }
      />
      <div className="max-w-[640px]">
        {tab === "profile" ? <ProfileTab me={me} /> : null}
        {tab === "password" ? <PasswordTab /> : null}
        {tab === "account" ? <AccountTab me={me} /> : null}
      </div>
    </>
  )
}

// MIRROR: backend/app/models.py UserUpdateMe (both max 255).
const profileSchema = z.object({
  full_name: z.string().trim().max(255, "Use at most 255 characters."),
  email: z.email("Enter a valid email.").max(255),
})
type ProfileValues = z.infer<typeof profileSchema>

function ProfileTab({ me }: { me: UserPublic }) {
  const queryClient = useQueryClient()
  const defaults = { full_name: me.full_name ?? "", email: me.email }
  const form = useForm<ProfileValues>({
    shouldFocusError: false,
    resolver: zodResolver(profileSchema),
    defaultValues: defaults,
  })
  const { errors, isDirty } = form.formState

  const save = useMutation({
    mutationFn: (values: ProfileValues) =>
      updateMe({
        // Only what changed, so an unchanged email is never re-checked for uniqueness.
        ...(values.full_name !== (me.full_name ?? "")
          ? { full_name: values.full_name || null }
          : {}),
        ...(values.email !== me.email ? { email: values.email } : {}),
      }),
    onSuccess: (saved) => {
      queryClient.setQueryData(currentUserQuery.queryKey, saved)
      form.reset({ full_name: saved.full_name ?? "", email: saved.email })
      toast.success("Profile saved")
    },
  })

  const copyId = async () => {
    try {
      await navigator.clipboard.writeText(me.id)
      toast.success("Account ID copied")
    } catch {
      toast.error("Couldn't copy. Select the ID and copy it instead.")
    }
  }

  return (
    <div className="space-y-5">
      <Card title="Profile">
        <form
          onSubmit={form.handleSubmit((v) => save.mutate(v), focusFirstError)}
          noValidate
          className="grid gap-4"
        >
          <Field
            label="Full name"
            htmlFor="me-full_name"
            error={errors.full_name?.message}
            hint="How your name appears across Clinic OS."
          >
            <input
              id="me-full_name"
              className="field-input"
              autoComplete="name"
              aria-invalid={errors.full_name ? "true" : undefined}
              {...form.register("full_name")}
            />
          </Field>
          <Field
            label="Email"
            htmlFor="me-email"
            error={errors.email?.message}
            hint="You sign in with this address."
          >
            <input
              id="me-email"
              type="email"
              className="field-input"
              autoComplete="email"
              aria-invalid={errors.email ? "true" : undefined}
              {...form.register("email")}
            />
          </Field>
          {save.isError ? (
            <FormAlert>{describeError(save.error)}</FormAlert>
          ) : null}
          <div className="flex gap-2">
            <Button type="submit" disabled={!isDirty || save.isPending}>
              {save.isPending ? <Loader2 className="animate-spin" /> : null}
              Save profile
            </Button>
            {isDirty ? (
              <Button
                type="button"
                variant="outline"
                disabled={save.isPending}
                onClick={() => {
                  save.reset()
                  form.reset(defaults)
                }}
              >
                Discard
              </Button>
            ) : null}
          </div>
        </form>
      </Card>

      <Card title="Account details">
        <dl className="grid gap-x-3 gap-y-1 text-sm sm:grid-cols-[160px_minmax(0,1fr)] sm:gap-y-3">
          <dt className="field-label mt-3 mb-0 self-center first:mt-0 sm:mt-0">
            Account ID
          </dt>
          <dd className="flex min-w-0 items-center gap-2">
            <Mono className="truncate">{me.id}</Mono>
            <Button
              size="icon-sm"
              variant="ghost"
              aria-label="Copy account ID"
              title="Copy"
              onClick={copyId}
            >
              <Copy />
            </Button>
          </dd>
          <dt className="field-label mt-3 mb-0 self-center first:mt-0 sm:mt-0">
            Type
          </dt>
          <dd>
            {me.is_superuser ? (
              <Pill tone="purple">Superuser</Pill>
            ) : (
              <Pill>Staff</Pill>
            )}
          </dd>
          <dt className="field-label mt-3 mb-0 self-center first:mt-0 sm:mt-0">
            Organisation
          </dt>
          <dd>
            {me.tenant_id ? (
              <Mono className="truncate text-stone">{me.tenant_id}</Mono>
            ) : (
              <span className="text-stone">None</span>
            )}
          </dd>
        </dl>
        <p className="mt-4 text-xs text-stone">
          An administrator uses your account ID to grant or revoke your roles.
        </p>
      </Card>
    </div>
  )
}

// MIRROR: backend/app/models.py UpdatePassword (8-128 characters).
const passwordSchema = z
  .object({
    current_password: z.string().min(1, "Enter your current password."),
    new_password: z
      .string()
      .min(8, "Use at least 8 characters.")
      .max(128, "Use at most 128 characters."),
    confirm_password: z.string(),
  })
  .refine((v) => v.new_password === v.confirm_password, {
    message: "The passwords don't match.",
    path: ["confirm_password"],
  })
  .refine((v) => v.new_password !== v.current_password, {
    message: "Choose a password different from your current one.",
    path: ["new_password"],
  })
type PasswordValues = z.infer<typeof passwordSchema>

function PasswordTab() {
  const form = useForm<PasswordValues>({
    shouldFocusError: false,
    resolver: zodResolver(passwordSchema),
    defaultValues: {
      current_password: "",
      new_password: "",
      confirm_password: "",
    },
  })
  const { errors } = form.formState

  const save = useMutation({
    mutationFn: ({ current_password, new_password }: PasswordValues) =>
      changePassword({ current_password, new_password }),
    onSuccess: () => {
      form.reset()
      toast.success("Password changed")
    },
  })

  const input = (
    name: keyof PasswordValues,
    autoComplete: "current-password" | "new-password",
  ) => (
    <input
      id={`pw-${name}`}
      type="password"
      className="field-input"
      autoComplete={autoComplete}
      aria-invalid={errors[name] ? "true" : undefined}
      {...form.register(name)}
    />
  )

  return (
    <Card title="Change password">
      <form
        onSubmit={form.handleSubmit((v) => save.mutate(v), focusFirstError)}
        noValidate
        className="grid gap-4"
      >
        <Field
          label="Current password"
          htmlFor="pw-current_password"
          error={errors.current_password?.message}
        >
          {input("current_password", "current-password")}
        </Field>
        <Field
          label="New password"
          htmlFor="pw-new_password"
          error={errors.new_password?.message}
          hint="At least 8 characters."
        >
          {input("new_password", "new-password")}
        </Field>
        <Field
          label="Confirm new password"
          htmlFor="pw-confirm_password"
          error={errors.confirm_password?.message}
        >
          {input("confirm_password", "new-password")}
        </Field>
        {save.isError ? (
          <FormAlert>{describeError(save.error)}</FormAlert>
        ) : null}
        <div>
          <Button type="submit" disabled={save.isPending}>
            {save.isPending ? <Loader2 className="animate-spin" /> : null}
            Change password
          </Button>
        </div>
      </form>
    </Card>
  )
}

function AccountTab({ me }: { me: UserPublic }) {
  const [confirming, setConfirming] = useState(false)
  const queryClient = useQueryClient()
  const navigate = useNavigate()

  const deactivate = useMutation({
    mutationFn: deactivateMe,
    onSuccess: () => {
      signOut()
      queryClient.clear()
      toast.success("Your account has been deactivated")
      navigate({ to: "/login" })
    },
  })

  useEffect(() => {
    if (!confirming) deactivate.reset()
  }, [confirming, deactivate.reset])

  return (
    <Card className="border-danger/30">
      <h2 className="text-base font-semibold text-danger-deep">
        Deactivate your account
      </h2>
      <p className="mt-1.5 text-sm text-stone">
        You'll be signed out and won't be able to sign in again. Your records
        and the history attributed to you are kept. A platform administrator can
        reactivate it.
      </p>
      {me.is_superuser ? (
        <p className="mt-3 rounded-inner border border-line bg-oat px-4 py-3 text-sm text-stone">
          A superuser can't deactivate their own account. Another superuser can
          do it from Administration.
        </p>
      ) : (
        <Button
          variant="destructive"
          className="mt-4"
          onClick={() => setConfirming(true)}
        >
          Deactivate account
        </Button>
      )}

      <Dialog
        open={confirming}
        onOpenChange={(open) => {
          if (!deactivate.isPending) setConfirming(open)
        }}
      >
        <DialogContent>
          <div className="grid gap-4">
            <DialogHeader>
              <DialogTitle>Deactivate your account?</DialogTitle>
              <DialogDescription>
                You'll be signed out straight away and can't sign back in. Only
                a platform administrator can reactivate it.
              </DialogDescription>
            </DialogHeader>
            {deactivate.isError ? (
              <FormAlert>{describeError(deactivate.error)}</FormAlert>
            ) : null}
            <DialogFooter>
              <Button
                type="button"
                variant="outline"
                onClick={() => setConfirming(false)}
                disabled={deactivate.isPending}
              >
                Keep my account
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
        </DialogContent>
      </Dialog>
    </Card>
  )
}
