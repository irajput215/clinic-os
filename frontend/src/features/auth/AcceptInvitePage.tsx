import { zodResolver } from "@hookform/resolvers/zod"
import { useQueryClient } from "@tanstack/react-query"
import { Link, useRouter } from "@tanstack/react-router"
import { Loader2 } from "lucide-react"
import { useEffect, useRef, useState } from "react"
import { useForm } from "react-hook-form"
import { Button } from "@/components/ui/button"
import { acceptInvitation } from "@/data/account"
import { resetPreview } from "@/data/preview/store"
import { Field } from "@/design/primitives"
import { focusFirstError } from "@/lib/form"
import {
  describeError,
  httpStatus,
  refusalCode,
  validationMessages,
} from "@/lib/http"
import { signIn } from "@/lib/session"
import { z } from "@/lib/zod"
import {
  AuthAside,
  AuthConfirmation,
  AuthFailure,
  AuthLayout,
  AuthLead,
  AuthTitle,
  authLinkClass,
} from "./AuthLayout"
import {
  confirmPassword,
  newPassword,
  PASSWORD_HINT,
  PASSWORDS_DIFFER,
} from "./password"

const schema = z
  .object({ new_password: newPassword, confirm_password: confirmPassword })
  .refine((v) => v.new_password === v.confirm_password, {
    message: PASSWORDS_DIFFER,
    path: ["confirm_password"],
  })
type Values = z.infer<typeof schema>

type Failure = { message: string; error: unknown; deadLink: boolean }

/**
 * Where a staff invitation lands: `{FRONTEND_HOST}/accept-invite?token=...`
 * (`backend/app/modules/users_roles/invitations.py`). The person chooses their own password, which
 * spends the single-use token, and is then signed in to the organisation that invited them. The
 * token is sent only in the request body; it is never logged or shown.
 */
export function AcceptInvitePage({ token }: { token: string | undefined }) {
  if (!token)
    return (
      <AuthLayout>
        <AuthTitle>This link is incomplete</AuthTitle>
        <AuthLead>
          The invitation link is missing the part that proves it's yours.
        </AuthLead>
        <p className="text-[13.5px] leading-relaxed text-pretty text-stone">
          Open the link from your invitation email again, or copy the whole
          address into your browser.
        </p>
        <AuthAside>
          <Link to="/login" className={authLinkClass}>
            Go to sign in
          </Link>
        </AuthAside>
      </AuthLayout>
    )
  return <AcceptInviteForm token={token} />
}

function AcceptInviteForm({ token }: { token: string }) {
  const router = useRouter()
  const queryClient = useQueryClient()
  const [failure, setFailure] = useState<Failure | null>(null)
  const [accepted, setAccepted] = useState(false)
  const titleRef = useRef<HTMLHeadingElement>(null)
  const form = useForm<Values>({
    shouldFocusError: false,
    resolver: zodResolver(schema),
    defaultValues: { new_password: "", confirm_password: "" },
  })
  const { errors, isSubmitting } = form.formState

  useEffect(() => {
    if (accepted) titleRef.current?.focus()
    else form.setFocus("new_password")
  }, [accepted, form])

  const onSubmit = form.handleSubmit(async ({ new_password }) => {
    setFailure(null)
    let email: string
    try {
      email = (await acceptInvitation(token, new_password)).email
    } catch (error) {
      setFailure(describe(error))
      const message = validationMessages(error).new_password
      if (message) form.setError("new_password", { message })
      return
    }
    try {
      await signIn(email, new_password)
      queryClient.clear()
      resetPreview()
      await router.navigate({ to: "/" })
    } catch {
      // The password is set; only the automatic sign-in failed (a busy sign-in limit, say).
      form.reset()
      setAccepted(true)
    }
  }, focusFirstError)

  if (accepted)
    return (
      <AuthLayout>
        <AuthTitle titleRef={titleRef}>You're all set</AuthTitle>
        <AuthLead>Your password is saved.</AuthLead>
        <AuthConfirmation>
          Sign in with your email and the password you just chose.
        </AuthConfirmation>
        <Button asChild size="lg" className="mt-5 w-full">
          <Link to="/login">Sign in</Link>
        </Button>
      </AuthLayout>
    )

  return (
    <AuthLayout>
      <AuthTitle>Join your clinic</AuthTitle>
      <AuthLead>Choose a password to finish setting up your account.</AuthLead>

      <form onSubmit={onSubmit} noValidate aria-label="Choose your password">
        <div className="space-y-4">
          <Field
            label="Password"
            htmlFor="new_password"
            error={errors.new_password?.message}
            hint={PASSWORD_HINT}
          >
            <input
              id="new_password"
              type="password"
              autoComplete="new-password"
              aria-invalid={errors.new_password ? "true" : undefined}
              className="field-input"
              {...form.register("new_password")}
            />
          </Field>
          <Field
            label="Confirm password"
            htmlFor="confirm_password"
            error={errors.confirm_password?.message}
          >
            <input
              id="confirm_password"
              type="password"
              autoComplete="new-password"
              aria-invalid={errors.confirm_password ? "true" : undefined}
              className="field-input"
              {...form.register("confirm_password")}
            />
          </Field>
        </div>

        <AuthFailure
          message={failure?.message ?? null}
          error={failure?.error}
          action={
            failure?.deadLink ? (
              <Link
                to="/recover-password"
                className="font-semibold underline underline-offset-2"
              >
                Get a new link
              </Link>
            ) : undefined
          }
        />

        <Button
          type="submit"
          size="lg"
          className="mt-5 w-full"
          disabled={isSubmitting}
        >
          {isSubmitting ? <Loader2 className="animate-spin" /> : null}
          {isSubmitting ? "Setting up…" : "Set password and sign in"}
        </Button>
      </form>

      <AuthAside>
        Already set a password?{" "}
        <Link to="/login" className={authLinkClass}>
          Sign in
        </Link>
      </AuthAside>
    </AuthLayout>
  )
}

/**
 * The API answers every unusable link the same way, `400 INVITATION_INVALID` (expired, already
 * used, tampered, or the account is gone or deactivated), so the page cannot say which. The
 * account itself exists, so password recovery is the way to a fresh link.
 */
const describe = (error: unknown): Failure => {
  if (httpStatus(error) === 400 || refusalCode(error) === "INVITATION_INVALID")
    return {
      message: "This invitation link has expired or has already been used.",
      error,
      deadLink: true,
    }
  if (httpStatus(error) === 429)
    return {
      message: "Too many attempts. Wait a minute, then try again.",
      error,
      deadLink: false,
    }
  return { message: describeError(error), error, deadLink: false }
}
