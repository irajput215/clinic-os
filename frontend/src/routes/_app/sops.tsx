import { createFileRoute } from "@tanstack/react-router"
import { PageError, PagePending } from "@/design/primitives"
import { SopsPage } from "@/features/sops/SopsPage"
import { SOP_TAB_KEYS, type SopTab } from "@/features/sops/tabs"
import { oneOf } from "@/lib/search"

export const Route = createFileRoute("/_app/sops")({
  staticData: { title: "SOPs & policies" },
  validateSearch: (search: Record<string, unknown>): { tab?: SopTab } => ({
    tab: oneOf(SOP_TAB_KEYS, search.tab),
  }),
  pendingComponent: PagePending,
  errorComponent: PageError,
  component: SopsRoute,
})

function SopsRoute() {
  const { tab } = Route.useSearch()
  return <SopsPage tab={tab ?? "procedures"} />
}
