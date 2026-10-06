import { createFileRoute, redirect } from "@tanstack/react-router"
import { ResetPasswordPage } from "@/features/auth/ResetPasswordPage"
import { isSignedIn } from "@/lib/session"

/** The emailed link lands here: `{FRONTEND_HOST}/reset-password?token=...` (backend/app/utils.py). */
export const Route = createFileRoute("/reset-password")({
  validateSearch: (search: Record<string, unknown>): { token?: string } => ({
    token:
      typeof search.token === "string" && search.token.length > 0
        ? search.token
        : undefined,
  }),
  beforeLoad: () => {
    if (isSignedIn()) throw redirect({ to: "/" })
  },
  staticData: { title: "Choose a new password" },
  component: ResetPasswordRoute,
})

function ResetPasswordRoute() {
  const { token } = Route.useSearch()
  return <ResetPasswordPage token={token} />
}
