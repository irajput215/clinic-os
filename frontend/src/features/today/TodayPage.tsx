import { useSuspenseQuery } from "@tanstack/react-query"
import { Link, type LinkProps, useNavigate } from "@tanstack/react-router"
import { categoryShort, formLabel } from "@/data/approvals"
import { type Today, todayQuery } from "@/data/dashboard"
import { formatQuantity } from "@/data/scripts"
import { APPOINTMENT_TYPES, MATCH_REASONS } from "@/data/types"
import {
  Card,
  CardLink,
  EmptyState,
  Mono,
  NotForYourRole,
  PageHeader,
  Pill,
  StatCard,
} from "@/design/primitives"
import {
  AppointmentStatusPill,
  DaysLeftPill,
  GatePill,
  PrescriptionStatePill,
} from "@/features/shared/pills"
import {
  daysBetween,
  formatDate,
  formatLongDay,
  formatTime,
  lastCoveredDay,
} from "@/lib/format"
import { currentUserQuery, displayName } from "@/lib/session"

interface AttentionItem {
  id: string
  title: string
  body: string
  to: LinkProps["to"]
  search?: LinkProps["search"]
}

/** What needs a person today, most urgent first, each linking to where it is fixed (R4). */
const attentionOf = (today: Today): AttentionItem[] => {
  const items: AttentionItem[] = []
  for (const a of today.approvals?.expiring_soon.slice(0, 3) ?? []) {
    const left = daysBetween(today.date, lastCoveredDay(a.valid_to))
    items.push({
      id: `exp-${a.id}`,
      title: `Approval ${left <= 0 ? "ends today" : `ends in ${left} d`} - ${a.patient_display_name ?? "Patient record unavailable"}`,
      body: `${a.approval_reference} · covered through ${formatDate(lastCoveredDay(a.valid_to))}. Start the renewal now so the patient's scripts never block.`,
      to: "/approvals",
      search: { filter: "attention" },
    })
  }
  for (const p of today.approvals?.pending.slice(0, 2) ?? [])
    items.push({
      id: `pend-${p.id}`,
      title: `Approval waiting for verification - ${p.patient_display_name ?? "Patient record unavailable"}`,
      body: `${p.approval_reference} needs a second clinician to check it against the TGA letter before it can authorise a script.`,
      to: "/approvals",
      search: { filter: "pending" },
    })
  for (const s of (today.scripts?.actionable ?? [])
    .filter((s) => s.gate && !s.gate.matched)
    .slice(0, 2))
    items.push({
      id: `blk-${s.id}`,
      title: `Script blocked - ${s.patient_name ?? "Patient record unavailable"}`,
      body: `${s.medicine_name}: ${s.gate?.reason_code ? MATCH_REASONS[s.gate.reason_code] : "no covering approval"}.`,
      to: "/scripts",
    })
  return items
}

const NOT_AVAILABLE = "not available to your role"

