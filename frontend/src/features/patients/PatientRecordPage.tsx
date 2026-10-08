import { useQuery, useSuspenseQuery } from "@tanstack/react-query"
import { Link, useNavigate } from "@tanstack/react-router"
import { ChevronLeft, Pencil, Plus } from "lucide-react"
import { useState } from "react"
import { Button } from "@/components/ui/button"
import {
  patientAppointmentsQuery,
  practitionersQuery,
} from "@/data/appointments"
import { patientApprovalsQuery } from "@/data/approvals"
import { actionLabel, resourceAuditQuery } from "@/data/audit"
import { patientName, patientQuery } from "@/data/patients"
import { isActionable, scriptsQuery } from "@/data/scripts"
import { APPOINTMENT_TYPES, type Script } from "@/data/types"
import {
  Card,
  EmptyState,
  ErrorState,
  Mono,
  PreviewBanner,
  SkeletonRows,
} from "@/design/primitives"
import { RecordApprovalDialog } from "@/features/approvals/ApprovalDialogs"
import { ApprovalsTable } from "@/features/approvals/ApprovalsTable"
import { ScriptCard } from "@/features/scripts/ScriptCard"
import {
  ReviewSignDialog,
  StageScriptDialog,
} from "@/features/scripts/ScriptDialogs"
import { AppointmentStatusPill, ScriptStatePill } from "@/features/shared/pills"
import {
  age,
  formatDate,
  formatDayMonth,
  formatDayMonthTime,
  formatTime,
  patientRef,
} from "@/lib/format"
import { currentUserQuery } from "@/lib/session"
import { cn } from "@/lib/utils"
import { NotesTab } from "./NotesTab"
import { PatientFormDialog } from "./PatientFormDialog"
import { PATIENT_TAB_KEYS, PATIENT_TABS, type PatientTab } from "./tabs"

const SEX_LABEL: Record<string, string> = {
  FEMALE: "Female",
  MALE: "Male",
  INTERSEX: "Intersex",
  UNKNOWN: "Not stated",
}

export function PatientRecordPage({
  patientId,
  tab,
}: {
  patientId: string
  tab: PatientTab
}) {
  const { data: patient } = useSuspenseQuery(patientQuery(patientId))
  const navigate = useNavigate()
  const [editing, setEditing] = useState(false)

  return (
    <>
      <Link
        to="/patients"
        className="mb-3 inline-flex items-center gap-1 text-[13px] font-medium text-stone hover:text-ink"
      >
        <ChevronLeft className="size-3.5" /> Patients
      </Link>
      <header className="mb-5 flex flex-wrap items-end justify-between gap-4">
        <div className="min-w-0">
          <h1 className="font-serif text-[31px] leading-[1.1] font-medium tracking-[-0.015em]">
            {patientName(patient)}
          </h1>
          <p className="mt-1.5 flex flex-wrap items-center gap-x-2 gap-y-1 text-sm text-stone">
            <Mono>{patientRef(patient.id)}</Mono>
            <span>·</span>
            <span>
              {formatDate(patient.date_of_birth)} ({age(patient.date_of_birth)})
            </span>
            {patient.sex_at_birth ? (
              <>
                <span>·</span>
                <span>
                  {SEX_LABEL[patient.sex_at_birth] ?? patient.sex_at_birth}
                </span>
              </>
            ) : null}
            {patient.deceased_at ? (
              <span className="rounded-full bg-fill px-2 py-0.5 text-xs">
                Deceased
              </span>
            ) : null}
          </p>
        </div>
        <Button variant="outline" onClick={() => setEditing(true)}>
          <Pencil /> Edit details
        </Button>
      </header>

      <div
        role="tablist"
        aria-label="Patient record"
        className="mb-5 flex gap-1 overflow-x-auto border-line border-b"
      >
        {PATIENT_TAB_KEYS.map((key) => (
          <button
            key={key}
            type="button"
            role="tab"
            aria-selected={tab === key}
            onClick={() =>
              navigate({ to: ".", search: { tab: key }, replace: true })
            }
            className={cn(
              "-mb-px shrink-0 border-b-2 px-3 py-2.5 text-[13.5px] font-medium transition-colors",
              tab === key
                ? "border-clay text-clay-deep"
                : "border-transparent text-stone hover:text-ink",
            )}
          >
            {PATIENT_TABS[key]}
          </button>
        ))}
      </div>

      {tab === "overview" ? <OverviewTab patientId={patientId} /> : null}
      {tab === "notes" ? <NotesTab patientId={patientId} /> : null}
      {tab === "approvals" ? <ApprovalsTab patientId={patientId} /> : null}
      {tab === "scripts" ? <ScriptsTab patientId={patientId} /> : null}
      {tab === "appointments" ? (
        <AppointmentsTab patientId={patientId} />
      ) : null}
      {tab === "activity" ? <ActivityTab patientId={patientId} /> : null}

      <PatientFormDialog
        open={editing}
        onOpenChange={setEditing}
        patient={patient}
      />
    </>
  )
}

