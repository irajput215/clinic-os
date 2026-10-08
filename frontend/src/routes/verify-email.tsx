import { createFileRoute, redirect } from "@tanstack/react-router"
import { VerifyEmailPage } from "@/features/auth/VerifyEmailPage"
import { isSignedIn } from "@/lib/session"

/**
 * A signup's emailed link lands here: `{FRONTEND_HOST}/verify-email?token=...`
 * (`backend/app/modules/users_roles/signup.py`). A tab that is already signed in goes to the app
 * instead, like the other signed-out pages.
 */
export const Route = createFileRoute("/verify-email")({
  validateSearch: (search: Record<string, unknown>): { token?: string } => ({
    token:
      typeof search.token === "string" && search.token.length > 0
        ? search.token
        : undefined,
  }),
  beforeLoad: () => {
    if (isSignedIn()) throw redirect({ to: "/" })
  },
  staticData: { title: "Confirm your email" },
  component: VerifyEmailRoute,
})

function VerifyEmailRoute() {
  const { token } = Route.useSearch()
  return <VerifyEmailPage token={token} />
}
