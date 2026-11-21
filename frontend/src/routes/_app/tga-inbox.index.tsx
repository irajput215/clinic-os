import { createFileRoute } from "@tanstack/react-router"
import {
  inboxQueueQuery,
  QUEUE_FILTER_KEYS,
  type QueueFilter,
} from "@/data/inbox"
import { PageError, PagePending } from "@/design/primitives"
import { InboxPage } from "@/features/inbox/InboxPage"
import { oneOf } from "@/lib/search"

export const Route = createFileRoute("/_app/tga-inbox/")({
  staticData: { title: "TGA inbox" },
  // The filter is a state code, never PHI, so it lives in the URL.
  validateSearch: (
    search: Record<string, unknown>,
  ): { filter?: QueueFilter } => ({
    filter: oneOf(QUEUE_FILTER_KEYS, search.filter),
  }),
  loaderDeps: ({ search }) => ({ filter: search.filter ?? "open" }),
  loader: ({ context: { queryClient }, deps }) => {
    void queryClient.prefetchQuery(inboxQueueQuery(deps.filter))
  },
  pendingComponent: PagePending,
  errorComponent: PageError,
  component: InboxRoute,
})

function InboxRoute() {
  const { filter } = Route.useSearch()
  return <InboxPage filter={filter ?? "open"} />
}
