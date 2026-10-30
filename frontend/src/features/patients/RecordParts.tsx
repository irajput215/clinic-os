import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query"
import { Loader2, Plus, X, Zap } from "lucide-react"
import { useEffect, useId, useState } from "react"
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
import {
  addPatientAlert,
  addPatientContact,
  changePatientStatus,
  PATIENT_STATUSES,
  type PatientStatus,
  patientAlertsQuery,
  patientContactsQuery,
  patientQuery,
  removePatientAlert,
  removePatientContact,
  STATUSES_NEEDING_A_REASON,
} from "@/data/patients"
import { myPermissionsQuery } from "@/data/permissions"
import {
  Card,
  ErrorState,
  Field,
  FormAlert,
  Mono,
  Pill,
  SkeletonRows,
  type Tone,
} from "@/design/primitives"
import { clinicToday } from "@/lib/format"
import { describeError } from "@/lib/http"
import { cn } from "@/lib/utils"

/** Whether the signed-in account may change patient records. The server decides; this only hides. */
export function useCanUpdatePatients() {
  const { data } = useQuery(myPermissionsQuery)
  // An unknown set (an older backend) shows the control, as elsewhere; the server still refuses.
  return data ? !data.known || data.codes.includes("patient:update") : false
}

export function PatientStatusPill({ status }: { status: string }) {
  const known = PATIENT_STATUSES[status as PatientStatus]
  return (
    <Pill tone={(known?.tone ?? "neutral") as Tone}>
      {known?.label ?? status}
    </Pill>
  )
}

const MISSING_LABEL: Record<string, string> = {
  IHI: "IHI",
  SEX: "sex",
  ADDRESS: "full address",
}

/** Manual §3.4, the eScript-ready rule: verified IHI, sex and a complete street address. */
export function EScriptChip({ patient }: { patient: PatientRead }) {
  if (patient.escript_ready.ready)
    return (
      <Pill tone="ok" title="IHI, sex and a full address are on file">
        <Zap className="size-3" aria-hidden /> eScript-ready
      </Pill>
    )
  return (
    <Pill
      tone="warn"
      title="An eScript needs a verified IHI, the patient's sex and a full street address"
    >
      Not eScript-ready: missing{" "}
      {patient.escript_ready.missing
        .map((m) => MISSING_LABEL[m] ?? m)
        .join(", ")}
    </Pill>
  )
}

const ALERT_TONE: Record<string, Tone> = {
  INFO: "info",
  WARN: "warn",
  DANGER: "danger",
}

/** The alert chips under the patient's name (manual §3.4), each removable by those who may edit. */
export function AlertChips({ patientId }: { patientId: string }) {
  const alerts = useQuery(patientAlertsQuery(patientId))
  const canUpdate = useCanUpdatePatients()
  const queryClient = useQueryClient()
  const remove = useMutation({
    mutationFn: (alertId: string) => removePatientAlert(patientId, alertId),
    onSuccess: (data) =>
      queryClient.setQueryData(patientAlertsQuery(patientId).queryKey, data),
    onError: (error) => toast.error(describeError(error)),
  })
  if (!alerts.data?.length) return null
  return (
    <ul aria-label="Alerts" className="mt-2 flex flex-wrap gap-1.5">
      {alerts.data.map((a) => (
        <li key={a.id}>
          <Pill tone={ALERT_TONE[a.tone] ?? "neutral"}>
            {a.text}
            {canUpdate ? (
              <button
                type="button"
                className="-mr-1 ml-0.5 inline-flex rounded-full p-0.5 hover:bg-black/10 max-lg:min-h-6 max-lg:min-w-6 max-lg:justify-center"
                aria-label={`Remove alert: ${a.text}`}
                disabled={remove.isPending}
                onClick={() => remove.mutate(a.id)}
              >
                <X className="size-3" aria-hidden />
              </button>
            ) : null}
          </Pill>
        </li>
      ))}
    </ul>
  )
}

export function AddAlertDialog({
  patientId,
  open,
  onOpenChange,
}: {
  patientId: string
  open: boolean
  onOpenChange: (open: boolean) => void
}) {
  const queryClient = useQueryClient()
  const [text, setText] = useState("")
  const [tone, setTone] = useState("INFO")
  const textId = useId()
  const toneId = useId()
  useEffect(() => {
    if (open) {
      setText("")
      setTone("INFO")
    }
  }, [open])
  const save = useMutation({
    mutationFn: () =>
      addPatientAlert(patientId, {
        text: text.trim(),
        tone: tone as "INFO" | "WARN" | "DANGER",
      }),
    onSuccess: (data) => {
      queryClient.setQueryData(patientAlertsQuery(patientId).queryKey, data)
      toast.success("Alert added")
      onOpenChange(false)
    },
  })
  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="sm:max-w-[440px]">
        <form
          noValidate
          className="grid gap-4"
          onSubmit={(e) => {
            e.preventDefault()
            if (text.trim()) save.mutate()
          }}
        >
          <DialogHeader>
            <DialogTitle>Add an alert</DialogTitle>
            <DialogDescription>
              A short note shown on this patient's header everywhere, such as
              "payment plan" or "interpreter needed".
            </DialogDescription>
          </DialogHeader>
          <Field label="Alert" htmlFor={textId}>
            <input
              id={textId}
              className="field-input"
              maxLength={120}
              value={text}
              autoComplete="off"
              onChange={(e) => setText(e.target.value)}
            />
          </Field>
          <Field label="Tone" htmlFor={toneId}>
            <select
              id={toneId}
              className="field-input"
              value={tone}
              onChange={(e) => setTone(e.target.value)}
            >
              <option value="INFO">Information</option>
              <option value="WARN">Caution</option>
              <option value="DANGER">Danger</option>
            </select>
          </Field>
          {save.isError ? (
            <FormAlert>{describeError(save.error)}</FormAlert>
          ) : null}
          <DialogFooter>
            <Button
              type="button"
              variant="outline"
              onClick={() => onOpenChange(false)}
            >
              Cancel
            </Button>
            <Button type="submit" disabled={!text.trim() || save.isPending}>
              {save.isPending ? <Loader2 className="animate-spin" /> : null}
              Add alert
            </Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  )
}

