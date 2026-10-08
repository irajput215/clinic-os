import { zodResolver } from "@hookform/resolvers/zod"
import { useQueryClient } from "@tanstack/react-query"
import { Link, useRouter } from "@tanstack/react-router"
import { Loader2 } from "lucide-react"
import { useEffect, useRef, useState } from "react"
import { useForm } from "react-hook-form"
import { Button } from "@/components/ui/button"
import { registerOrganisation } from "@/data/account"
import { Field } from "@/design/primitives"
import { focusFirstError } from "@/lib/form"
import { describeError, httpStatus, validationMessages } from "@/lib/http"
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
 */
export function SignupPage() {
  const router = useRouter()
  const queryClient = useQueryClient()
  const [failure, setFailure] = useState<{
    message: string
    error: unknown
  } | null>(null)
  const [registered, setRegistered] = useState(false)
  const titleRef = useRef<HTMLHeadingElement>(null)
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
  useEffect(() => form.setFocus("clinic_name"), [form])
  useEffect(() => {
    if (registered) titleRef.current?.focus()
  }, [registered])

  const onSubmit = form.handleSubmit(async (values) => {
    setFailure(null)
    const { confirm_password: _confirm, ...body } = values
    try {
      await registerOrganisation(body)
    } catch (error) {
      refuse(error)
      return
    }
    // The organisation exists now. Signing in is a convenience: if it fails (rate limit, network),
    // the account is still there and the person signs in from the sign-in page.
    try {
      await signIn(body.email, body.password)
      queryClient.clear()
      await router.navigate({ to: "/" })
    } catch {
      setRegistered(true)
    }
  }, focusFirstError)

  const refuse = (error: unknown) => {
    const status = httpStatus(error)
    if (status === 400) {
      // The only 400 signup raises: the email already has an account.
      form.setError(
        "email",
        { message: "An account already uses this email. Sign in instead." },
        { shouldFocus: true },
      )
      return
    }
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
          : describeError(error),
      error,
    })
  }

  if (registered)
    return (
      <AuthLayout>
        <AuthTitle titleRef={titleRef}>Your clinic is ready</AuthTitle>
        <AuthLead>
          You're its administrator. Add your staff once you're in.
        </AuthLead>
        <AuthConfirmation>
          {form.getValues("clinic_name")} is registered. Sign in with the email
          and password you just chose.
        </AuthConfirmation>
        <Button asChild size="lg" className="mt-5 w-full">
          <Link to="/login">Go to sign in</Link>
        </Button>
      </AuthLayout>
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