function OverviewTab({ patientId }: { patientId: string }) {
  const { data: p } = useSuspenseQuery(patientQuery(patientId))
  const approvals = useQuery(patientApprovalsQuery(patientId))
  const appts = useQuery(patientAppointmentsQuery(patientId))
  const upcoming = (appts.data ?? [])
    .filter(
      (a) =>
        a.starts_at >= new Date().toISOString() && a.status !== "CANCELLED",
    )
    .slice(-3)
    .reverse()
  const active = (approvals.data ?? []).filter((a) => a.state === "ACTIVE")
  const row = (label: string, value: React.ReactNode) => (
    <div className="contents">
      <dt className="text-stone">{label}</dt>
      <dd className="min-w-0 break-words">
        {value || <span className="text-stone-faint">-</span>}
      </dd>
    </div>
  )
  return (
    <div className="grid gap-3.5 lg:grid-cols-[minmax(0,1.2fr)_minmax(0,1fr)]">
      <Card title="Details">
        <dl className="grid grid-cols-[130px_minmax(0,1fr)] gap-y-2.5 text-sm">
          {row("Given name", p.given_name)}
          {row("Family name", p.family_name)}
          {row("Preferred name", p.preferred_name)}
          {row("Date of birth", formatDate(p.date_of_birth))}
          {row("Mobile", p.phone ? <Mono>{p.phone}</Mono> : null)}
          {row("Email", p.email)}
          {row(
            "Address",
            [
              p.address_line,
              [p.suburb, p.state, p.postcode].filter(Boolean).join(" "),
            ]
              .filter(Boolean)
              .join(", "),
          )}
          {row("Record created", formatDayMonthTime(p.created_at))}
        </dl>
      </Card>
      <div className="min-w-0 space-y-3.5">
        <Card title="Active approvals">
          {approvals.isError ? (
            <ErrorState error={approvals.error} />
          ) : active.length === 0 ? (
            <p className="text-sm text-stone">
              No active TGA approval. Scripts will be blocked.
            </p>
          ) : (
            <ul className="space-y-2 text-sm">
              {active.map((a) => (
                <li
                  key={a.id}
                  className="flex items-baseline justify-between gap-3"
                >
                  <Mono>{a.approval_reference}</Mono>
                  <span className="text-stone">
                    {a.tga_category.replace("CATEGORY_", "Cat ")}
                  </span>
                </li>
              ))}
            </ul>
          )}
        </Card>
        <Card title="Upcoming appointments">
          {appts.isError ? (
            <ErrorState error={appts.error} />
          ) : appts.isPending ? (
            <SkeletonRows rows={2} />
          ) : upcoming.length === 0 ? (
            <p className="text-sm text-stone">Nothing booked.</p>
          ) : (
            <ul className="space-y-2 text-sm">
              {upcoming.map((a) => (
                <li
                  key={a.id}
                  className="flex items-baseline justify-between gap-3"
                >
                  <span>
                    <Mono>
                      {formatDayMonth(a.starts_at)} {formatTime(a.starts_at)}
                    </Mono>{" "}
                    <span className="text-stone">
                      {APPOINTMENT_TYPES[a.type].label}
                    </span>
                  </span>
                  <AppointmentStatusPill status={a.status} />
                </li>
              ))}
            </ul>
          )}
        </Card>
      </div>
    </div>
  )
}

function ApprovalsTab({ patientId }: { patientId: string }) {
  const approvals = useQuery(patientApprovalsQuery(patientId))
  const [recording, setRecording] = useState(false)
  return (
    <>
      <Card
        title="TGA approvals"
        action={
          <Button size="sm" onClick={() => setRecording(true)}>
            <Plus /> Record approval
          </Button>
        }
        bodyClassName="-mx-5 -mb-[18px]"
      >
        {approvals.isPending ? (
          <div className="px-5 pb-5">
            <SkeletonRows rows={2} />
          </div>
        ) : approvals.isError ? (
          <div className="px-5 pb-5">
            <ErrorState
              error={approvals.error}
              onRetry={() => approvals.refetch()}
            />
          </div>
        ) : approvals.data.length === 0 ? (
          <EmptyState
            title="No TGA approvals on file."
            body="Any script for this patient will be blocked by the safety gate until an approval is recorded and verified."
          />
        ) : (
          <ApprovalsTable approvals={approvals.data} />
        )}
      </Card>
      <RecordApprovalDialog
        open={recording}
        onOpenChange={setRecording}
        patientId={patientId}
      />
    </>
  )
}

