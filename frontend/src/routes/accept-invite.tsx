import { createFileRoute, redirect } from "@tanstack/react-router"
import { AcceptInvitePage } from "@/features/auth/AcceptInvitePage"
import { isSignedIn } from "@/lib/session"

/**
 * A staff invitation lands here: `{FRONTEND_HOST}/accept-invite?token=...`
 * (`backend/app/modules/users_roles/invitations.py`). A tab that is already signed in goes to the
 * app instead, like the other signed-out pages.
 */
export const Route = createFileRoute("/accept-invite")({
  validateSearch: (search: Record<string, unknown>): { token?: string } => ({
    token:
      typeof search.token === "string" && search.token.length > 0
        ? search.token
        : undefined,
  }),
  beforeLoad: () => {
    if (isSignedIn()) throw redirect({ to: "/" })
  },
  staticData: { title: "Join your clinic" },
  component: AcceptInviteRoute,
})

function AcceptInviteRoute() {
  const { token } = Route.useSearch()
  return <AcceptInvitePage token={token} />
}
