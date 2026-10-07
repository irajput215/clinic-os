import { createFileRoute } from "@tanstack/react-router"
import { todayQuery } from "@/data/dashboard"
import { previewPractitionersQuery } from "@/data/preview/practitioners"
import { PageError, PagePending } from "@/design/primitives"
import { TodayPage } from "@/features/today/TodayPage"

export const Route = createFileRoute("/_app/")({
  staticData: { title: "Today's clinic" },
  loader: ({ context: { queryClient } }) =>
    Promise.all([
      queryClient.ensureQueryData(todayQuery),
      queryClient.ensureQueryData(previewPractitionersQuery),
    ]),
  pendingComponent: PagePending,
  errorComponent: PageError,
  component: TodayPage,
})
