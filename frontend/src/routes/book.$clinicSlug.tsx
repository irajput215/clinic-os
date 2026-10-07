import { createFileRoute } from "@tanstack/react-router"
import { BookingPage } from "@/features/booking/BookingPage"

/** Public, unauthenticated. The clinic is identified by its slug; the server resolves the tenant. */
export const Route = createFileRoute("/book/$clinicSlug")({
  staticData: { title: "Book an appointment" },
  params: {
    parse: ({ clinicSlug }) => ({
      clinicSlug: clinicSlug
        .toLowerCase()
        .replace(/[^a-z0-9-]/g, "")
        .slice(0, 64),
    }),
    stringify: ({ clinicSlug }) => ({ clinicSlug }),
  },
  component: BookingRoute,
})

function BookingRoute() {
  const { clinicSlug } = Route.useParams()
  return <BookingPage clinicSlug={clinicSlug} />
}
