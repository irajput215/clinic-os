import { keepPreviousData, useInfiniteQuery } from "@tanstack/react-query"
import { useNavigate } from "@tanstack/react-router"
import { Plus, Search } from "lucide-react"
import { useMemo, useState } from "react"
import { Button } from "@/components/ui/button"
import { patientName, patientPagesQuery, useSearchTerm } from "@/data/patients"
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
  // The search box is local state only: the term is sent in a request body and never put in the URL.
  const [input, setInput] = useState("")
  const q = useSearchTerm(input)
  const patients = useInfiniteQuery({
    ...patientPagesQuery(q),
    // Keep the previous result on screen while the next search loads, so the table does not flash.
    placeholderData: keepPreviousData,
  })
  const [adding, setAdding] = useState(false)

  const rows = useMemo(
    () => patients.data?.pages.flatMap((page) => page.data) ?? [],
    [patients.data],
  )
  const total = patients.data?.pages[0]?.count ?? 0
  const searching = q !== ""
  const pending =
    input.trim() !== q || (patients.isFetching && !patients.isFetchingNextPage)

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

      <div className="mb-4 flex flex-wrap items-center gap-x-3 gap-y-2">
        <div className="relative w-full sm:w-[340px]">
          <Search className="pointer-events-none absolute top-1/2 left-3 size-3.5 -translate-y-1/2 text-stone-faint" />
          <input
            id="patients-search"
            name="patients-search"
            type="search"
            aria-label="Search patients"
            aria-describedby="patients-search-hint"
            placeholder="Name, date of birth or PT- reference"
            autoComplete="off"
            value={input}
            onChange={(e) => setInput(e.target.value)}
            className="h-[38px] w-full rounded-full border border-line bg-paper pr-3 pl-[34px] text-[14px] outline-none placeholder:text-stone-faint focus:border-clay max-lg:h-11 max-lg:text-[16px]"
          />
        </div>
        <span
          id="patients-search-hint"
          className="text-xs text-stone"
          aria-live="polite"
        >
          {patients.isSuccess
            ? searching
              ? `${total} ${total === 1 ? "match" : "matches"}`
              : `${total} ${total === 1 ? "patient" : "patients"}`
            : null}
          {pending && patients.isSuccess ? " · searching…" : null}
        </span>
      </div>

      <Card bodyClassName="-mx-5 -my-[18px]">
        {patients.isPending ? (
          <div className="p-5">
            <SkeletonRows rows={6} />
          </div>
        ) : patients.isError && rows.length === 0 ? (
          <div className="p-5">
            <ErrorState
              error={patients.error}
              onRetry={() => patients.refetch()}
            />
          </div>
        ) : rows.length === 0 ? (
          <EmptyState
            title={
              searching ? "No patients match that search." : "No patients yet."
            }
            body={
              searching
                ? "Search by the start of a name, a date of birth (14/03/1980) or a PT- reference."
                : "Add your first patient to start booking and prescribing."
            }
            action={
              searching ? null : (
                <Button size="sm" onClick={() => setAdding(true)}>
                  <Plus /> Add patient
                </Button>
              )
            }
          />
        ) : (
          <>
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
                    <th className="rounded-tr-card pr-5 max-md:hidden">
                      Suburb
                    </th>
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
            {/* Paging controls only when there is more than one page to speak of. */}
            {patients.hasNextPage || (patients.data?.pages.length ?? 0) > 1 ? (
              <div className="flex flex-wrap items-center justify-between gap-3 border-t border-line px-5 py-3">
                <span className="text-xs text-stone">
                  Showing {rows.length} of {total}
                </span>
                {patients.hasNextPage ? (
                  <Button
                    variant="outline"
                    size="sm"
                    disabled={patients.isFetchingNextPage}
                    onClick={() => patients.fetchNextPage()}
                  >
                    {patients.isFetchingNextPage ? "Loading…" : "Load more"}
                  </Button>
                ) : null}
              </div>
            ) : null}
            {patients.isFetchNextPageError ? (
              <div className="px-5 pb-4">
                <ErrorState
                  error={patients.error}
                  onRetry={() => patients.fetchNextPage()}
                />
              </div>
            ) : null}
          </>
        )}
      </Card>

      <PatientFormDialog open={adding} onOpenChange={setAdding} />
    </>
  )
}
