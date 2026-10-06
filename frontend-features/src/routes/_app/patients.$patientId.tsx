import { createFileRoute, notFound } from "@tanstack/react-router"
import { patientQuery } from "@/data/patients"
import { EmptyState, PageError, PagePending } from "@/design/primitives"
import { PatientRecordPage } from "@/features/patients/PatientRecordPage"
import { PATIENT_TAB_KEYS, type PatientTab } from "@/features/patients/tabs"
import { isNotFound } from "@/lib/http"
import { oneOf } from "@/lib/search"

export const Route = createFileRoute("/_app/patients/$patientId")({
  staticData: { title: "Patient record" },
  validateSearch: (search: Record<string, unknown>): { tab?: PatientTab } => ({
    tab: oneOf(PATIENT_TAB_KEYS, search.tab),
  }),
  loader: async ({ context: { queryClient }, params }) => {
    try {
      await queryClient.ensureQueryData(patientQuery(params.patientId))
    } catch (error) {
      // Absent and another organisation's record are the same answer (404), by design.
      if (isNotFound(error)) throw notFound()
      throw error
    }
  },
  pendingComponent: PagePending,
  errorComponent: PageError,
  notFoundComponent: () => (
    <EmptyState
      title="That patient record isn't available."
      body="It may not exist, or it isn't part of your practice."
    />
  ),
  component: PatientRoute,
})

function PatientRoute() {
  const { patientId } = Route.useParams()
  const { tab } = Route.useSearch()
  return <PatientRecordPage patientId={patientId} tab={tab ?? "overview"} />
}
