import { Link } from "@tanstack/react-router"
import { Button } from "@/components/ui/button"
import { categoryShort, formLabel } from "@/data/approvals"
import type { Prescription } from "@/data/scripts"
import { Mono } from "@/design/primitives"
import { GatePill, PrescriptionStatePill } from "@/features/shared/pills"
import { formatDayMonthTime, patientRef } from "@/lib/format"
import { cn } from "@/lib/utils"

/** What the person looking at a script can do with it, decided by the page from the server's data. */
export type ScriptAction = "sign" | "send" | null

/** One script needing action: who, what, the gate's answer now, and the next step. */
export function ScriptCard({
  script: s,
  action,
  onReview,
  showPatientLink = true,
}: {
  script: Prescription
  action: ScriptAction
  onReview: () => void
  showPatientLink?: boolean
}) {
  const blocked = s.gate !== null && !s.gate.matched
  return (
    <article
      className={cn(
        "flex flex-col gap-3 rounded-inner border border-line border-l-[3px] bg-paper px-5 py-4 shadow-card sm:flex-row sm:items-center",
        blocked || s.state === "BLOCKED" || s.state === "FAILED"
          ? "border-l-danger"
          : "border-l-warn",
      )}
    >
      <div className="min-w-0 flex-1">
        <div className="flex flex-wrap items-center gap-2">
          <span className="text-[16px] font-semibold">
            {s.patient_name ?? "Patient"}
          </span>
          <Mono className="text-stone">{patientRef(s.patient_id)}</Mono>
          <PrescriptionStatePill state={s.state} />
          <GatePill gate={s.gate} />
        </div>
        <div className="mt-1 text-[14.5px]">
          <span className="font-semibold">{s.medicine_name}</span>
          <span className="text-stone">
            {" "}
            · {categoryShort(s.tga_category)} · {formLabel(s.dosage_form)} · qty{" "}
            {s.quantity} · {s.repeats} repeat{s.repeats === 1 ? "" : "s"} ·{" "}
          </span>
          <span className="text-stone">{s.dose_instruction}</span>
        </div>
        <div className="mt-0.5 text-[13px] text-stone">
          Drafted {formatDayMonthTime(s.created_at)} by{" "}
          {s.drafted_by_name ?? "a colleague"} → for{" "}
          {s.prescriber_name ?? "the prescriber"}
        </div>
        <dl className="mt-2.5 rounded-btn bg-oat px-3.5 py-2.5 text-[13px] leading-relaxed">
          <div>
            <dt className="inline font-semibold">Triage outcome: </dt>
            <dd className="inline">{s.triage_outcome}</dd>
          </div>
          <div>
            <dt className="inline font-semibold">
              Conventional therapy first:{" "}
            </dt>
            <dd className="inline">{s.conventional_therapy}</dd>
          </div>
        </dl>
      </div>
      <div className="flex shrink-0 items-center gap-2 sm:flex-col sm:items-end">
        {action === "sign" ? (
          <Button size="sm" onClick={onReview}>
            Review & sign
          </Button>
        ) : action === "send" ? (
          <Button size="sm" onClick={onReview}>
            Review & send
          </Button>
        ) : (
          <span className="text-[13px] text-stone">
            Assigned to {s.prescriber_name ?? "the prescriber"}
          </span>
        )}
        {showPatientLink ? (
          <Link
            to="/patients/$patientId"
            params={{ patientId: s.patient_id }}
            search={{ tab: "scripts" }}
            className="px-2 text-[13px] font-medium text-stone hover:text-ink"
          >
            Open record
          </Link>
        ) : null}
      </div>
    </article>
  )
}
