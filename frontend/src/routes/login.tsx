import { createFileRoute, redirect } from "@tanstack/react-router"
import { LoginPage } from "@/features/auth/LoginPage"
import { safeRedirect } from "@/lib/search"
import { isSignedIn } from "@/lib/session"

export const Route = createFileRoute("/login")({
  validateSearch: (search: Record<string, unknown>): { redirect?: string } => ({
    redirect: safeRedirect(search.redirect),
  }),
  beforeLoad: ({ search }) => {
    if (isSignedIn()) throw redirect({ to: search.redirect ?? "/" })
  },
  staticData: { title: "Sign in" },
  component: LoginRoute,
})

function LoginRoute() {
  const { redirect: to } = Route.useSearch()
  return <LoginPage redirectTo={to ?? "/"} />
}
