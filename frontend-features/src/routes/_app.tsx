import { createFileRoute, redirect } from "@tanstack/react-router"
import { currentUserQuery, isSignedIn } from "@/lib/session"
import { AppShell } from "@/shell/AppShell"

/**
 * Every staff screen sits under this layout. No token means the sign-in page; the token itself is
 * validated by the server on the first request (`/users/me`), and a `401` there signs out.
 */
export const Route = createFileRoute("/_app")({
  beforeLoad: ({ location }) => {
    if (!isSignedIn())
      throw redirect({ to: "/login", search: { redirect: location.href } })
  },
  loader: ({ context }) =>
    context.queryClient.ensureQueryData(currentUserQuery),
  component: AppShell,
})
