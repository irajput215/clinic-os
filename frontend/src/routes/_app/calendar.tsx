import { createFileRoute } from "@tanstack/react-router"
import { practitionersQuery } from "@/data/appointments"
import { PageError, PagePending } from "@/design/primitives"
import { CalendarPage } from "@/features/calendar/CalendarPage"
import { clinicToday } from "@/lib/format"
import { isoDate, oneOf } from "@/lib/search"

export const Route = createFileRoute("/_app/calendar")({
  staticData: { title: "Calendar" },
  validateSearch: (
    search: Record<string, unknown>,
  ): { date?: string; view?: "day" | "week" } => ({
    date: isoDate(search.date),
    view: oneOf(["day", "week"] as const, search.view),
  }),
  loader: ({ context: { queryClient } }) =>
    queryClient.ensureQueryData(practitionersQuery),
  pendingComponent: PagePending,
  errorComponent: PageError,
  component: CalendarRoute,
})

function CalendarRoute() {
  const { date, view } = Route.useSearch()
  return <CalendarPage date={date ?? clinicToday()} view={view ?? "day"} />
}