export function TodayPage() {
  const { data: me } = useSuspenseQuery(currentUserQuery)
  const { data: today } = useSuspenseQuery(todayQuery)
  const navigate = useNavigate()
  const openPatient = (patientId: string) =>
    navigate({ to: "/patients/$patientId", params: { patientId } })
  const { appointments, scripts, approvals } = today

  const count = (state: string) => scripts?.by_state[state] ?? 0
  const needingAction =
    count("DRAFT") + count("SIGNED") + count("BLOCKED") + count("FAILED")
  const status = (s: string) => appointments?.by_status[s] ?? 0
  const done = status("COMPLETED")
  const toCome = status("BOOKED") + status("CONFIRMED") + status("ARRIVED")
  const attention = attentionOf(today)
  const queuedNotSent =
    scripts && !scripts.transport_configured ? count("QUEUED") : 0

  return (
    <>
      <PageHeader
        title="Today's clinic"
        subtitle={[
          formatLongDay(today.date),
          appointments
            ? `${appointments.data.length} appointment${appointments.data.length === 1 ? "" : "s"}`
            : null,
          `signed in as ${displayName(me)}`,
        ]
          .filter(Boolean)
          .join(" · ")}
      />

      <div className="grid grid-cols-2 gap-3.5 lg:grid-cols-4">
        {appointments ? (
          <StatCard
            to="/calendar"
            value={appointments.data.length}
            label="Appointments today"
            sub={`${done} done · ${toCome} to come`}
          />
        ) : (
          <StatCard value="-" label="Appointments today" sub={NOT_AVAILABLE} />
        )}
        {scripts ? (
          <StatCard
            to="/scripts"
            value={needingAction}
            label="Scripts needing action"
            sub={
              scripts.gate_refused
                ? // The server asks the gate about at most 100 scripts; past that, say "at least".
                  `${scripts.gate_refused}${scripts.gate_checked < needingAction ? "+" : ""} blocked on approval`
                : `${count("DRAFT")} awaiting signature`
            }
            subTone={scripts.gate_refused ? "danger" : "ink"}
          />
        ) : (
          <StatCard
            value="-"
            label="Scripts needing action"
            sub={NOT_AVAILABLE}
          />
        )}
        {approvals ? (
          <>
            <StatCard
              to="/approvals"
              search={{ filter: "pending" }}
              value={approvals.pending_verification}
              label="Approvals to verify"
              sub="four-eyes check"
            />
            <StatCard
              to="/approvals"
              search={{ filter: "attention" }}
              value={approvals.expiring}
              label={`Approvals expiring ≤ ${approvals.expiring_within_days} d`}
              sub={approvals.expiring ? "renewals needed" : "all current"}
              subTone={approvals.expiring ? "danger" : "ok"}
            />
          </>
        ) : (
          <>
            <StatCard
              value="-"
              label="Approvals to verify"
              sub={NOT_AVAILABLE}
            />
            <StatCard
              value="-"
              label={"Approvals expiring ≤ 30 d"}
              sub={NOT_AVAILABLE}
            />
          </>
        )}
      </div>

      <div className="mt-3.5 grid gap-3.5 lg:grid-cols-[minmax(0,1.2fr)_minmax(0,1fr)]">
        <div className="min-w-0 space-y-3.5">
          <Card
            title="Today's schedule"
            action={
              appointments ? (
                <CardLink to="/calendar">Open calendar →</CardLink>
              ) : null
            }
          >
            {!appointments ? (
              <NotForYourRole />
            ) : appointments.data.length === 0 ? (
              <EmptyState title="No appointments today." />
            ) : (
              <div className="-mx-1 overflow-x-auto">
                <table className="data-table">
                  <thead>
                    <tr>
                      <th className="rounded-tl-inner">Time</th>
                      <th>Patient</th>
                      <th className="max-sm:hidden">With</th>
                      <th className="rounded-tr-inner">Status</th>
                    </tr>
                  </thead>
                  <tbody>
                    {appointments.data.map((a) => (
                      <tr
                        key={a.id}
                        data-href
                        tabIndex={0}
                        onClick={() => openPatient(a.patient_id)}
                        onKeyDown={(e) =>
                          e.key === "Enter" && openPatient(a.patient_id)
                        }
                      >
                        <td>
                          <Mono>{formatTime(a.starts_at)}</Mono>
                        </td>
                        <td>
                          <div className="font-medium whitespace-nowrap">
                            {a.patient_name}
                          </div>
                          <div className="text-xs text-stone">
                            {APPOINTMENT_TYPES[a.type].label}
                          </div>
                        </td>
                        <td className="whitespace-nowrap text-stone max-sm:hidden">
                          {a.practitioner_name ?? "-"}
                        </td>
                        <td>
                          <AppointmentStatusPill status={a.status} />
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}
          </Card>

          <Card
            title="Script staging queue"
            action={
              scripts ? <CardLink to="/scripts">Open queue →</CardLink> : null
            }
          >
            {!scripts ? (
              <NotForYourRole />
            ) : (
              <>
                {queuedNotSent ? (
                  <p className="mb-3 rounded-btn bg-info-tint px-3 py-2 text-[13px] text-info-deep">
                    {queuedNotSent} signed script
                    {queuedNotSent === 1 ? " is" : "s are"} queued, not sent: no
                    pharmacy connection is configured yet.
                  </p>
                ) : null}
                {scripts.actionable.length === 0 ? (
                  <EmptyState title="Nothing waiting for review." />
                ) : (
                  <ul className="divide-y divide-line-faint">
                    {scripts.actionable.map((s) => (
                      <li
                        key={s.id}
                        className="flex items-start justify-between gap-3 py-3 first:pt-0 last:pb-0"
                      >
                        <div className="min-w-0">
                          <div className="text-[14.5px]">
                            <span className="font-semibold">
                              {s.patient_name ?? "Patient record unavailable"}
                            </span>
                            <span className="text-stone"> - </span>
                            {s.medicine_name}
                          </div>
                          <div className="mt-0.5 text-xs text-stone">
                            Qty {formatQuantity(s.quantity)} · drafted by{" "}
                            {s.drafted_by_name ?? "-"} · for{" "}
                            {s.prescriber_name ?? "-"}
                          </div>
                        </div>
                        {s.gate && !s.gate.matched ? (
                          <GatePill gate={s.gate} compact />
                        ) : (
                          <PrescriptionStatePill state={s.state} />
                        )}
                      </li>
                    ))}
                  </ul>
                )}
              </>
            )}
          </Card>
        </div>

        <div className="min-w-0 space-y-3.5">
          <Card
            title="Needs attention"
            action={
              approvals ? (
                <CardLink to="/approvals" search={{ filter: "attention" }}>
                  Approvals →
                </CardLink>
              ) : null
            }
          >
            {!approvals && !scripts ? (
              <NotForYourRole />
            ) : attention.length === 0 ? (
              <EmptyState
                title="All clear."
                body="Nothing needs your attention right now."
              />
            ) : (
              <ul className="divide-y divide-line-faint">
                {attention.map((item) => (
                  <li key={item.id} className="py-3 first:pt-0 last:pb-0">
                    <Link
                      to={item.to}
                      search={item.search}
                      className="group block"
                    >
                      <div className="flex items-start justify-between gap-3">
                        <span className="text-[14.5px] font-semibold group-hover:text-clay">
                          {item.title}
                        </span>
                        <Pill tone="clay">Actionable</Pill>
                      </div>
                      <p className="mt-1 text-[13px] leading-relaxed text-stone">
                        {item.body}
                      </p>
                    </Link>
                  </li>
                ))}
              </ul>
            )}
          </Card>

          <Card
            title="SAS-B / AP renewals"
            action={
              approvals ? (
                <CardLink to="/approvals" search={{ filter: "attention" }}>
                  Register →
                </CardLink>
              ) : null
            }
          >
            {!approvals ? (
              <NotForYourRole />
            ) : approvals.expiring_soon.length === 0 ? (
              <EmptyState
                title={`No approvals end in the next ${approvals.expiring_within_days} days.`}
              />
            ) : (
              <div className="overflow-x-auto rounded-inner border border-line">
                <table className="data-table">
                  <thead>
                    <tr>
                      <th>Patient and approval</th>
                      <th className="text-right">Days left</th>
                    </tr>
                  </thead>
                  <tbody>
                    {approvals.expiring_soon.map((a) => (
                      <tr key={a.id}>
                        <td>
                          <div className="font-medium">
                            {a.patient_display_name ??
                              "Patient record unavailable"}
                          </div>
                          <div className="text-xs text-stone">
                            <Mono>{a.approval_reference}</Mono> ·{" "}
                            {categoryShort(a.tga_category)} ·{" "}
                            {formLabel(a.dosage_form)}
                          </div>
                        </td>
                        <td className="text-right">
                          <DaysLeftPill
                            days={daysBetween(
                              today.date,
                              lastCoveredDay(a.valid_to),
                            )}
                          />
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}
          </Card>
        </div>
      </div>
    </>
  )
}
