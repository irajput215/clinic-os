import { zodResolver } from "@hookform/resolvers/zod"
import { Link } from "@tanstack/react-router"
import { Loader2 } from "lucide-react"
import { useEffect, useRef, useState } from "react"
import { useForm } from "react-hook-form"
import type { SignupAccepted } from "@/client/types.gen"
import { Button } from "@/components/ui/button"
import { registerOrganisation, resendSignupEmail } from "@/data/account"
import { Field } from "@/design/primitives"
import { focusFirstError } from "@/lib/form"
import {
  describeError,
  httpStatus,
  refusalCode,
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

const passwords = z.object({
  password: newPassword,
  confirm_password: confirmPassword,
})

const schema = z
  .object({
    clinic_name: z
      .string()
      .trim()
      .min(1, "Enter your clinic or practice name.")
      .max(255, "Keep the name to 255 characters or fewer."),
    full_name: z
      .string()
      .trim()
      .min(1, "Enter your full name.")
      .max(255, "Keep your name to 255 characters or fewer."),
    email: z
      .email("Enter a valid email address.")
      .max(255, "Use an email address of 255 characters or fewer."),
    password: newPassword,
    confirm_password: confirmPassword,
  })
  .refine((v) => v.password === v.confirm_password, {
    message: PASSWORDS_DIFFER,
    path: ["confirm_password"],
    // Say the passwords differ as soon as both are filled in, not after every other field is fixed.
    when: (payload) => passwords.safeParse(payload.value).success,
  })
type Values = z.infer<typeof schema>
type FieldName = keyof Values

const FIELDS: readonly FieldName[] = [
  "clinic_name",
  "full_name",
  "email",
  "password",
  "confirm_password",
]

/**
 * Registering here registers an organisation: the clinic name becomes the tenant and the signer its
 * Practice Owner (`docs/reference/business-flow.md` step 1). Staff are invited afterwards.
 *
 * Nothing is created until the person opens the link the server emails
 * (`docs/reference/decisions/D-007-signup-email-verification.md`). The server answers every address
 * the same way, so this page never says whether the address already has an account: "Check your
 * email" covers both the link and the notice an existing account's owner receives instead.
 */
export function SignupPage() {
  const [failure, setFailure] = useState<{
    message: string
    error: unknown
  } | null>(null)
  const [requested, setRequested] = useState<{
    email: string
    accepted: SignupAccepted
  } | null>(null)
  const form = useForm<Values>({
    shouldFocusError: false,
    resolver: zodResolver(schema),
    defaultValues: {
      clinic_name: "",
      full_name: "",
      email: "",
      password: "",
      confirm_password: "",
    },
  })
  const { errors, isSubmitting } = form.formState
  useEffect(() => {
    if (!requested) form.setFocus("clinic_name")
  }, [form, requested])

  const onSubmit = form.handleSubmit(async (values) => {
    setFailure(null)
    const { confirm_password: _confirm, ...body } = values
    try {
      const accepted = await registerOrganisation(body)
      setRequested({ email: body.email, accepted })
    } catch (error) {
      refuse(error)
    }
  }, focusFirstError)

  const refuse = (error: unknown) => {
    const status = httpStatus(error)
    if (status === 422) {
      const messages = validationMessages(error)
      const named = FIELDS.filter((f) => messages[f])
      for (const field of named)
        form.setError(field, { message: messages[field] })
      if (named.length > 0) {
        form.setFocus(named[0])
        return
      }
    }
    setFailure({
      message:
        status === 403
          ? "New organisations can't be registered on this server. Ask your Clinic OS administrator for an account."
          : refusalCode(error) === "EMAIL_NOT_CONFIGURED"
            ? "New organisations can't be registered right now: this server can't send email. Nothing was created."
            : describeError(error),
      error,
    })
  }

  if (requested)
    return (
      <CheckYourEmail
        email={requested.email}
        accepted={requested.accepted}
        onChangeEmail={() => {
          // Back to the filled form, minus the passwords, to correct the address.
          form.reset({
            ...form.getValues(),
            password: "",
            confirm_password: "",
          })
          setRequested(null)
          setTimeout(() => form.setFocus("email"))
        }}
      />
    )

  return (
    <AuthLayout>
      <AuthTitle>Register your clinic</AuthTitle>
      <AuthLead>
        This creates your organisation. You become its administrator and can add
        staff once you're in.
      </AuthLead>

      <form onSubmit={onSubmit} noValidate aria-label="Register your clinic">
        <div className="space-y-4">
          <Field
            label="Clinic or practice name"
            htmlFor="clinic_name"
            error={errors.clinic_name?.message}
          >
            <input
              id="clinic_name"
              type="text"
              autoComplete="organization"
              aria-invalid={errors.clinic_name ? "true" : undefined}
              className="field-input"
              {...form.register("clinic_name")}
            />
          </Field>
          <Field
            label="Your full name"
            htmlFor="full_name"
            error={errors.full_name?.message}
          >
            <input
              id="full_name"
              type="text"
              autoComplete="name"
              aria-invalid={errors.full_name ? "true" : undefined}
              className="field-input"
              {...form.register("full_name")}
            />
          </Field>
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
          <Field
            label="Password"
            htmlFor="password"
            error={errors.password?.message}
            hint={PASSWORD_HINT}
          >
            <input
              id="password"
              type="password"
              autoComplete="new-password"
              aria-invalid={errors.password ? "true" : undefined}
              className="field-input"
              {...form.register("password")}
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
        />

        <Button
          type="submit"
          size="lg"
          className="mt-5 w-full"
          disabled={isSubmitting}
        >
          {isSubmitting ? <Loader2 className="animate-spin" /> : null}
          {isSubmitting ? "Registering…" : "Register clinic"}
        </Button>
      </form>

      <AuthAside>
        Already have an account?{" "}
        <Link to="/login" className={authLinkClass}>
          Sign in
        </Link>
      </AuthAside>
    </AuthLayout>
  )
}

/**
 * After a signup: the email is on its way. The words hold for both answers the server may have
 * mailed (the link, or a notice to an address that already has an account), so the page discloses
 * nothing about the address.
 */
function CheckYourEmail({
  email,
  accepted,
  onChangeEmail,
}: {
  email: string
  accepted: SignupAccepted
  onChangeEmail: () => void
}) {
  const titleRef = useRef<HTMLHeadingElement>(null)
  const [resend, setResend] = useState<
    | { state: "idle" }
    | { state: "sending" }
    | { state: "sent" }
    | { state: "failed"; error: unknown }
  >({ state: "idle" })
  useEffect(() => titleRef.current?.focus(), [])

  const sendAgain = async () => {
    setResend({ state: "sending" })
    try {
      await resendSignupEmail(accepted.request_id)
      setResend({ state: "sent" })
    } catch (error) {
      setResend({ state: "failed", error })
    }
  }

  return (
    <AuthLayout>
      <AuthTitle titleRef={titleRef}>Check your email</AuthTitle>
      <AuthLead>One more step and your clinic is ready.</AuthLead>
      <AuthConfirmation>
        We've sent a message to{" "}
        <span className="font-mono text-[12.5px] wrap-anywhere">{email}</span>.
        Open the link in it within {accepted.expires_in_hours} hours to finish
        registering and sign in. If this address already has an account, the
        message explains how to sign in instead.
      </AuthConfirmation>
      <p className="mt-4 text-[13px] leading-relaxed text-pretty text-stone">
        It can take a minute to arrive; check your spam folder too.
      </p>
      <Button
        type="button"
        variant="outline"
        size="lg"
        className="mt-5 w-full"
        disabled={resend.state === "sending"}
        onClick={sendAgain}
      >
        {resend.state === "sending" ? (
          <Loader2 className="animate-spin" />
        ) : null}
        Send the email again
      </Button>
      {resend.state === "sent" ? (
        <p role="status" className="mt-3 text-center text-[13px] text-ok-deep">
          Sent again. Use the newest email: earlier links no longer work.
        </p>
      ) : null}
      <AuthFailure
        message={resend.state === "failed" ? describeError(resend.error) : null}
        error={resend.state === "failed" ? resend.error : undefined}
      />
      <Button
        type="button"
        variant="ghost"
        size="lg"
        className="mt-2 w-full"
        onClick={onChangeEmail}
      >
        Use a different email
      </Button>
    </AuthLayout>
  )
}
