import { zodResolver } from "@hookform/resolvers/zod"
import { useQueryClient } from "@tanstack/react-query"
import { useRouter } from "@tanstack/react-router"
import { Loader2 } from "lucide-react"
import { useEffect, useState } from "react"
import { useForm } from "react-hook-form"
import { Button } from "@/components/ui/button"
import { resetPreview } from "@/data/preview/store"
import { Field } from "@/design/primitives"
import { describeError, httpStatus } from "@/lib/http"
import { signIn } from "@/lib/session"
import { z } from "@/lib/zod"
import { BrandMark } from "@/shell/BrandMark"

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
  })

  return (
    <div className="backdrop-pattern flex min-h-dvh items-center justify-center p-6">
      <form
        onSubmit={onSubmit}
        noValidate
        className="w-full max-w-[400px] animate-rise rounded-[18px] border border-line bg-paper/95 px-[38px] pt-10 pb-8 shadow-[0_24px_70px_rgba(38,34,27,0.16),0_2px_6px_rgba(38,34,27,0.06)] backdrop-blur-[4px] max-sm:px-6"
      >
        <BrandMark className="mb-[18px]" />
        <h1 className="font-serif text-[30px] font-semibold tracking-[-0.015em]">
          Clinic OS
        </h1>
        <p className="mb-1.5 font-serif text-[15px] text-stone italic">
          Calm software for careful medicine.
        </p>
        <p className="mb-6 text-[12.5px] tracking-[0.02em] text-stone-faint uppercase">
          Banksia Family Medical
        </p>

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
        </div>

        {failure ? (
          <p
            role="alert"
            className="mt-4 rounded-btn bg-danger-tint px-3 py-2.5 text-[13px] text-danger-deep"
          >
            {failure}
          </p>
        ) : null}

        <Button
          type="submit"
          size="lg"
          className="mt-5 w-full"
          disabled={isSubmitting}
        >
          {isSubmitting ? <Loader2 className="animate-spin" /> : null}
          {isSubmitting ? "Signing in…" : "Sign in"}
        </Button>

        <a
          href="/book/banksia-family-medical"
          className="mt-4 block text-center text-[13px] text-clay hover:underline"
        >
          New patient? Book an appointment
        </a>

        <div className="mt-6 flex justify-between border-line border-t pt-4 font-mono text-[10.5px] tracking-[0.04em] text-stone-faint uppercase">
          <span>AU data residency</span>
          <span>AES-256 at rest</span>
        </div>
      </form>
    </div>
  )
}