export function ChangeStatusDialog({
  patient,
  open,
  onOpenChange,
}: {
  patient: PatientRead
  open: boolean
  onOpenChange: (open: boolean) => void
}) {
  const queryClient = useQueryClient()
  const [status, setStatus] = useState<PatientStatus>(
    patient.status as PatientStatus,
  )
  const [reason, setReason] = useState("")
  const [deceasedOn, setDeceasedOn] = useState("")
  const statusId = useId()
  const reasonId = useId()
  const dateId = useId()
  useEffect(() => {
    if (open) {
      setStatus(patient.status as PatientStatus)
      setReason("")
      setDeceasedOn("")
    }
  }, [open, patient.status])
  const needsReason = STATUSES_NEEDING_A_REASON.includes(status)
  const needsDate = status === "DECEASED"
  const ready =
    status !== patient.status &&
    (!needsReason || reason.trim() !== "") &&
    (!needsDate || deceasedOn !== "")
  const save = useMutation({
    mutationFn: () =>
      changePatientStatus(patient.id, {
        status,
        reason: reason.trim() || null,
        deceased_at: needsDate ? `${deceasedOn}T00:00:00Z` : null,
      }),
    onSuccess: async (saved) => {
      queryClient.setQueryData(patientQuery(saved.id).queryKey, saved)
      await queryClient.invalidateQueries({ queryKey: ["patients", "list"] })
      toast.success(`Status changed to ${PATIENT_STATUSES[status].label}`)
      onOpenChange(false)
    },
  })
  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="sm:max-w-[460px]">
        <form
          noValidate
          className="grid gap-4"
          onSubmit={(e) => {
            e.preventDefault()
            if (ready) save.mutate()
          }}
        >
          <DialogHeader>
            <DialogTitle>Change status</DialogTitle>
            <DialogDescription>
              Archived, discharged and deceased records stay, but leave the
              patient list. Blocked stops new bookings and scripts.
            </DialogDescription>
          </DialogHeader>
          <Field label="Status" htmlFor={statusId}>
            <select
              id={statusId}
              className="field-input"
              value={status}
              onChange={(e) => setStatus(e.target.value as PatientStatus)}
            >
              {Object.entries(PATIENT_STATUSES).map(([value, { label }]) => (
                <option key={value} value={value}>
                  {label}
                </option>
              ))}
            </select>
          </Field>
          <Field
            label="Reason"
            htmlFor={reasonId}
            hint={needsReason ? "Required for this status" : "Optional"}
          >
            <textarea
              id={reasonId}
              className="field-input min-h-20"
              maxLength={500}
              value={reason}
              onChange={(e) => setReason(e.target.value)}
            />
          </Field>
          {needsDate ? (
            <Field label="Date of death" htmlFor={dateId}>
              <input
                id={dateId}
                type="date"
                className="field-input"
                max={clinicToday()}
                value={deceasedOn}
                onChange={(e) => setDeceasedOn(e.target.value)}
              />
            </Field>
          ) : null}
          {save.isError ? (
            <FormAlert>{describeError(save.error)}</FormAlert>
          ) : null}
          <DialogFooter>
            <Button
              type="button"
              variant="outline"
              onClick={() => onOpenChange(false)}
            >
              Cancel
            </Button>
            <Button type="submit" disabled={!ready || save.isPending}>
              {save.isPending ? <Loader2 className="animate-spin" /> : null}
              Change status
            </Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  )
}

