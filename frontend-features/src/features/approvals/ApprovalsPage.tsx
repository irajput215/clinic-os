import { useQuery } from "@tanstack/react-query"
import { Plus } from "lucide-react"
import { useMemo, useState } from "react"
import { Button } from "@/components/ui/button"
import { approvalsQuery } from "@/data/approvals"
import { isPreview } from "@/data/capabilities"
import { patientName, patientsQuery } from "@/data/patients"
import type { TgaApproval } from "@/data/types"
import {
  Card,
  EmptyState,
  ErrorState,
  PageHeader,
  PreviewBanner,
  SkeletonRows,
} from "@/design/primitives"
import { clinicToday, daysBetween, lastCoveredDay } from "@/lib/format"
import { cn } from "@/lib/utils"
import { RecordApprovalDialog } from "./ApprovalDialogs"
import { ApprovalsTable } from "./ApprovalsTable"

const FILTERS = {
  attention: {
    label: "Needs action",
    test: (a: TgaApproval, today: string) =>
      a.state === "PENDING" ||
      (a.state === "ACTIVE" &&
        daysBetween(today, lastCoveredDay(a.valid_to)) <= 30),
  },
  active: { label: "Active", test: (a: TgaApproval) => a.state === "ACTIVE" },
  pending: {
    label: "Pending",
    test: (a: TgaApproval) => a.state === "PENDING",
  },
  inactive: {
    label: "Expired & revoked",
    test: (a: TgaApproval) => !["ACTIVE", "PENDING"].includes(a.state),
  },
  all: { label: "All", test: () => true },
} as const
type FilterKey = keyof typeof FILTERS

export function ApprovalsPage() {
  const approvals = useQuery(approvalsQuery)
  const patients = useQuery(patientsQuery)
  const [filter, setFilter] = useState<FilterKey>("attention")
  const [recording, setRecording] = useState(false)
  const today = clinicToday()

  const names = useMemo(
    () =>
      new Map((patients.data?.data ?? []).map((p) => [p.id, patientName(p)])),
    [patients.data],
  )
  const rows = (approvals.data ?? [])
    .filter((a) => FILTERS[filter].test(a, today))
    .sort((a, b) => a.valid_to.localeCompare(b.valid_to))

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
      {isPreview("tgaApprovals") ? (
        <PreviewBanner what="Approvals here are sample grants for your real patients." />
      ) : null}

      <div
        className="mb-4 flex flex-wrap gap-1.5"
        role="tablist"
        aria-label="Filter approvals"
      >
        {(Object.keys(FILTERS) as FilterKey[]).map((key) => {
          const count = (approvals.data ?? []).filter((a) =>
            FILTERS[key].test(a, today),
          ).length
          return (
            <button
              key={key}
              type="button"
              role="tab"
              aria-selected={filter === key}
              onClick={() => setFilter(key)}
              className={cn(
                "rounded-full border px-3.5 py-1.5 text-[13px] font-medium transition-colors",
                filter === key
                  ? "border-clay bg-clay-tint text-clay-deep"
                  : "border-line bg-paper text-stone hover:text-ink",
              )}
            >
              {FILTERS[key].label}
              <span className="ml-1.5 font-mono text-[11px] opacity-70">
                {count}
              </span>
            </button>
          )
        })}
      </div>

      <Card bodyClassName="-mx-5 -my-[18px]">
        {approvals.isPending ? (
          <div className="p-5">
            <SkeletonRows rows={5} />
          </div>
        ) : approvals.isError ? (
          <div className="p-5">
            <ErrorState
              error={approvals.error}
              onRetry={() => approvals.refetch()}
            />
          </div>
        ) : rows.length === 0 ? (
          <EmptyState
            title={
              filter === "attention"
                ? "Nothing needs action."
                : "No approvals here."
            }
            body={
              filter === "attention"
                ? "No approvals are pending verification or expiring within 30 days."
                : undefined
            }
          />
        ) : (
          <ApprovalsTable approvals={rows} patientNames={names} />
        )}
      </Card>

      <RecordApprovalDialog open={recording} onOpenChange={setRecording} />
    </>
  )
}
