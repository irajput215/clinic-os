import { createFileRoute, notFound } from "@tanstack/react-router"
import { inboxMessageQuery } from "@/data/inbox"
import { EmptyState, PageError, PagePending } from "@/design/primitives"
import { ReviewPage } from "@/features/inbox/ReviewPage"
import { isNotFound } from "@/lib/http"

export const Route = createFileRoute("/_app/tga-inbox/$messageId")({
  staticData: { title: "Review TGA letter" },
  loader: async ({ context: { queryClient }, params }) => {
    try {
      await queryClient.ensureQueryData(inboxMessageQuery(params.messageId))
    } catch (error) {
      // Absent and another clinic's message are the same answer (404), by design.
      if (isNotFound(error)) throw notFound()
      throw error
    }
  },
  pendingComponent: PagePending,
  errorComponent: PageError,
  notFoundComponent: () => (
    <EmptyState
      title="That letter isn't available."
      body="It may not exist, or it isn't part of your practice."
    />
  ),
  component: ReviewRoute,
})

function ReviewRoute() {
  const { messageId } = Route.useParams()
  return <ReviewPage messageId={messageId} />
}
