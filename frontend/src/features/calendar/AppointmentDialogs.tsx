import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query"
import { Link } from "@tanstack/react-router"
import { Loader2 } from "lucide-react"
import { type FormEvent, useEffect, useState } from "react"
import { toast } from "sonner"
import type { PatientRead } from "@/client/types.gen"
import { Button } from "@/components/ui/button"
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog"
import { appointmentsRepo, STATUS_LABEL } from "@/data/appointments"
import {
  patientName,
  patientQuickFindQuery,
  useSearchTerm,
} from "@/data/patients"
import {
  APPOINTMENT_TRANSITIONS,
  APPOINTMENT_TYPES,
  type Appointment,
  type AppointmentStatus,
  type AppointmentType,
  type Practitioner,
} from "@/data/types"
import { ErrorState, Field } from "@/design/primitives"
import { AppointmentStatusPill } from "@/features/shared/pills"
import { clinicInstant } from "@/lib/clinic-time"
import { formatDate, formatLongDay, formatTime } from "@/lib/format"
import { describeError } from "@/lib/http"

const invalidateSchedule = (queryClient: ReturnType<typeof useQueryClient>) =>
  Promise.all([
    queryClient.invalidateQueries({ queryKey: ["appointments"] }),
    queryClient.invalidateQueries({ queryKey: ["dashboard"] }),
  ])

export interface SlotPrefill {
  practitionerId: string
  date: string
  time: string
}

export function NewAppointmentDialog({
  open,
  onOpenChange,
  practitioners,
  prefill,
}: {
  open: boolean
  onOpenChange: (open: boolean) => void
  practitioners: Practitioner[]
  prefill: SlotPrefill
}) {
  const queryClient = useQueryClient()
  // The picker asks the server (`POST /patients/search`), so every patient is reachable, not only
  // the first page; with nothing typed it offers the first few by name.
  const [search, setSearch] = useState("")
  const term = useSearchTerm(search)
  const matches = useQuery({ ...patientQuickFindQuery(term), enabled: open })
  const [patient, setPatient] = useState<PatientRead | null>(null)
  const patientId = patient?.id ?? ""
  const [practitionerId, setPractitionerId] = useState(prefill.practitionerId)
  const [date, setDate] = useState(prefill.date)
  const [time, setTime] = useState(prefill.time)
  const practitioner = practitioners.find((p) => p.id === practitionerId)
  const types = (Object.keys(APPOINTMENT_TYPES) as AppointmentType[]).filter(
    (t) => APPOINTMENT_TYPES[t].role === practitioner?.role,
  )
  const [type, setType] = useState<AppointmentType>(types[0] ?? "FOLLOW_UP")

  useEffect(() => {
    if (open) {
      setPractitionerId(prefill.practitionerId)
      setDate(prefill.date)
      setTime(prefill.time)
      setPatient(null)
      setSearch("")
    }
  }, [open, prefill])

  useEffect(() => {
    if (!types.includes(type) && types[0]) setType(types[0])
  }, [types, type])

  const create = useMutation({
    mutationFn: () =>
      appointmentsRepo.create({
        patient_id: patientId,
        practitioner_id: practitionerId,
        type,
        starts_at: clinicInstant(date, time),
      }),
    onSuccess: async (appt) => {
      await invalidateSchedule(queryClient)
      toast.success(
        `Booked ${appt.patient_name} at ${formatTime(appt.starts_at)}`,
      )
      onOpenChange(false)
    },
  })

  const submit = (e: FormEvent) => {
    e.preventDefault()
    if (!patientId) return
    create.mutate()
  }

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent>
        <form onSubmit={submit} className="grid gap-4">
          <DialogHeader>
            <DialogTitle>New appointment</DialogTitle>
            <DialogDescription>
              Double-bookings are refused; pick a free time for the
              practitioner.
            </DialogDescription>
          </DialogHeader>

          <Field label="Patient" htmlFor="appt-patient">
            {patient ? (
              <div className="flex items-center justify-between gap-3 rounded-btn border border-line bg-paper px-3 py-2 text-sm">
                <span className="truncate font-medium">
                  {patientName(patient)}
                </span>
                <button
                  type="button"
                  className="shrink-0 text-[13px] font-medium text-clay hover:underline"
                  onClick={() => setPatient(null)}
                >
                  Change
                </button>
              </div>
            ) : (
              <>
                <input
                  id="appt-patient"
                  className="field-input"
                  placeholder="Search by name, date of birth or PT- reference"
                  autoComplete="off"
                  value={search}
                  onChange={(e) => setSearch(e.target.value)}
                  aria-controls="appt-patient-results"
                />
                {matches.isError ? (
                  <div className="mt-2">
                    <ErrorState error={matches.error} />
                  </div>
                ) : (
                  <ul
                    id="appt-patient-results"
                    aria-label="Matching patients"
                    className="mt-1.5 max-h-48 overflow-y-auto rounded-btn border border-line bg-paper"
                  >
                    {matches.isPending ? (
                      <li className="px-3 py-2 text-[13px] text-stone">
                        Searching…
                      </li>
                    ) : matches.data.data.length === 0 ? (
                      <li className="px-3 py-2 text-[13px] text-stone">
                        No patient matches “{term}”.
                      </li>
                    ) : (
                      matches.data.data.map((p) => (
                        <li key={p.id}>
                          <button
                            type="button"
                            className="flex w-full items-baseline justify-between gap-3 px-3 py-2 text-left text-sm hover:bg-oat focus-visible:bg-oat"
                            onClick={() => setPatient(p)}
                          >
                            <span className="truncate">{patientName(p)}</span>
                            <span className="shrink-0 font-mono text-[11px] text-stone">
                              {formatDate(p.date_of_birth)}
                            </span>
                          </button>
                        </li>
                      ))
                    )}
                  </ul>
                )}
              </>
            )}
          </Field>

          <div className="grid gap-4 sm:grid-cols-2">
            <Field label="With" htmlFor="appt-prac">
              <select
                id="appt-prac"
                className="field-input"
                value={practitionerId}
                onChange={(e) => setPractitionerId(e.target.value)}
              >
                {practitioners.map((p) => (
                  <option key={p.id} value={p.id}>
                    {p.name}
                  </option>
                ))}
              </select>
            </Field>
            <Field label="Type" htmlFor="appt-type">
              <select
                id="appt-type"
                className="field-input"
                value={type}
                onChange={(e) => setType(e.target.value as AppointmentType)}
              >
                {types.map((t) => (
                  <option key={t} value={t}>
                    {APPOINTMENT_TYPES[t].label} ·{" "}
                    {APPOINTMENT_TYPES[t].minutes} min
                  </option>
                ))}
              </select>
            </Field>
            <Field label="Date" htmlFor="appt-date">
              <input
                id="appt-date"
                type="date"
                className="field-input"
                value={date}
                onChange={(e) => setDate(e.target.value)}
                required
              />
            </Field>
            <Field label="Time" htmlFor="appt-time">
              <input
                id="appt-time"
                type="time"
                step={900}
                min="07:00"
                max="19:00"
                className="field-input"
                value={time}
                onChange={(e) => setTime(e.target.value)}
                required
              />
            </Field>
          </div>

          {create.isError ? (
            <p
              role="alert"
              className="rounded-btn bg-danger-tint px-3 py-2.5 text-[13px] text-danger-deep"
            >
              {describeError(create.error)}
            </p>
          ) : null}

          <DialogFooter>
            <Button
              type="button"
              variant="outline"
              onClick={() => onOpenChange(false)}
            >
              Cancel
            </Button>
            <Button type="submit" disabled={!patientId || create.isPending}>
              {create.isPending ? <Loader2 className="animate-spin" /> : null}
              Book appointment
            </Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  )
}