function ScriptsTab({ patientId }: { patientId: string }) {
  const scripts = useQuery(scriptsQuery)
  const { data: me } = useQuery(currentUserQuery)
  const [staging, setStaging] = useState(false)
  const [reviewing, setReviewing] = useState<Script | null>(null)
  const mine = (scripts.data ?? []).filter((s) => s.patient_id === patientId)
  const open = mine.filter((s) => isActionable(s.state))
  const done = mine.filter((s) => !isActionable(s.state))
  return (
    <>
      <PreviewBanner what="Scripts are sample drafts; nothing is sent to a pharmacy." />
      <Card
        title="Scripts"
        action={
          <Button size="sm" onClick={() => setStaging(true)}>
            <Plus /> Stage a script
          </Button>
        }
      >
        {mine.length === 0 ? (
          <EmptyState title="No scripts for this patient." />
        ) : (
          <div className="space-y-3">
            {open.map((s) => (
              <ScriptCard
                key={s.id}
                script={s}
                canSign={s.prescriber_id === me?.id}
                onReview={() => setReviewing(s)}
                showPatientLink={false}
              />
            ))}
            {done.length ? (
              <ul className="divide-y divide-line-faint rounded-inner border border-line">
                {done.map((s) => (
                  <li
                    key={s.id}
                    className="flex flex-wrap items-center gap-3 px-4 py-3 text-sm"
                  >
                    <Mono className="text-stone">
                      {formatDayMonth(s.sent_at ?? s.created_at)}
                    </Mono>
                    <span className="font-medium">{s.product_name}</span>
                    <span className="text-stone">{s.prescriber_name}</span>
                    <span className="ml-auto flex items-center gap-2">
                      {s.escript_token ? (
                        <Mono className="text-[11.5px] text-stone">
                          {s.escript_token}
                        </Mono>
                      ) : null}
                      <ScriptStatePill state={s.state} />
                    </span>
                  </li>
                ))}
              </ul>
            ) : null}
          </div>
        )}
      </Card>
      <StageScriptDialog
        open={staging}
        onOpenChange={setStaging}
        patientId={patientId}
      />
      <ReviewSignDialog
        script={reviewing}
        onOpenChange={(o) => !o && setReviewing(null)}
      />
    </>
  )
}

function AppointmentsTab({ patientId }: { patientId: string }) {
  const appts = useQuery(patientAppointmentsQuery(patientId))
  const { data: practitioners = [] } = useQuery(practitionersQuery)
  return (
    <Card bodyClassName="-mx-5 -my-[18px]">
      {appts.isError ? (
        <div className="p-5">
          <ErrorState
            error={appts.error}
            onRetry={() => void appts.refetch()}
          />
        </div>
      ) : appts.isPending ? (
        <div className="p-5">
          <SkeletonRows rows={3} />
        </div>
      ) : (appts.data ?? []).length === 0 ? (
        <EmptyState title="No appointments." />
      ) : (
        <table className="data-table">
          <thead>
            <tr>
              <th className="pl-5">When</th>
              <th>Type</th>
              <th className="max-sm:hidden">With</th>
              <th className="pr-5">Status</th>
            </tr>
          </thead>
          <tbody>
            {appts.data!.map((a) => (
              <tr key={a.id}>
                <td className="pl-5">
                  <Mono>
                    {formatDate(a.starts_at)} {formatTime(a.starts_at)}
                  </Mono>
                </td>
                <td>{APPOINTMENT_TYPES[a.type].label}</td>
                <td className="max-sm:hidden">
                  {practitioners.find((p) => p.id === a.practitioner_id)?.name}
                </td>
                <td className="pr-5">
                  <AppointmentStatusPill status={a.status} />
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </Card>
  )
}

function ActivityTab({ patientId }: { patientId: string }) {
  const events = useQuery(resourceAuditQuery(patientId))
  return (
    <Card
      title="Audit trail"
      action={
        <span className="text-xs text-stone">Append-only, hash-chained</span>
      }
      bodyClassName="-mx-5 -mb-[18px]"
    >
      {events.isPending ? (
        <div className="px-5 pb-5">
          <SkeletonRows rows={3} />
        </div>
      ) : events.isError ? (
        <div className="px-5 pb-5">
          <ErrorState error={events.error} onRetry={() => events.refetch()} />
        </div>
      ) : events.data.length === 0 ? (
        <EmptyState title="No recorded activity for this record yet." />
      ) : (
        <table className="data-table">
          <thead>
            <tr>
              <th className="pl-5">When</th>
              <th>Action</th>
              <th className="max-sm:hidden">Role</th>
              <th className="max-md:pr-5">Result</th>
              <th className="pr-5 max-md:hidden">Hash</th>
            </tr>
          </thead>
          <tbody>
            {events.data.map((e) => (
              <tr key={e.event_id}>
                <td className="pl-5">
                  <Mono>{formatDayMonthTime(e.timestamp)}</Mono>
                </td>
                <td>{actionLabel(e.action)}</td>
                <td className="text-stone max-sm:hidden">
                  {e.actor_role ?? "-"}
                </td>
                <td className="max-md:pr-5">
                  <span
                    className={
                      e.result === "SUCCESS" ? "text-ok-deep" : "text-danger"
                    }
                  >
                    {e.result.toLowerCase()}
                  </span>
                  {e.reason ? (
                    <span className="ml-1 text-xs text-stone">
                      ({e.reason})
                    </span>
                  ) : null}
                </td>
                <td className="pr-5 max-md:hidden">
                  <Mono className="text-[11px] text-stone-faint">
                    {e.hash.slice(0, 12)}…
                  </Mono>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </Card>
  )
}
