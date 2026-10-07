import { useInfiniteQuery } from "@tanstack/react-query"
import { Link } from "@tanstack/react-router"
import { Loader2, Plus } from "lucide-react"
import { useState } from "react"
import { Button } from "@/components/ui/button"
import {
  EXPIRING_WINDOW_DAYS,
  REGISTER_FILTER_KEYS,
  REGISTER_FILTERS,
  type RegisterFilter,
  registerQuery,
} from "@/data/approvals"
import {
  Card,
  EmptyState,
  ErrorState,
  PageHeader,
  SkeletonRows,
} from "@/design/primitives"
import { isForbidden } from "@/lib/http"
import { cn } from "@/lib/utils"
import { RecordApprovalDialog } from "./ApprovalDialogs"
import { ApprovalsTable } from "./ApprovalsTable"

const EMPTY: Record<RegisterFilter, { title: string; body?: string }> = {
  attention: {
    title: "Nothing needs action.",
    body: `No approvals are pending verification or expiring within ${EXPIRING_WINDOW_DAYS} days.`,
  },
  active: { title: "No active approvals." },
  pending: { title: "No approvals are waiting for verification." },
  inactive: { title: "No expired or revoked approvals." },
  all: {
    title: "No TGA approvals on file yet.",
    body: "Record one from the TGA letter. A second clinician then verifies it before it can authorise a script.",
  },
}

/**
 * The practice-wide register: `GET /api/v1/tga-approvals`, one filter at a time, newest first, a
 * keyset page at a time. The chip counts are the practice's totals from the same response, so they
 * are right whatever has been loaded.
 */
export function ApprovalsPage({ filter }: { filter: RegisterFilter }) {
  const register = useInfiniteQuery(registerQuery(filter))
  const [recording, setRecording] = useState(false)

  const pages = register.data?.pages ?? []
  const rows = pages.flatMap((p) => p.data)
  const counts = pages[0]?.counts
  const total = counts ? REGISTER_FILTERS[filter].count(counts) : undefined
  const forbidden = register.isError && isForbidden(register.error)

  return (
    <>
      <PageHeader
        title="TGA approvals register"
        subtitle="SAS-B and Authorised Prescriber approvals, held at the grain the law sets: patient, TGA category and dosage form. A script is only sent when an active approval covers its date of service."
        actions={
          <Button onClick={() => setRecording(true)}>
            <Plus /> Record approval
          </Button>
        }
      />

      {forbidden ? null : (
        <nav
          className="mb-4 flex flex-wrap gap-1.5"
          aria-label="Filter approvals"
        >
          {REGISTER_FILTER_KEYS.map((key) => (
            <Link
              key={key}
              to="/approvals"
              search={{ filter: key }}
              aria-current={filter === key ? "page" : undefined}
              className={cn(
                "rounded-full border px-3.5 py-1.5 text-[13px] font-medium transition-colors",
                filter === key
                  ? "border-clay bg-clay-tint text-clay-deep"
                  : "border-line bg-paper text-stone hover:text-ink",
              )}
            >
              {REGISTER_FILTERS[key].label}
              <span className="ml-1.5 inline-block min-w-[1ch] font-mono text-[11px] opacity-70">
                {counts ? REGISTER_FILTERS[key].count(counts) : ""}
              </span>
            </Link>
          ))}
        </nav>
      )}

      <Card bodyClassName="-mx-5 -my-[18px]">
        {register.isPending ? (
          <div className="p-5">
            <SkeletonRows rows={5} />
          </div>
        ) : register.isError && rows.length === 0 ? (
          <div className="p-5">
            <ErrorState
              error={register.error}
              onRetry={() => register.refetch()}
            />
          </div>
        ) : rows.length === 0 ? (
          <EmptyState title={EMPTY[filter].title} body={EMPTY[filter].body} />
        ) : (
          <>
            <ApprovalsTable approvals={rows} showPatient />
            <div className="flex flex-wrap items-center justify-between gap-3 border-t border-line-faint px-5 py-3 text-[13px] text-stone">
              <span aria-live="polite">
                Showing{" "}
                <span className="font-mono text-ink">{rows.length}</span>
                {total !== undefined ? (
                  <>
                    {" "}
                    of <span className="font-mono text-ink">{total}</span>
                  </>
                ) : null}
                , newest first
              </span>
              {register.hasNextPage ? (
                <Button
                  size="sm"
                  variant="outline"
                  disabled={register.isFetchingNextPage}
                  onClick={() => register.fetchNextPage()}
                >
                  {register.isFetchingNextPage ? (
                    <Loader2 className="animate-spin" />
                  ) : null}
                  Show more
                </Button>
              ) : null}
            </div>
            {register.isFetchNextPageError ? (
              <div className="px-5 pb-4">
                <ErrorState
                  error={register.error}
                  onRetry={() => register.fetchNextPage()}
                />
              </div>
            ) : null}
          </>
        )}
      </Card>

      <RecordApprovalDialog open={recording} onOpenChange={setRecording} />
    </>
  )
}
