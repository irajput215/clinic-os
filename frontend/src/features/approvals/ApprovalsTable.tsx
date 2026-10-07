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
      {/* `relative`: the header's sr-only label is absolutely positioned, and without a positioned
          scroller it escapes the clip and scrolls the whole page sideways at phone width. */}
      <div className="relative overflow-x-auto">
        <table className="data-table">
          <thead>
            <tr>
              {showPatient ? <th className="pl-5">Patient</th> : null}
              <th className={showPatient ? "" : "pl-5"}>Reference</th>
              <th>Grain</th>
              <th title="As printed on the TGA letter. The end date itself is not covered (D-006).">
                Valid (letter)
              </th>
              <th>Status</th>
              <th className="pr-5 text-right">
                <span className="sr-only">Actions</span>
              </th>
            </tr>
          </thead>
          <tbody>
            {approvals.map((a) => {
              const daysLeft = daysBetween(today, lastCoveredDay(a.valid_to))
              return (
                <tr key={a.id}>
                  {showPatient ? (
                    <td className="pl-5">
                      {a.patient_display_name ? (
                        <Link
                          to="/patients/$patientId"
                          params={{ patientId: a.patient_id }}
                          search={{ tab: "approvals" }}
                          className="font-semibold whitespace-nowrap hover:text-clay"
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
                    </td>
                  ) : null}
                  <td className={showPatient ? "" : "pl-5"}>
                    <Mono>{a.approval_reference}</Mono>
                  </td>
                  <td className="whitespace-nowrap">
                    <span className="font-medium">
                      {categoryShort(a.tga_category)}
                    </span>
                    <span className="text-stone">
                      {" "}
                      · {formLabel(a.dosage_form)}
                    </span>
                  </td>
                  <td className="whitespace-nowrap">
                    <span className="text-stone">
                      {formatDate(a.valid_from)} →
                    </span>{" "}
                    {formatDate(a.valid_to)}
                    {a.state === "ACTIVE" && daysLeft <= 30 ? (
                      <span className="ml-2">
                        <DaysLeftPill days={daysLeft} />
                      </span>
                    ) : null}
                  </td>
                  <td>
                    <ApprovalStatePill state={a.state} />
                  </td>
                  <td className="pr-5 text-right whitespace-nowrap">
                    {a.state === "PENDING" ? (
                      <Button size="sm" onClick={() => setVerifying(a)}>
                        Verify
                      </Button>
                    ) : null}
                    {a.state === "PENDING" || a.state === "ACTIVE" ? (
                      <Button
                        size="sm"
                        variant="ghost"
                        className="ml-1"
                        onClick={() => setRevoking(a)}
                      >
                        Revoke
                      </Button>
                    ) : null}
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
