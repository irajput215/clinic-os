import { useQuery, useSuspenseQuery } from "@tanstack/react-query"
import { Link, useNavigate } from "@tanstack/react-router"
import { categoryShort, formLabel } from "@/data/approvals"
import { todayQuery } from "@/data/dashboard"
import { previewPractitionersQuery } from "@/data/preview/practitioners"
import { APPOINTMENT_TYPES } from "@/data/types"
import {
  Card,
  CardLink,
  EmptyState,
  Mono,
  PageHeader,
  Pill,
  PreviewBanner,
  StatCard,
} from "@/design/primitives"
import {
  AppointmentStatusPill,
  DaysLeftPill,
  GatePill,
} from "@/features/shared/pills"
import { formatLongDay, formatTime } from "@/lib/format"
import { currentUserQuery, displayName } from "@/lib/session"

export function TodayPage() {
  const { data: me } = useSuspenseQuery(currentUserQuery)
  const { data: today } = useSuspenseQuery(todayQuery)
  const { data: practitioners = [] } = useQuery(previewPractitionersQuery)
  const navigate = useNavigate()
  const withName = (id: string) =>
    practitioners.find((p) => p.id === id)?.name ?? "-"

  const done = today.appointments.filter((a) => a.status === "COMPLETED").length
  const upcoming = today.appointments.filter(
    (a) => a.status === "BOOKED" || a.status === "CONFIRMED",
  ).length

  return (
    <>
      <PageHeader
        title="Today's clinic"
        subtitle={`${formatLongDay(new Date())} · ${today.appointments.length} appointments · signed in as ${displayName(me)}`}
      />
      <PreviewBanner what="Appointments, scripts and approvals on this page are sample records attached to your real patients." />

      <div className="grid grid-cols-2 gap-3.5 lg:grid-cols-4">
        <StatCard
          to="/calendar"
          value={today.appointments.length}
          label="Appointments today"
          sub={`${done} done · ${upcoming} to come`}
        />
        <StatCard
          to="/scripts"
          value={today.scripts_awaiting.length}
          label="Scripts needing action"
          sub={
            today.scripts_blocked
              ? `${today.scripts_blocked} blocked on approval`
              : "staging queue"
          }
          subTone={today.scripts_blocked ? "danger" : "ink"}
        />
        <StatCard
          to="/approvals"
          value={today.attention.filter((a) => a.id.startsWith("pend-")).length}
          label="Approvals to verify"
          sub="four-eyes check"
        />
        <StatCard
          to="/approvals"
          value={today.approvals_expiring.length}
          label={"Approvals expiring ≤\u00a030\u00a0d"}
          sub={
            today.approvals_expiring.length ? "renewals needed" : "all current"
          }
          subTone={today.approvals_expiring.length ? "danger" : "ok"}
        />
      </div>

      <div className="mt-3.5 grid gap-3.5 lg:grid-cols-[minmax(0,1.2fr)_minmax(0,1fr)]">
        <div className="min-w-0 space-y-3.5">
          <Card
            title="Today's schedule"
            action={<CardLink to="/calendar">Open calendar →</CardLink>}
          >
            {today.appointments.length === 0 ? (
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
                    {today.appointments.map((a) => (
                      <tr
                        key={a.id}
                        data-href
                        onClick={() =>
                          a.patient_id.startsWith("intake-")
                            ? navigate({ to: "/calendar" })
                            : navigate({
                                to: "/patients/$patientId",
                                params: { patientId: a.patient_id },
                              })
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
                          {withName(a.practitioner_id)}
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
            action={<CardLink to="/scripts">Open queue →</CardLink>}
          >
            {today.scripts_awaiting.length === 0 ? (
              <EmptyState title="Nothing waiting for review." />
            ) : (
              <ul className="divide-y divide-line-faint">
                {today.scripts_awaiting.slice(0, 8).map((s) => (
                  <li
                    key={s.id}
                    className="flex items-start justify-between gap-3 py-3 first:pt-0 last:pb-0"
                  >
                    <div className="min-w-0">
                      <div className="text-[14.5px]">
                        <span className="font-semibold">{s.patient_name}</span>
                        <span className="text-stone"> - </span>
                        {s.product_name}
                      </div>
                      <div className="mt-0.5 text-xs text-stone">
                        Drafted by {s.drafted_by_name} · for {s.prescriber_name}
                      </div>
                    </div>
                    {s.gate && !s.gate.matched ? (
                      <GatePill gate={s.gate} compact />
                    ) : (
                      <Pill tone="warn">Awaiting review</Pill>
                    )}
                  </li>
                ))}
              </ul>
            )}
          </Card>
        </div>

        <div className="min-w-0 space-y-3.5">
          <Card
            title="Needs attention"
            action={<CardLink to="/approvals">Approvals →</CardLink>}
          >
            {today.attention.length === 0 ? (
              <EmptyState
                title="All clear."
                body="Nothing needs your attention right now."
              />
            ) : (
              <ul className="divide-y divide-line-faint">
                {today.attention.map((item) => (
                  <li key={item.id} className="py-3 first:pt-0 last:pb-0">
                    <Link to={item.href} className="group block">
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
            action={<CardLink to="/approvals">Register →</CardLink>}
          >
            {today.approvals_expiring.length === 0 ? (
              <EmptyState title="No approvals expire in the next 30 days." />
            ) : (
              <div className="overflow-hidden rounded-inner border border-line">
                <table className="data-table">
                  <thead>
                    <tr>
                      <th>Patient</th>
                      <th>Approval</th>
                      <th className="text-right">Expires</th>
                    </tr>
                  </thead>
                  <tbody>
                    {today.approvals_expiring.map((a) => (
                      <tr key={a.id}>
                        <td className="font-medium whitespace-nowrap">
                          {a.patient_name}
                        </td>
                        <td>
                          <Mono>{a.approval_reference}</Mono>
                          <div className="text-xs text-stone">
                            {categoryShort(a.tga_category)} ·{" "}
                            {formLabel(a.dosage_form)}
                          </div>
                        </td>
                        <td className="text-right">
                          <DaysLeftPill days={a.days_left} />
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
