import { zodResolver } from "@hookform/resolvers/zod"
import { useQueryClient } from "@tanstack/react-query"
import { Link, useRouter } from "@tanstack/react-router"
import { Loader2 } from "lucide-react"
import { useEffect, useState } from "react"
import { useForm } from "react-hook-form"
import { Button } from "@/components/ui/button"
import { resetPreview } from "@/data/preview/store"
import { Field } from "@/design/primitives"
import { focusFirstError } from "@/lib/form"
import { describeError, httpStatus } from "@/lib/http"
import { signIn } from "@/lib/session"
import { cn } from "@/lib/utils"
import { z } from "@/lib/zod"
import {
  AuthFailure,
  AuthLayout,
  AuthLead,
  AuthTitle,
  authLinkClass,
} from "./AuthLayout"

const schema = z.object({
  username: z.email("Enter the email you sign in with."),
  password: z.string().min(1, "Enter your password."),
})
type Values = z.infer<typeof schema>

export function LoginPage({ redirectTo }: { redirectTo: string }) {
  const router = useRouter()
  const queryClient = useQueryClient()
  const [failure, setFailure] = useState<string | null>(null)
  const form = useForm<Values>({
    shouldFocusError: false,
    resolver: zodResolver(schema),
    defaultValues: { username: "", password: "" },
  })
  const { errors, isSubmitting } = form.formState
  useEffect(() => form.setFocus("username"), [form])

  const onSubmit = form.handleSubmit(async ({ username, password }) => {
    setFailure(null)
    try {
      await signIn(username, password)
      queryClient.clear()
      resetPreview()
      await router.navigate({ to: redirectTo })
    } catch (error) {
      const status = httpStatus(error)
      setFailure(
        status === 400 || status === 401
          ? "That email and password don't match an active account."
          : describeError(error),
      )
      form.setValue("password", "")
      form.setFocus("password")
    }
  }, focusFirstError(form.setFocus))

  return (
    <AuthLayout>
      <AuthTitle>Clinic OS</AuthTitle>
      <AuthLead>Calm software for careful medicine.</AuthLead>

      <form onSubmit={onSubmit} noValidate aria-label="Sign in">
        <div className="space-y-4">
          <Field
            label="Email"
            htmlFor="username"
            error={errors.username?.message}
          >
            <input
              id="username"
              type="email"
              autoComplete="username"
              aria-invalid={errors.username ? "true" : undefined}
              className="field-input"
              {...form.register("username")}
            />
          </Field>
          <div>
            <Field
              label="Password"
              htmlFor="password"
              error={errors.password?.message}
            >
              <input
                id="password"
                type="password"
                autoComplete="current-password"
                aria-invalid={errors.password ? "true" : undefined}
                className="field-input"
                {...form.register("password")}
              />
            </Field>
            <div className="mt-1.5 flex justify-end">
              <Link
                to="/recover-password"
                className={cn(authLinkClass, "text-[12.5px]")}
              >
                Forgot password?
              </Link>
            </div>
          </div>
        </div>

        <AuthFailure message={failure} />

        <Button
          type="submit"
          size="lg"
          className="mt-5 w-full"
          disabled={isSubmitting}
        >
          {isSubmitting ? <Loader2 className="animate-spin" /> : null}
          {isSubmitting ? "Signing in…" : "Sign in"}
        </Button>
      </form>

      <p className="mt-4 text-center text-[13px] text-stone">
        Setting up a practice?{" "}
        <Link to="/signup" className={authLinkClass}>
          Create an organisation
        </Link>
      </p>
    </AuthLayout>
  )
}
