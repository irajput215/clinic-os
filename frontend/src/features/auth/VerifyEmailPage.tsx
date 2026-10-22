import { useQueryClient } from "@tanstack/react-query"
import { Link, useRouter } from "@tanstack/react-router"
import { Loader2 } from "lucide-react"
import { useRef, useState } from "react"
import { Button } from "@/components/ui/button"
import { verifySignup } from "@/data/account"
import { describeError, refusalCode } from "@/lib/http"
import {
  AuthAside,
  AuthFailure,
  AuthLayout,
  AuthLead,
  AuthTitle,
  authLinkClass,
} from "./AuthLayout"

/**
 * Where a signup's emailed link lands: `{FRONTEND_HOST}/verify-email?token=...`
 * (`docs/reference/decisions/D-008-signup-email-verification.md`). One button spends the link,
 * which creates the organisation and its owner and signs the person in. It is a button, not an
 * automatic request on load, so a mail scanner that opens links cannot spend it. The token is sent
 * only in the request body; it is never logged or shown.
 */
export function VerifyEmailPage({ token }: { token: string | undefined }) {
  if (!token)
    return (
      <AuthLayout>
        <AuthTitle>This link is incomplete</AuthTitle>
        <AuthLead>
          The link is missing the part that proves the email is yours.
        </AuthLead>
        <p className="text-[13.5px] leading-relaxed text-pretty text-stone">
          Open the link from your email again, or copy the whole address into
          your browser.
        </p>
        <AuthAside>
          <Link to="/signup" className={authLinkClass}>
            Register again
          </Link>
        </AuthAside>
      </AuthLayout>
    )
  return <ConfirmEmail token={token} />
}

function ConfirmEmail({ token }: { token: string }) {
  const router = useRouter()
  const queryClient = useQueryClient()
  const [pending, setPending] = useState(false)
  const [failure, setFailure] = useState<{
    message: string
    error: unknown
    deadLink: boolean
  } | null>(null)
  const titleRef = useRef<HTMLHeadingElement>(null)

  const confirm = async () => {
    setFailure(null)
    setPending(true)
    try {
      await verifySignup(token)
    } catch (error) {
      const deadLink = refusalCode(error) === "SIGNUP_LINK_INVALID"
      setFailure({
        message: deadLink
          ? "This link has expired, was replaced by a newer email or has already been used. If you've already confirmed, sign in; otherwise register again."
          : describeError(error),
        error,
        deadLink,
      })
      setPending(false)
      titleRef.current?.focus()
      return
    }
    queryClient.clear()
    await router.navigate({ to: "/" })
  }

  return (
    <AuthLayout>
      <AuthTitle titleRef={titleRef}>Confirm your email</AuthTitle>
      <AuthLead>
        This creates your clinic and signs you in as its administrator.
      </AuthLead>

      {failure?.deadLink ? null : (
        <Button
          type="button"
          size="lg"
          className="w-full"
          disabled={pending}
          onClick={confirm}
        >
          {pending ? <Loader2 className="animate-spin" /> : null}
          {pending ? "Confirming…" : "Confirm and sign in"}
        </Button>
      )}

      <AuthFailure
        message={failure?.message ?? null}
        error={failure?.deadLink ? undefined : failure?.error}
      />

      {failure?.deadLink ? (
        <div className="mt-5 grid gap-2">
          <Button asChild size="lg" className="w-full">
            <Link to="/login">Sign in</Link>
          </Button>
          <Button asChild variant="outline" size="lg" className="w-full">
            <Link to="/signup">Register again</Link>
          </Button>
        </div>
      ) : (
        <AuthAside>
          Already confirmed?{" "}
          <Link to="/login" className={authLinkClass}>
            Sign in
          </Link>
        </AuthAside>
      )}
    </AuthLayout>
  )
}
