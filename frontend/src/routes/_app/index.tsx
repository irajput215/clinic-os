import { createFileRoute } from "@tanstack/react-router"
import { todayQuery } from "@/data/dashboard"
import { PageError, PagePending } from "@/design/primitives"
import { TodayPage } from "@/features/today/TodayPage"

export const Route = createFileRoute("/_app/")({
  staticData: { title: "Today's clinic" },
  loader: ({ context: { queryClient } }) =>
    queryClient.ensureQueryData(todayQuery),
  pendingComponent: PagePending,
  errorComponent: PageError,
  component: TodayPage,
})
