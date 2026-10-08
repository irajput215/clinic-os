import { createFileRoute, redirect } from "@tanstack/react-router"
import { approvalCountsQuery } from "@/data/approvals"
import { myPermissionsQuery } from "@/data/permissions"
import { scriptsQuery } from "@/data/scripts"
import { currentUserQuery, isSignedIn } from "@/lib/session"
import { AppShell } from "@/shell/AppShell"

/** Fetch only while the cache has no answer; one try (the sidebar's own reads never retry either). */
const once = { retry: false, staleTime: Number.POSITIVE_INFINITY } as const

/**
 * Every staff screen sits under this layout. No token means the sign-in page; the token itself is
 * validated by the server on the first request (`/users/me`), and a `401` there signs out.
 *
 * The shell's own reads (the permission set that decides the Administration entry, and the two
 * sidebar counts) start here, together with `/users/me` and the screen's own loader, instead of
 * after `/users/me` has answered and the shell has rendered: no cold load waits a round trip for
 * them. They do not block the render; the components that show them read the same cache entries
 * (`data/permissions.ts`, `shell/AppShell.tsx`), and a refusal there is the server's answer as usual.
 * Asked only while the cache has no answer (`once`), so a later navigation or a hover preload never
 * refetches them: the components keep them fresh as before.
 */
export const Route = createFileRoute("/_app")({
  beforeLoad: ({ location }) => {
    if (!isSignedIn())
      throw redirect({ to: "/login", search: { redirect: location.href } })
  },
  loader: ({ context: { queryClient } }) => {
    void queryClient.prefetchQuery({ ...myPermissionsQuery, ...once })
    void queryClient.prefetchQuery({ ...scriptsQuery, ...once })
    void queryClient.prefetchQuery({ ...approvalCountsQuery, ...once })
    return queryClient.ensureQueryData(currentUserQuery)
  },
  component: AppShell,
})
