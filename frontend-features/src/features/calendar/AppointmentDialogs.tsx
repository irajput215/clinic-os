import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query"
import { Link } from "@tanstack/react-router"
import { Loader2 } from "lucide-react"
import { type FormEvent, useEffect, useState } from "react"
import { toast } from "sonner"
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
import { patientName, patientsQuery } from "@/data/patients"
import { clinicInstant } from "@/data/preview/time"
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
import { formatLongDay, formatTime } from "@/lib/format"
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
  const patients = useQuery({ ...patientsQuery, enabled: open })
  const [patientId, setPatientId] = useState("")
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
      setPatientId("")
    }
  }, [open, prefill])

  useEffect(() => {
    if (!types.includes(type) && types[0]) setType(types[0])
  }, [types, type])

  const create = useMutation({
    mutationFn: () => {
      const patient = patients.data?.data.find((p) => p.id === patientId)
      return appointmentsRepo.create({
        patient_id: patientId,
        patient_name: patient ? patientName(patient) : "",
        practitioner_id: practitionerId,
        type,
        starts_at: clinicInstant(date, time),
      })
    },
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
            {patients.isError ? (
              <ErrorState error={patients.error} />
            ) : (
              <select
                id="appt-patient"
                className="field-input"
                value={patientId}
                onChange={(e) => setPatientId(e.target.value)}
                required
              >
                <option value="" disabled>
                  {patients.isPending
                    ? "Loading patients…"
                    : "Choose a patient"}
                </option>
                {patients.data?.data.map((p) => (
                  <option key={p.id} value={p.id}>
                    {patientName(p)}
                  </option>
                ))}
              </select>
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
    onError: (error) => toast.error(describeError(error)),
  })

  const a = appointment
  const next = a ? APPOINTMENT_TRANSITIONS[a.status] : []
  const intake = a?.patient_id.startsWith("intake-")

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
                New patient from the booking page. Create their record from the
                intake before the consult.
              </p>
            ) : (
              <Link
                to="/patients/$patientId"
                params={{ patientId: a.patient_id }}
                className="text-sm font-medium text-clay hover:underline"
              >
                Open patient record →
              </Link>
            )}
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
