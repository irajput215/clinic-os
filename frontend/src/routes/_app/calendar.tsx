import { createFileRoute } from "@tanstack/react-router"
import { practitionersQuery } from "@/data/appointments"
import { clinicHoursQuery } from "@/data/clinic-hours"
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
  loader: ({ context: { queryClient } }) => {
    // The hours shape the day view but never block it: asked alongside, not before.
    void queryClient.prefetchQuery(clinicHoursQuery)
    return queryClient.ensureQueryData(practitionersQuery)
  },
  pendingComponent: PagePending,
  errorComponent: PageError,
  component: CalendarRoute,
})

function CalendarRoute() {
  const { date, view } = Route.useSearch()
  return <CalendarPage date={date ?? clinicToday()} view={view ?? "day"} />
}
