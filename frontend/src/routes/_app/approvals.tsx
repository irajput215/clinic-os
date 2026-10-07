import { createFileRoute } from "@tanstack/react-router"
import {
  REGISTER_FILTER_KEYS,
  type RegisterFilter,
  registerQuery,
} from "@/data/approvals"
import { PageError, PagePending } from "@/design/primitives"
import { ApprovalsPage } from "@/features/approvals/ApprovalsPage"
import { oneOf } from "@/lib/search"

export const Route = createFileRoute("/_app/approvals")({
  staticData: { title: "Approvals" },
  // The filter is a code, never PHI, so it lives in the URL and survives Back from a patient.
  validateSearch: (
    search: Record<string, unknown>,
  ): { filter?: RegisterFilter } => ({
    filter: oneOf(REGISTER_FILTER_KEYS, search.filter),
  }),
  loaderDeps: ({ search }) => ({ filter: search.filter ?? "attention" }),
  // Prefetch without blocking: the page renders its own loading and error states.
  loader: ({ context: { queryClient }, deps }) => {
    void queryClient.prefetchInfiniteQuery(registerQuery(deps.filter))
  },
  pendingComponent: PagePending,
  errorComponent: PageError,
  component: ApprovalsRoute,
})

function ApprovalsRoute() {
  const { filter } = Route.useSearch()
  return <ApprovalsPage filter={filter ?? "attention"} />
}
