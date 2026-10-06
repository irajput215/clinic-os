import { STATUS_LABEL } from "@/data/appointments"
import { SCRIPT_STATE_LABEL } from "@/data/scripts"
import {
  type AppointmentStatus,
  type ApprovalState,
  MATCH_REASONS,
  MATCH_REASONS_SHORT,
  type ScriptState,
  type TgaMatchResponse,
} from "@/data/types"
import { Pill, type Tone } from "@/design/primitives"
import { formatDate, lastCoveredDay } from "@/lib/format"

const APPT_TONE: Record<AppointmentStatus, Tone> = {
  BOOKED: "neutral",
  CONFIRMED: "purple",
  ARRIVED: "info",
  COMPLETED: "ok",
  CANCELLED: "danger",
  NO_SHOW: "warn",
}

export const AppointmentStatusPill = ({
  status,
}: {
  status: AppointmentStatus
}) => <Pill tone={APPT_TONE[status]}>{STATUS_LABEL[status]}</Pill>

const SCRIPT_TONE: Record<ScriptState, Tone> = {
  AWAITING_REVIEW: "warn",
  SIGNED: "info",
  SENT: "info",
  BLOCKED: "danger",
  REQUIRES_RECONCILIATION: "purple",
  CANCELLED: "neutral",
}

export const ScriptStatePill = ({ state }: { state: ScriptState }) => (
  <Pill tone={SCRIPT_TONE[state]}>{SCRIPT_STATE_LABEL[state]}</Pill>
)

const APPROVAL_TONE: Record<ApprovalState, Tone> = {
  PENDING: "warn",
  ACTIVE: "ok",
  EXPIRED: "neutral",
  REJECTED: "danger",
  REVOKED: "danger",
  SUPERSEDED: "neutral",
}

const APPROVAL_LABEL: Record<ApprovalState, string> = {
  PENDING: "Pending verification",
  ACTIVE: "Active",
  EXPIRED: "Expired",
  REJECTED: "Rejected",
  REVOKED: "Revoked",
  SUPERSEDED: "Superseded",
}

export const ApprovalStatePill = ({ state }: { state: ApprovalState }) => (
  <Pill tone={APPROVAL_TONE[state]}>{APPROVAL_LABEL[state]}</Pill>
)

/** The safety gate's answer, as the queue shows it: "Covered through 14 Mar 2027" or the refusal. */
export const GatePill = ({
  gate,
  compact = false,
}: {
  gate: TgaMatchResponse | null
  /** Short refusal wording for dense lists; the full sentence is in the tooltip. */
  compact?: boolean
}) => {
  if (!gate) return <Pill tone="neutral">Not checked</Pill>
  if (gate.matched && gate.validity_interval)
    return (
      <Pill
        tone="ok"
        title="Checked against the date of service, half-open window"
      >
        Covered through{" "}
        {formatDate(lastCoveredDay(gate.validity_interval.valid_to))}
      </Pill>
    )
  const code = gate.reason_code
  return (
    <Pill
      tone="danger"
      title={code ? `${MATCH_REASONS[code]} (${code})` : undefined}
    >
      {code
        ? compact
          ? `Blocked · ${MATCH_REASONS_SHORT[code]}`
          : MATCH_REASONS[code]
        : "Blocked"}
    </Pill>
  )
}

/** "-25 days" / "14 days" countdown chip for approval expiry. */
export const DaysLeftPill = ({ days }: { days: number }) => (
  <Pill tone={days <= 7 ? "danger" : days <= 30 ? "warn" : "ok"}>
    <span className="font-mono">
      {days <= 0 ? "today" : `${days} day${days === 1 ? "" : "s"}`}
    </span>
  </Pill>
)
