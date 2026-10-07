import { useQuery } from "@tanstack/react-query"
import { useNavigate } from "@tanstack/react-router"
import { Plus, Search } from "lucide-react"
import { useMemo, useState } from "react"
import { Button } from "@/components/ui/button"
import { PATIENT_PAGE_LIMIT, patientName, patientsQuery } from "@/data/patients"
import {
  Card,
  EmptyState,
  ErrorState,
  Mono,
  PageHeader,
  SkeletonRows,
} from "@/design/primitives"
import { age, formatDate, patientRef } from "@/lib/format"
import { PatientFormDialog } from "./PatientFormDialog"

export function PatientsPage() {
  const navigate = useNavigate()
  const patients = useQuery(patientsQuery)
  const [filter, setFilter] = useState("")
  const [adding, setAdding] = useState(false)

  const rows = useMemo(() => {
    const q = filter.trim().toLowerCase()
    const all = patients.data?.data ?? []
    return q
      ? all.filter((p) =>
          [
            patientName(p),
            p.given_name,
            p.family_name,
            p.suburb ?? "",
            patientRef(p.id),
          ]
            .join(" ")
            .toLowerCase()
            .includes(q),
        )
      : all
  }, [patients.data, filter])

  return (
    <>
      <PageHeader
        title="Patients"
        subtitle="Everyone your practice cares for. Open a record for consult notes, TGA approvals, scripts and history."
        actions={
          <Button onClick={() => setAdding(true)}>
            <Plus /> Add patient
          </Button>
        }
      />

      <div className="mb-4 flex flex-wrap items-center gap-3">
        <div className="relative">
          <Search className="pointer-events-none absolute top-1/2 left-3 size-3.5 -translate-y-1/2 text-stone-faint" />
          <input
            id="patients-filter"
            name="patients-filter"
            type="search"
            aria-label="Filter patients"
            placeholder="Filter this page…"
            value={filter}
            onChange={(e) => setFilter(e.target.value)}
            className="h-[38px] w-[240px] rounded-full border border-line bg-paper pr-3 pl-[34px] text-[14px] outline-none focus:border-clay"
          />
        </div>
        {patients.data && patients.data.count >= PATIENT_PAGE_LIMIT ? (
          <span className="text-xs text-stone">
            Showing the first {PATIENT_PAGE_LIMIT}. Server-side search is on the
            patients API backlog.
          </span>
        ) : null}
      </div>

      <Card bodyClassName="-mx-5 -my-[18px]">
        {patients.isPending ? (
          <div className="p-5">
            <SkeletonRows rows={6} />
          </div>
        ) : patients.isError ? (
          <div className="p-5">
            <ErrorState
              error={patients.error}
              onRetry={() => patients.refetch()}
            />
          </div>
        ) : rows.length === 0 ? (
          <EmptyState
            title={
              filter ? "No patients match that filter." : "No patients yet."
            }
            body={
              filter
                ? undefined
                : "Add your first patient to start booking and prescribing."
            }
            action={
              filter ? null : (
                <Button size="sm" onClick={() => setAdding(true)}>
                  <Plus /> Add patient
                </Button>
              )
            }
          />
        ) : (
          <div className="overflow-x-auto">
            <table className="data-table">
              <thead>
                <tr>
                  <th className="rounded-tl-card pl-5">Patient</th>
                  <th className="max-sm:hidden">Reference</th>
                  <th className="max-md:rounded-tr-card max-md:pr-5">
                    Date of birth
                  </th>
                  <th className="max-md:hidden">Mobile</th>
                  <th className="rounded-tr-card pr-5 max-md:hidden">Suburb</th>
                </tr>
              </thead>
              <tbody>
                {rows.map((p) => (
                  <tr
                    key={p.id}
                    data-href
                    tabIndex={0}
                    onClick={() =>
                      navigate({
                        to: "/patients/$patientId",
                        params: { patientId: p.id },
                      })
                    }
                    onKeyDown={(e) =>
                      e.key === "Enter" &&
                      navigate({
                        to: "/patients/$patientId",
                        params: { patientId: p.id },
                      })
                    }
                  >
                    <td className="pl-5">
                      <span className="font-semibold">{patientName(p)}</span>
                      {p.deceased_at ? (
                        <span className="ml-2 text-xs text-stone">
                          (deceased)
                        </span>
                      ) : null}
                    </td>
                    <td className="max-sm:hidden">
                      <Mono className="text-stone">{patientRef(p.id)}</Mono>
                    </td>
                    <td className="max-md:pr-5">
                      {formatDate(p.date_of_birth)}{" "}
                      <span className="text-stone">
                        · {age(p.date_of_birth)}
                      </span>
                    </td>
                    <td className="max-md:hidden">
                      {p.phone ? (
                        <Mono>{p.phone}</Mono>
                      ) : (
                        <span className="text-stone-faint">-</span>
                      )}
                    </td>
                    <td className="pr-5 max-md:hidden">
                      {p.suburb ? (
                        `${p.suburb}${p.state ? ` ${p.state}` : ""}`
                      ) : (
                        <span className="text-stone-faint">-</span>
                      )}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </Card>

      <PatientFormDialog open={adding} onOpenChange={setAdding} />
    </>
  )
}
