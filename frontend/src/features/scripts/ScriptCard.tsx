import { Link } from "@tanstack/react-router"
import { Button } from "@/components/ui/button"
import type { Script } from "@/data/types"
import { Mono, Pill } from "@/design/primitives"
import { GatePill, ScriptStatePill } from "@/features/shared/pills"
import { formatDayMonthTime, patientRef } from "@/lib/format"
import { cn } from "@/lib/utils"

/** One staged script: who, what, the gate's answer, and the doctor's next action. */
export function ScriptCard({
  script: s,
  canSign,
  onReview,
  showPatientLink = true,
}: {
  script: Script
  canSign: boolean
  onReview: () => void
  showPatientLink?: boolean
}) {
  const blocked = s.gate !== null && !s.gate.matched
  return (
    <article
      className={cn(
        "flex flex-col gap-3 rounded-inner border border-line border-l-[3px] bg-paper px-5 py-4 shadow-card sm:flex-row sm:items-center",
        blocked ? "border-l-danger" : "border-l-warn",
      )}
    >
      <div className="min-w-0 flex-1">
        <div className="flex flex-wrap items-center gap-2">
          <span className="text-[16px] font-semibold">{s.patient_name}</span>
          <Mono className="text-stone">{patientRef(s.patient_id)}</Mono>
          {s.state === "BLOCKED" ? (
            <ScriptStatePill state={s.state} />
          ) : (
            <Pill tone="warn">Awaiting review</Pill>
          )}
          <GatePill gate={s.gate} />
        </div>
        <div className="mt-1 text-[14.5px]">
          <span className="font-semibold">{s.product_name}</span>
          <span className="text-stone">
            {" "}
            · {s.quantity} · {s.repeats} repeat{s.repeats === 1 ? "" : "s"} ·{" "}
          </span>
          <span className="text-stone">{s.directions}</span>
        </div>
        <div className="mt-0.5 text-[13px] text-stone">
          Drafted {formatDayMonthTime(s.created_at)} by {s.drafted_by_name} →
          for {s.prescriber_name}
        </div>
        {s.triage_outcome || s.conventional_therapy ? (
          <dl className="mt-2.5 rounded-btn bg-oat px-3.5 py-2.5 text-[13px] leading-relaxed">
            {s.triage_outcome ? (
              <div>
                <dt className="inline font-semibold">Triage outcome: </dt>
                <dd className="inline">{s.triage_outcome}</dd>
              </div>
            ) : null}
            {s.conventional_therapy ? (
              <div>
                <dt className="inline font-semibold">
                  Conventional therapy first:{" "}
                </dt>
                <dd className="inline">{s.conventional_therapy}</dd>
              </div>
            ) : null}
          </dl>
        ) : null}
      </div>
      <div className="flex shrink-0 items-center gap-2 sm:flex-col sm:items-end">
        {canSign ? (
          <Button size="sm" onClick={onReview}>
            Review & sign
          </Button>
        ) : (
          <span className="text-[13px] text-stone">
            Assigned to {s.prescriber_name}
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
