import { createFileRoute } from "@tanstack/react-router"
import { PageError, PagePending } from "@/design/primitives"
import { AdminPage } from "@/features/admin/AdminPage"
import { ADMIN_TAB_KEYS, type AdminTab } from "@/features/admin/tabs"
import { oneOf } from "@/lib/search"

/**
 * No permission gate here: the server is the boundary. The page renders, its reads go out, and a
 * `403` renders as the designed "not available to your role" state.
 */
export const Route = createFileRoute("/_app/admin")({
  staticData: { title: "Administration" },
  validateSearch: (search: Record<string, unknown>): { tab?: AdminTab } => ({
    tab: oneOf(ADMIN_TAB_KEYS, search.tab),
  }),
  pendingComponent: PagePending,
  errorComponent: PageError,
  component: AdminRoute,
})

function AdminRoute() {
  const { tab } = Route.useSearch()
  return <AdminPage tab={tab} />
}
