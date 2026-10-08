import { Link } from "@tanstack/react-router"
import { useState } from "react"
import { Button } from "@/components/ui/button"
import { categoryShort, formLabel } from "@/data/approvals"
import type { TgaApproval } from "@/data/types"
import { Mono } from "@/design/primitives"
import { ApprovalStatePill, DaysLeftPill } from "@/features/shared/pills"
import {
  clinicToday,
  daysBetween,
  formatDate,
  lastCoveredDay,
} from "@/lib/format"
import { RevokeApprovalDialog, VerifyApprovalDialog } from "./ApprovalDialogs"

export function ApprovalsTable({
  approvals,
  showPatient = false,
}: {
  approvals: (TgaApproval & { patient_display_name?: string | null })[]
  /** The register's Patient column: each row links to the record by the name the API returned. */
  showPatient?: boolean
}) {
  const [verifying, setVerifying] = useState<TgaApproval | null>(null)
  const [revoking, setRevoking] = useState<TgaApproval | null>(null)
  const today = clinicToday()

  return (
    <>
      {/* Priority columns: below 1280 px the grain moves under the reference, and below 1024 px
          (touch-sized) the row is its first column, with everything else stacked inside it, and
          its actions. The table never needs a sideways scroll to reach Verify or Revoke.
          `relative`: the header's sr-only label is absolutely positioned, and without a positioned
          scroller it escapes the clip and scrolls the whole page sideways at phone width. */}
      <div className="relative overflow-x-auto">
        <table className="data-table">
          <thead>
            <tr>
              {showPatient ? <th className="pl-5">Patient</th> : null}
              <th className={showPatient ? "max-lg:hidden" : "pl-5"}>
                Reference
              </th>
              <th className="max-xl:hidden">Grain</th>
              <th
                className="max-lg:hidden"
                title="As printed on the TGA letter. The end date itself is not covered (D-006)."
              >
                Valid (letter)
              </th>
              <th className="max-lg:hidden">Status</th>
              <th className="pr-5 text-right">
                <span className="sr-only">Actions</span>
              </th>
            </tr>
          </thead>
          <tbody>
            {approvals.map((a) => {
              const daysLeft = daysBetween(today, lastCoveredDay(a.valid_to))
              const grain = (
                <>
                  <span className="font-medium">
                    {categoryShort(a.tga_category)}
                  </span>
                  <span className="text-stone">
                    {" "}
                    · {formLabel(a.dosage_form)}
                  </span>
                </>
              )
              const validity = (
                <>
                  <span className="text-stone">
                    {formatDate(a.valid_from)} →
                  </span>{" "}
                  {formatDate(a.valid_to)}
                </>
              )
              const daysPill =
                a.state === "ACTIVE" && daysLeft <= 30 ? (
                  <DaysLeftPill days={daysLeft} />
                ) : null
              // What the hidden columns hold, stacked in the first column below 1024 px.
              const stacked = (
                <div className="mt-1 space-y-1 text-[13px] lg:hidden">
                  {showPatient ? (
                    <div>
                      <Mono>{a.approval_reference}</Mono>
                    </div>
                  ) : null}
                  <div>{grain}</div>
                  <div>{validity}</div>
                  <div className="flex flex-wrap gap-1.5">
                    <ApprovalStatePill state={a.state} />
                    {daysPill}
                  </div>
                </div>
              )
              return (
                <tr key={a.id}>
                  {showPatient ? (
                    <td className="pl-5">
                      {a.patient_display_name ? (
                        <Link
                          to="/patients/$patientId"
                          params={{ patientId: a.patient_id }}
                          search={{ tab: "approvals" }}
                          className="font-semibold whitespace-nowrap hover:text-clay max-lg:inline-flex max-lg:min-h-11 max-lg:items-center"
                        >
                          {a.patient_display_name}
                        </Link>
                      ) : (
                        // The patient's record is no longer readable; the approval is still
                        // regulatory history, so the row stays, unlinked.
                        <span className="whitespace-nowrap text-stone italic">
                          Record removed
                        </span>
                      )}
                      {stacked}
                    </td>
                  ) : null}
                  <td className={showPatient ? "max-lg:hidden" : "pl-5"}>
                    <Mono>{a.approval_reference}</Mono>
                    <div className="mt-0.5 text-[13px] whitespace-nowrap max-lg:hidden xl:hidden">
                      {grain}
                    </div>
                    {showPatient ? null : stacked}
                  </td>
                  <td className="whitespace-nowrap max-xl:hidden">{grain}</td>
                  <td className="whitespace-nowrap max-lg:hidden">
                    {validity}
                    {daysPill ? <span className="ml-2">{daysPill}</span> : null}
                  </td>
                  <td className="max-lg:hidden">
                    <ApprovalStatePill state={a.state} />
                  </td>
                  <td className="pr-5 text-right whitespace-nowrap">
                    <div className="inline-flex items-center gap-1 max-sm:flex-col max-sm:items-stretch">
                      {a.state === "PENDING" ? (
                        <Button size="sm" onClick={() => setVerifying(a)}>
                          Verify
                        </Button>
                      ) : null}
                      {a.state === "PENDING" || a.state === "ACTIVE" ? (
                        <Button
                          size="sm"
                          variant="ghost"
                          onClick={() => setRevoking(a)}
                        >
                          Revoke
                        </Button>
                      ) : null}
                    </div>
                  </td>
                </tr>
              )
            })}
          </tbody>
        </table>
      </div>
      <VerifyApprovalDialog
        approval={verifying}
        onOpenChange={(o) => !o && setVerifying(null)}
      />
      <RevokeApprovalDialog
        approval={revoking}
        onOpenChange={(o) => !o && setRevoking(null)}
      />
    </>
  )
}
