import { createFileRoute } from "@tanstack/react-router"
import { patientPagesQuery } from "@/data/patients"
import { PatientsPage } from "@/features/patients/PatientsPage"

export const Route = createFileRoute("/_app/patients/")({
  staticData: { title: "Patients" },
  loader: ({ context: { queryClient } }) => {
    void queryClient.prefetchInfiniteQuery(patientPagesQuery(""))
  },
  component: PatientsPage,
})
