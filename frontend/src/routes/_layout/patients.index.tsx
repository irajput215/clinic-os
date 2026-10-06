import { useQuery } from "@tanstack/react-query"
import { createFileRoute } from "@tanstack/react-router"
import { AlertCircle, UserRound } from "lucide-react"

import { PatientsService } from "@/client"
import { DataTable } from "@/components/Common/DataTable"
import AddPatient from "@/components/Patients/AddPatient"
import { columns } from "@/components/Patients/columns"
import PatientsNoAccess from "@/components/Patients/NoAccess"
import PendingPatients from "@/components/Patients/PendingPatients"
import { Button } from "@/components/ui/button"
import { Card, CardContent } from "@/components/ui/card"
import { httpStatus, retryTransient } from "@/lib/http"

/**
 * The server's maximum page size (`MAX_PATIENTS_PAGE_SIZE` in
 * `backend/app/modules/patients/router.py`). Asking for more is a `422`, so this is also the
 * largest list the screen can show; cursor pagination is not built.
 */
const PAGE_SIZE = 25

/**
 * The list retries what can change on its own — a dropped request or a `5xx` — and nothing
 * else. A `4xx` here is a final answer: `403` is refused access and `422` a page size the
 * server will not accept, and retrying either only holds a spinner in front of the state the
 * user needs to read.
 */
const patientsQueryOptions = {
  queryKey: ["patients"],
  queryFn: async () =>
    (
      await PatientsService.listPatients({
        query: { limit: PAGE_SIZE },
      })
    ).data,
  retry: retryTransient,
}

export const Route = createFileRoute("/_layout/patients/")({
  component: Patients,
  head: () => ({
    meta: [
      {
        title: "Patients - ClinicOS",
      },
    ],
  }),
})

function Patients() {
  const { data, isPending, isError, error, refetch, isFetching } =
    useQuery(patientsQueryOptions)

  return (
    <div className="flex flex-col gap-6">
      <div className="flex items-center justify-between gap-4">
        <div>
          <h1 className="text-2xl font-bold tracking-tight">Patients</h1>
          <p className="text-muted-foreground">
            Patients recorded by your organisation
          </p>
        </div>
        <AddPatient />
      </div>

      {isPending ? (
        <PendingPatients />
      ) : isError && httpStatus(error) === 403 ? (
        <PatientsNoAccess error={error} />
      ) : isError ? (
        <PatientsError
          status={httpStatus(error)}
          onRetry={() => refetch()}
          retrying={isFetching}
        />
      ) : data.data.length === 0 ? (
        <PatientsEmpty />
      ) : (
        <div className="flex flex-col gap-3">
          {data.count > data.data.length ? (
            <p className="text-sm text-muted-foreground">
              Showing the first {data.data.length} of {data.count} patients. The
              API returns at most {PAGE_SIZE} patients per request and paging is
              not built yet.
            </p>
          ) : null}
          <DataTable columns={columns} data={data.data} />
        </div>
      )}
    </div>
  )
}

function PatientsEmpty() {
  return (
    <Card data-testid="patients-empty">
      <CardContent className="flex flex-col items-center gap-4 py-12 text-center">
        <div className="rounded-full bg-muted p-3">
          <UserRound
            className="size-6 text-muted-foreground"
            aria-hidden="true"
          />
        </div>
        <div className="flex flex-col gap-1">
          <p className="font-medium">No patients yet</p>
          <p className="text-sm text-muted-foreground">
            Add the first patient to this organisation and they will appear
            here.
          </p>
        </div>
        <AddPatient label="Add the first patient" />
      </CardContent>
    </Card>
  )
}

function PatientsError({
  status,
  onRetry,
  retrying,
}: {
  status: number | undefined
  onRetry: () => void
  retrying: boolean
}) {
  // A `403` is refused access and has its own state above (`PatientsNoAccess`); this is what
  // is left, which is a failure worth retrying.
  const detail =
    status === undefined
      ? "The request could not reach the API. Check your connection and try again."
      : "The API could not return your patients. Try again in a moment."

  return (
    <Card data-testid="patients-error" role="alert">
      <CardContent className="flex flex-col items-start gap-4 py-8">
        <div className="flex items-center gap-2">
          <AlertCircle className="size-5 text-destructive" aria-hidden="true" />
          <p className="font-medium">We couldn't load your patients.</p>
        </div>
        <p className="text-sm text-muted-foreground">{detail}</p>
        <Button variant="outline" onClick={onRetry} disabled={retrying}>
          Try again
        </Button>
      </CardContent>
    </Card>
  )
}