const ACTION_LABEL: Partial<Record<AppointmentStatus, string>> = {
  CONFIRMED: "Confirm",
  ARRIVED: "Mark arrived",
  COMPLETED: "Complete",
  NO_SHOW: "No-show",
  CANCELLED: "Cancel appointment",
}

export function AppointmentDialog({
  appointment,
  practitioner,
  onOpenChange,
}: {
  appointment: Appointment | null
  practitioner?: Practitioner
  onOpenChange: (open: boolean) => void
}) {
  const queryClient = useQueryClient()
  const update = useMutation({
    mutationFn: (status: AppointmentStatus) =>
      appointmentsRepo.setStatus(appointment!.id, status),
    onSuccess: async (appt) => {
      await invalidateSchedule(queryClient)
      toast.success(
        `${appt.patient_name}: ${STATUS_LABEL[appt.status].toLowerCase()}`,
      )
      onOpenChange(false)
    },
  })
  const { reset } = update
  // A refusal belongs to the booking it was about: opening another one starts clean.
  // biome-ignore lint/correctness/useExhaustiveDependencies: reset when the selected booking changes
  useEffect(() => reset(), [appointment?.id, reset])

  const a = appointment
  const next = a ? APPOINTMENT_TRANSITIONS[a.status] : []
  const intake = a?.source === "PUBLIC_BOOKING"

  return (
    <Dialog open={a !== null} onOpenChange={onOpenChange}>
      <DialogContent>
        {a ? (
          <>
            <DialogHeader>
              <DialogTitle>{a.patient_name}</DialogTitle>
              <DialogDescription>
                {APPOINTMENT_TYPES[a.type].label} with{" "}
                {practitioner?.name ?? "-"}
              </DialogDescription>
            </DialogHeader>
            <dl className="grid grid-cols-[110px_minmax(0,1fr)] gap-y-2.5 text-sm">
              <dt className="text-stone">When</dt>
              <dd>
                {formatLongDay(new Date(a.starts_at))},{" "}
                <span className="font-mono">
                  {formatTime(a.starts_at)}–{formatTime(a.ends_at)}
                </span>
              </dd>
              <dt className="text-stone">Status</dt>
              <dd>
                <AppointmentStatusPill status={a.status} />
              </dd>
              <dt className="text-stone">Booked via</dt>
              <dd>
                {a.source === "PUBLIC_BOOKING"
                  ? "Public booking page"
                  : "Staff"}
              </dd>
            </dl>
            {intake ? (
              <p className="rounded-btn bg-info-tint px-3 py-2.5 text-[13px] text-info-deep">
                Booked by the patient on the public booking page. Check their
                details and add anything missing before the consult.
              </p>
            ) : null}
            <Link
              to="/patients/$patientId"
              params={{ patientId: a.patient_id }}
              className="text-sm font-medium text-clay hover:underline"
            >
              Open patient record →
            </Link>
            {update.isError ? (
              <p
                role="alert"
                className="rounded-btn bg-danger-tint px-3 py-2.5 text-[13px] text-danger-deep"
              >
                {describeError(update.error)}
              </p>
            ) : null}
            {next.length ? (
              <DialogFooter className="flex-wrap gap-2 sm:justify-start">
                {next.map((status) => (
                  <Button
                    key={status}
                    size="sm"
                    variant={
                      status === "CANCELLED" || status === "NO_SHOW"
                        ? "outline"
                        : "default"
                    }
                    disabled={update.isPending}
                    onClick={() => update.mutate(status)}
                  >
                    {ACTION_LABEL[status]}
                  </Button>
                ))}
              </DialogFooter>
            ) : null}
          </>
        ) : null}
      </DialogContent>
    </Dialog>
  )
}
