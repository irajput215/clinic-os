import { queryOptions } from "@tanstack/react-query"
import { previewMatch } from "@/data/preview/gate"
import { readPreview } from "@/data/preview/store"
import type { TodaySummary } from "@/data/types"
import { clinicDateOf } from "@/lib/clinic-time"
import {
  clinicToday,
  daysBetween,
  formatDate,
  lastCoveredDay,
} from "@/lib/format"
import { MATCH_REASONS } from "./types"

/**
 * The Today page in one round trip. PREVIEW ONLY: the proposed `GET /api/v1/dashboard/today`
 * (docs2/sdlc/08-today/api.md) aggregates these server-side in a single query.
 */
const EXPIRY_HORIZON_DAYS = 30

export const todaySummary = async (): Promise<TodaySummary> => {
  const s = await readPreview()
  const today = clinicToday()
  const names = new Map<string, string>()
  for (const a of s.appointments) names.set(a.patient_id, a.patient_name)
  for (const x of s.scripts) names.set(x.patient_id, x.patient_name)

  const appointments = s.appointments
    .filter((a) => clinicDateOf(a.starts_at) === today)
    .sort((a, b) => a.starts_at.localeCompare(b.starts_at))
  // Gate answers are evaluated now, against today's approvals, as the server would.
  const awaiting = s.scripts
    .filter((x) => x.state === "AWAITING_REVIEW" || x.state === "BLOCKED")
    .map((x) => ({ ...x, gate: previewMatch(s.approvals, x) }))
  const expiring = s.approvals
    .filter((a) => a.state === "ACTIVE")
    .map((a) => ({
      ...a,
      patient_name: names.get(a.patient_id) ?? "Patient",
      days_left: daysBetween(today, lastCoveredDay(a.valid_to)),
    }))
    .filter((a) => a.days_left <= EXPIRY_HORIZON_DAYS)
    .sort((a, b) => a.days_left - b.days_left)

  const attention: TodaySummary["attention"] = []
  for (const a of expiring.slice(0, 3))
    attention.push({
      id: `exp-${a.id}`,
      title: `Approval ${a.days_left <= 0 ? "expires today" : `expires in ${a.days_left} d`} - ${a.patient_name}`,
      body: `${a.approval_reference} · covered through ${formatDate(lastCoveredDay(a.valid_to))}. Start the renewal now so the patient's scripts never block.`,
      href: "/approvals",
    })
  for (const p of s.approvals.filter((x) => x.state === "PENDING").slice(0, 2))
    attention.push({
      id: `pend-${p.id}`,
      title: `Approval waiting for verification - ${names.get(p.patient_id) ?? "Patient"}`,
      body: `${p.approval_reference} needs a second clinician to check it against the TGA letter before it can authorise a script.`,
      href: "/approvals",
    })
  for (const x of awaiting.filter((x) => x.gate && !x.gate.matched).slice(0, 2))
    attention.push({
      id: `blk-${x.id}`,
      title: `Script blocked - ${x.patient_name}`,
      body: `${x.product_name}: ${MATCH_REASONS[x.gate!.reason_code!] ?? x.gate!.reason_code}.`,
      href: "/scripts",
    })

  return {
    date: today,
    appointments,
    scripts_awaiting: awaiting,
    scripts_blocked: awaiting.filter((x) => x.gate && !x.gate.matched).length,
    approvals_expiring: expiring,
    attention,
  }
}

export const todayQuery = queryOptions({
  queryKey: ["dashboard", "today"],
  queryFn: todaySummary,
  staleTime: 10_000,
})
