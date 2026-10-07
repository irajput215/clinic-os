import { zodResolver } from "@hookform/resolvers/zod"
import { Link } from "@tanstack/react-router"
import { Loader2 } from "lucide-react"
import { useEffect, useRef, useState } from "react"
import { useForm } from "react-hook-form"
import { Button } from "@/components/ui/button"
import { resetPassword } from "@/data/account"
import { Field } from "@/design/primitives"
import { focusFirstError } from "@/lib/form"
import {
  apiErrorMessage,
  describeError,
  httpStatus,
  validationMessages,
} from "@/lib/http"
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
 * Spends the emailed reset token. The token arrives in the link's `token` query parameter
 * (`backend/app/utils.py` builds `{FRONTEND_HOST}/reset-password?token=...`) and is sent only in the
 * request body; it is never logged or shown.
 */
export function ResetPasswordPage({ token }: { token: string | undefined }) {
  if (!token)
    return (
      <AuthLayout>
        <AuthTitle>This link is incomplete</AuthTitle>
        <AuthLead>
          The reset link is missing the part that proves it's yours.
        </AuthLead>
        <p className="text-[13.5px] leading-relaxed text-pretty text-stone">
          Open the link from the email again, or copy the whole address into
          your browser. If it still doesn't work, ask for a new link.
        </p>
        <Button asChild size="lg" className="mt-5 w-full">
          <Link to="/recover-password">Send a new link</Link>
        </Button>
        <AuthAside>
          <Link to="/login" className={authLinkClass}>
            Back to sign in
          </Link>
        </AuthAside>
      </AuthLayout>
    )
  return <ResetPasswordForm token={token} />
}

function ResetPasswordForm({ token }: { token: string }) {
  const [failure, setFailure] = useState<Failure | null>(null)
  const [done, setDone] = useState(false)
  const titleRef = useRef<HTMLHeadingElement>(null)
  const form = useForm<Values>({
    shouldFocusError: false,
    resolver: zodResolver(schema),
    defaultValues: { new_password: "", confirm_password: "" },
  })
  const { errors, isSubmitting } = form.formState

  useEffect(() => {
    if (done) titleRef.current?.focus()
    else form.setFocus("new_password")
  }, [done, form])

  const onSubmit = form.handleSubmit(async ({ new_password }) => {
    setFailure(null)
    try {
      await resetPassword(token, new_password)
      form.reset()
      setDone(true)
    } catch (error) {
      setFailure(describe(error))
      const message = validationMessages(error).new_password
      if (message) form.setError("new_password", { message })
    }
  }, focusFirstError(form.setFocus))

  if (done)
    return (
      <AuthLayout>
        <AuthTitle titleRef={titleRef}>Password updated</AuthTitle>
        <AuthLead>Your new password works from now on.</AuthLead>
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
      <AuthTitle>Choose a new password</AuthTitle>
      <AuthLead>You'll use it to sign in to Clinic OS from now on.</AuthLead>

      <form onSubmit={onSubmit} noValidate aria-label="Choose a new password">
        <div className="space-y-4">
          <Field
            label="New password"
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
            label="Confirm new password"
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
                Send a new link
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
          {isSubmitting ? "Saving…" : "Set new password"}
        </Button>
      </form>

      <AuthAside>
        <Link to="/login" className={authLinkClass}>
          Back to sign in
        </Link>
      </AuthAside>
    </AuthLayout>
  )
}

/**
 * The API refuses a bad token with `400 "Invalid token"` (expired, tampered, or for an account that
 * no longer exists: the same answer for all three) and a deactivated account with
 * `400 "Inactive user"`.
 */
const describe = (error: unknown): Failure => {
  if (httpStatus(error) === 400) {
    if (apiErrorMessage(error) === "Inactive user")
      return {
        message:
          "This account is deactivated, so its password can't be changed. Ask your practice administrator.",
        error,
        deadLink: false,
      }
    return {
      message: "This reset link has expired or isn't valid any more.",
      error,
      deadLink: true,
    }
  }
  return { message: describeError(error), error, deadLink: false }
}