export function IdentifiersCard({ patient }: { patient: PatientRead }) {
  const row = (label: string, value: React.ReactNode) => (
    <div className="contents">
      <dt className="text-stone">{label}</dt>
      <dd className="min-w-0">
        {value || <span className="text-stone-faint">Not on file</span>}
      </dd>
    </div>
  )
  return (
    <Card title="Identifiers" action={<EScriptChip patient={patient} />}>
      <dl className="grid grid-cols-[130px_minmax(0,1fr)] gap-y-2.5 text-sm">
        {row(
          "Medicare",
          patient.medicare_masked ? (
            <span>
              <Mono>{patient.medicare_masked}</Mono>
              {patient.medicare_irn ? (
                <span className="ml-2 text-stone">
                  IRN {patient.medicare_irn}
                </span>
              ) : null}
              <span className="ml-2 text-xs text-stone">format checked</span>
            </span>
          ) : null,
        )}
        {row(
          "IHI",
          patient.ihi_masked ? <Mono>{patient.ihi_masked}</Mono> : null,
        )}
        {row(
          "Communications",
          patient.receives_communications ? (
            "Receives reminders"
          ) : (
            <span className="text-warn-deep">Opted out of reminders</span>
          ),
        )}
        {row("Time zone", patient.timezone.replace("_", " "))}
      </dl>
    </Card>
  )
}

export function EmergencyContactsCard({ patientId }: { patientId: string }) {
  const contacts = useQuery(patientContactsQuery(patientId))
  const canUpdate = useCanUpdatePatients()
  const queryClient = useQueryClient()
  const [adding, setAdding] = useState(false)
  const [name, setName] = useState("")
  const [relationship, setRelationship] = useState("")
  const [phone, setPhone] = useState("")
  const ids = { name: useId(), relationship: useId(), phone: useId() }
  const settle = (data: Awaited<ReturnType<typeof addPatientContact>>) =>
    queryClient.setQueryData(patientContactsQuery(patientId).queryKey, data)
  const add = useMutation({
    mutationFn: () =>
      addPatientContact(patientId, {
        name: name.trim(),
        relationship: relationship.trim(),
        phone: phone.trim(),
      }),
    onSuccess: (data) => {
      settle(data)
      setName("")
      setRelationship("")
      setPhone("")
      setAdding(false)
      toast.success("Emergency contact added")
    },
  })
  const remove = useMutation({
    mutationFn: (contactId: string) =>
      removePatientContact(patientId, contactId),
    onSuccess: settle,
    onError: (error) => toast.error(describeError(error)),
  })
  const complete = name.trim() && relationship.trim() && phone.trim()
  return (
    <Card
      title="Emergency contacts"
      action={
        canUpdate && !adding ? (
          <Button size="sm" variant="outline" onClick={() => setAdding(true)}>
            <Plus /> Add
          </Button>
        ) : undefined
      }
    >
      {contacts.isPending ? (
        <SkeletonRows rows={1} />
      ) : contacts.isError ? (
        <ErrorState error={contacts.error} onRetry={() => contacts.refetch()} />
      ) : contacts.data.length === 0 && !adding ? (
        <p className="text-sm text-stone">
          None on file. At least one is good practice for telehealth.
        </p>
      ) : (
        <ul className="divide-y divide-line-faint text-sm">
          {contacts.data.map((c) => (
            <li key={c.id} className="flex items-center gap-3 py-2">
              <span className="min-w-0 flex-1">
                <span className="font-medium">{c.name}</span>{" "}
                <span className="text-stone">({c.relationship})</span>
              </span>
              <Mono>{c.phone}</Mono>
              {canUpdate ? (
                <Button
                  size="sm"
                  variant="ghost"
                  className="max-lg:min-h-11"
                  aria-label={`Remove ${c.name}`}
                  disabled={remove.isPending}
                  onClick={() => remove.mutate(c.id)}
                >
                  <X />
                </Button>
              ) : null}
            </li>
          ))}
        </ul>
      )}
      {adding ? (
        <form
          noValidate
          className={cn(
            "grid gap-3 sm:grid-cols-3",
            contacts.data?.length ? "mt-3 border-t border-line-faint pt-3" : "",
          )}
          onSubmit={(e) => {
            e.preventDefault()
            if (complete) add.mutate()
          }}
        >
          <Field label="Name" htmlFor={ids.name}>
            <input
              id={ids.name}
              className="field-input"
              value={name}
              autoComplete="off"
              onChange={(e) => setName(e.target.value)}
            />
          </Field>
          <Field label="Relationship" htmlFor={ids.relationship}>
            <input
              id={ids.relationship}
              className="field-input"
              value={relationship}
              autoComplete="off"
              onChange={(e) => setRelationship(e.target.value)}
            />
          </Field>
          <Field label="Phone" htmlFor={ids.phone}>
            <input
              id={ids.phone}
              type="tel"
              className="field-input"
              value={phone}
              autoComplete="off"
              onChange={(e) => setPhone(e.target.value)}
            />
          </Field>
          {add.isError ? (
            <div className="sm:col-span-3">
              <FormAlert>{describeError(add.error)}</FormAlert>
            </div>
          ) : null}
          <div className="flex justify-end gap-2 sm:col-span-3">
            <Button
              type="button"
              variant="outline"
              onClick={() => setAdding(false)}
            >
              Cancel
            </Button>
            <Button type="submit" disabled={!complete || add.isPending}>
              {add.isPending ? <Loader2 className="animate-spin" /> : null}
              Save contact
            </Button>
          </div>
        </form>
      ) : null}
    </Card>
  )
}
