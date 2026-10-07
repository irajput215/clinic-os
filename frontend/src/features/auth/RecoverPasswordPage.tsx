import { zodResolver } from "@hookform/resolvers/zod"
import { Link } from "@tanstack/react-router"
import { Loader2 } from "lucide-react"
import { useEffect, useRef, useState } from "react"
import { useForm } from "react-hook-form"
import { Button } from "@/components/ui/button"
import { requestPasswordRecovery } from "@/data/account"
import { Field } from "@/design/primitives"
import { focusFirstError } from "@/lib/form"
import { describeError } from "@/lib/http"
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

const schema = z.object({
  email: z.email("Enter the email you sign in with."),
})
type Values = z.infer<typeof schema>

/**
 * Asks for a reset link. The API answers identically whether or not the address has an account, so
 * the confirmation is worded the same way: it never says that an account exists.
 */
export function RecoverPasswordPage() {
  const [failure, setFailure] = useState<{
    message: string
    error: unknown
  } | null>(null)
  const [sentTo, setSentTo] = useState<string | null>(null)
  const titleRef = useRef<HTMLHeadingElement>(null)
  const form = useForm<Values>({
    shouldFocusError: false,
    resolver: zodResolver(schema),
    defaultValues: { email: "" },
  })
  const { errors, isSubmitting } = form.formState

  useEffect(() => {
    if (sentTo) titleRef.current?.focus()
    else form.setFocus("email")
  }, [sentTo, form])

  const onSubmit = form.handleSubmit(async ({ email }) => {
    setFailure(null)
    try {
      await requestPasswordRecovery(email)
      setSentTo(email)
    } catch (error) {
      setFailure({ message: describeError(error), error })
    }
  }, focusFirstError(form.setFocus))

  if (sentTo)
    return (
      <AuthLayout>
        <AuthTitle titleRef={titleRef}>Check your email</AuthTitle>
        <AuthLead>The link in it lets you choose a new password.</AuthLead>
        <AuthConfirmation>
          If <span className="font-medium wrap-anywhere">{sentTo}</span> has a
          Clinic OS account, we've sent it a password reset link. It can take a
          minute to arrive; check your spam folder too.
        </AuthConfirmation>
        <Button asChild size="lg" className="mt-5 w-full">
          <Link to="/login">Back to sign in</Link>
        </Button>
        <AuthAside>
          Wrong address?{" "}
          <button
            type="button"
            className={authLinkClass}
            onClick={() => {
              form.reset({ email: "" })
              setSentTo(null)
            }}
          >
            Try another email
          </button>
        </AuthAside>
      </AuthLayout>
    )

  return (
    <AuthLayout>
      <AuthTitle>Reset your password</AuthTitle>
      <AuthLead>
        Enter the email you sign in with and we'll send you a link to choose a
        new password.
      </AuthLead>

      <form onSubmit={onSubmit} noValidate aria-label="Reset your password">
        <Field label="Email" htmlFor="email" error={errors.email?.message}>
          <input
            id="email"
            type="email"
            autoComplete="email"
            aria-invalid={errors.email ? "true" : undefined}
            className="field-input"
            {...form.register("email")}
          />
        </Field>

        <AuthFailure
          message={failure?.message ?? null}
          error={failure?.error}
        />

        <Button
          type="submit"
          size="lg"
          className="mt-5 w-full"
          disabled={isSubmitting}
        >
          {isSubmitting ? <Loader2 className="animate-spin" /> : null}
          {isSubmitting ? "Sending…" : "Send reset link"}
        </Button>
      </form>

      <AuthAside>
        Remembered it?{" "}
        <Link to="/login" className={authLinkClass}>
          Back to sign in
        </Link>
      </AuthAside>
    </AuthLayout>
  )
}
