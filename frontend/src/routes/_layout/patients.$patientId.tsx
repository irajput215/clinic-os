import { useQuery } from "@tanstack/react-query"
import { createFileRoute, Link as RouterLink } from "@tanstack/react-router"
import { AlertCircle, ArrowLeft, SearchX } from "lucide-react"

import { PatientsService } from "@/client"
import PatientDetails from "@/components/Patients/PatientDetails"
import { Button } from "@/components/ui/button"
import { Card, CardContent } from "@/components/ui/card"
import { Skeleton } from "@/components/ui/skeleton"
import { isNotFound } from "@/lib/http"
import { patientFullName } from "@/lib/patients"

/**
 * One patient.
 *
 * `retry: false` is deliberate. The API answers `404` both for a record that does not exist
 * and for one belonging to another organisation — that is how it avoids confirming that
 * someone else's record exists — and it answers `422` for an id that is not a UUID. Each is
 * a final answer, so retrying would only hold a spinner in front of the not-found state.
 */
const patientQueryOptions = (patientId: string) => ({
  queryKey: ["patients", patientId],
  queryFn: async () =>
    (await PatientsService.readPatient({ path: { patient_id: patientId } }))
      .data,
  retry: false,
})

export const Route = createFileRoute("/_layout/patients/$patientId")({
  component: PatientRecord,
  head: () => ({
    meta: [
      {
        title: "Patient - ClinicOS",
      },
    ],
  }),
})

function PatientRecord() {
  const { patientId } = Route.useParams()
  const {
    data: patient,
    isPending,
    isError,
    error,
    refetch,
    isFetching,
  } = useQuery(patientQueryOptions(patientId))

  const notFound = isError && isNotFound(error)

  return (
    <div className="flex flex-col gap-6">
      <div className="flex flex-col gap-3">
        <RouterLink
          to="/patients"
          className="inline-flex w-fit items-center gap-1 text-sm text-muted-foreground underline-offset-4 hover:text-foreground hover:underline"
        >
          <ArrowLeft className="size-4" aria-hidden="true" />
          All patients
        </RouterLink>
        {patient ? (
          <h1 className="text-2xl font-bold tracking-tight">
            {patientFullName(patient)}
          </h1>
        ) : isPending ? (
          <div className="h-8 w-64">
            <Skeleton className="h-8 w-64" />
          </div>
        ) : (
          <h1 className="text-2xl font-bold tracking-tight">
            {notFound ? "Patient not found" : "Patient"}
          </h1>
        )}
      </div>

      {isPending ? (
        <PendingPatient />
      ) : notFound ? (
        <PatientNotFound />
      ) : isError ? (
        <PatientError onRetry={() => refetch()} retrying={isFetching} />
      ) : patient ? (
        <PatientDetails patient={patient} />
      ) : null}
    </div>
  )
}

function PendingPatient() {
  return (
    <Card data-testid="patient-loading">
      <CardContent className="grid gap-4 py-6 sm:grid-cols-2">
        {Array.from({ length: 8 }).map((_, index) => (
          <div key={index} className="flex flex-col gap-2">
            <Skeleton className="h-3 w-24" />
            <Skeleton className="h-4 w-40" />
          </div>
        ))}
      </CardContent>
    </Card>
  )
}

/**
 * "No such patient" — deliberately not an error and not a permission message. The API
 * cannot tell the two apart, and the UI must not either.
 */
function PatientNotFound() {
  return (
    <Card data-testid="patient-not-found">
      <CardContent className="flex flex-col items-center gap-4 py-12 text-center">
        <div className="rounded-full bg-muted p-3">
          <SearchX
            className="size-6 text-muted-foreground"
            aria-hidden="true"
          />
        </div>
        <div className="flex flex-col gap-1">
          <p className="font-medium">Patient not found</p>
          <p className="text-sm text-muted-foreground">
            There is no patient with this reference in your organisation's
            records.
          </p>
        </div>
        <Button variant="outline" asChild>
          <RouterLink to="/patients">Back to patients</RouterLink>
        </Button>
      </CardContent>
    </Card>
  )
}

function PatientError({
  onRetry,
  retrying,
}: {
  onRetry: () => void
  retrying: boolean
}) {
  return (
    <Card data-testid="patient-error" role="alert">
      <CardContent className="flex flex-col items-start gap-4 py-8">
        <div className="flex items-center gap-2">
          <AlertCircle className="size-5 text-destructive" aria-hidden="true" />
          <p className="font-medium">We couldn't load this patient.</p>
        </div>
        <p className="text-sm text-muted-foreground">
          The API could not return the record. Try again in a moment.
        </p>
        <Button variant="outline" onClick={onRetry} disabled={retrying}>
          Try again
        </Button>
      </CardContent>
    </Card>
  )
}
