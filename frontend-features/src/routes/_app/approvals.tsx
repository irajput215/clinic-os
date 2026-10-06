import { createFileRoute } from "@tanstack/react-router"
import { approvalsQuery } from "@/data/approvals"
import { patientsQuery } from "@/data/patients"
import { PageError, PagePending } from "@/design/primitives"
import { ApprovalsPage } from "@/features/approvals/ApprovalsPage"

export const Route = createFileRoute("/_app/approvals")({
  staticData: { title: "Approvals" },
  // Prefetch without blocking: the page renders its own loading and error states per card.
  loader: ({ context: { queryClient } }) => {
    void queryClient.prefetchQuery(approvalsQuery)
    void queryClient.prefetchQuery(patientsQuery)
  },
  pendingComponent: PagePending,
  errorComponent: PageError,
  component: ApprovalsPage,
})
