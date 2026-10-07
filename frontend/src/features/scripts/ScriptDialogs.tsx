import { zodResolver } from "@hookform/resolvers/zod"
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query"
import { Link } from "@tanstack/react-router"
import { Loader2, ShieldAlert, ShieldCheck } from "lucide-react"
import { useState } from "react"
import { useForm } from "react-hook-form"
import { toast } from "sonner"
import type { PatientRead, PrescriberRead } from "@/client/types.gen"
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
  categoryShort,
  DOSAGE_FORMS,
  formLabel,
  TGA_CATEGORIES,
} from "@/data/approvals"
import { patientName, patientsQuery } from "@/data/patients"
import {
  type Prescription,
  prescribersQuery,
  scriptsRepo,
} from "@/data/scripts"
import { MATCH_REASONS } from "@/data/types"
import { ErrorState, Field, Mono } from "@/design/primitives"
import { focusFirstError } from "@/lib/form"
import { clinicToday, formatDate, lastCoveredDay } from "@/lib/format"
import { describeError, refusalCode, validationMessages } from "@/lib/http"
import { currentUserQuery } from "@/lib/session"
import { z } from "@/lib/zod"
import type { ScriptAction } from "./ScriptCard"

const invalidateScripts = (queryClient: ReturnType<typeof useQueryClient>) =>
  Promise.all([
    queryClient.invalidateQueries({ queryKey: ["scripts"] }),
    queryClient.invalidateQueries({ queryKey: ["dashboard"] }),
  ])

const schema = z.object({
  patient_id: z.string().min(1, "Choose the patient."),
  medicine_name: z
    .string()
    .trim()
    .min(2, "Enter the product, as it will appear on the script.")
    .max(200),
  tga_category: z.string().min(1, "Choose the TGA category."),
  dosage_form: z.string().min(1, "Choose the dosage form."),
  quantity: z
    .string()
    .trim()
    .regex(/^\d{1,8}(\.\d{1,2})?$/, "Enter a quantity, e.g. 1 or 2.5.")
    .refine((v) => Number(v) > 0, "The quantity must be more than zero."),
  repeats: z.coerce.number<string>().int().min(0).max(12),
  dose_instruction: z
    .string()
    .trim()
    .min(3, "Enter the directions for use.")
    .max(500),
  triage_outcome: z
    .string()
    .trim()
    .min(3, "Record the triage outcome.")
    .max(300),
  conventional_therapy: z
    .string()
    .trim()
    .min(3, "Record the conventional therapy tried first (TGA expectation).")
    .max(300),
  prescriber_id: z.string().min(1, "Choose the reviewing doctor."),
  date_of_service: z.string().regex(/^\d{4}-\d{2}-\d{2}$/),
})
type FormIn = z.input<typeof schema>
type FormOut = z.output<typeof schema>

/** A nurse (or doctor) stages a draft; the prescriber of record reviews and signs it later. */
export function StageScriptDialog({
  open,
  onOpenChange,
  patientId,
}: {
  open: boolean
  onOpenChange: (open: boolean) => void
  patientId?: string
}) {
  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="sm:max-w-[640px]">
        <StageScriptForm
          patientId={patientId}
          onClose={() => onOpenChange(false)}
        />
      </DialogContent>
    </Dialog>
  )
}

/**
 * Mounted fresh each time the dialog opens. It waits for the option lists before mounting the form:
 * a `<select>` registered before its options exist shows a different value from the one the form
 * holds, which on a prescription form is not acceptable.
 */
function StageScriptForm({
  patientId,
  onClose,
}: {
  patientId?: string
  onClose: () => void
}) {
  const patients = useQuery({ ...patientsQuery, enabled: !patientId })
  const prescribers = useQuery(prescribersQuery)
  const { data: me } = useQuery(currentUserQuery)
  const failed = prescribers.error ?? patients.error
  if (failed) return <ErrorState error={failed} />
  if (!prescribers.data || !me || (!patientId && !patients.data))
    return (
      <div className="flex justify-center py-10 text-stone">
        <Loader2 className="animate-spin" aria-label="Loading" />
      </div>
    )
  return (
    <StageScriptFields
      patientId={patientId}
      onClose={onClose}
      patients={patients.data?.data ?? []}
      prescribers={prescribers.data}
      meId={me.id}
    />
  )
}

function StageScriptFields({
  patientId,
  onClose,
  patients,
  prescribers,
  meId,
}: {
  patientId?: string
  onClose: () => void
  patients: PatientRead[]
  prescribers: PrescriberRead[]
  meId: string
}) {
  const queryClient = useQueryClient()
  const form = useForm<FormIn, unknown, FormOut>({
    shouldFocusError: false,
    resolver: zodResolver(schema),
    defaultValues: {
      patient_id: patientId ?? "",
      medicine_name: "",
      tga_category: "",
      dosage_form: "",
      quantity: "1",
      repeats: "2",
      dose_instruction: "",
      triage_outcome: "",
      conventional_therapy: "",
      prescriber_id: prescribers.some((d) => d.id === meId) ? meId : "",
      date_of_service: clinicToday(),
    },
  })
  const { errors } = form.formState

  const stage = useMutation({
    mutationFn: (v: FormOut) =>
      scriptsRepo.stage({ ...v, quantity: v.quantity }),
    onSuccess: async (script) => {
      await invalidateScripts(queryClient)
      if (script.gate?.matched)
        toast.success(
          `Staged for ${script.prescriber_name ?? "the prescriber"} to review`,
        )
      else
        toast.warning(
          "Staged, but no TGA approval covers it yet. It can't be signed until one does.",
        )
      onClose()
    },
  })
  const serverFields = validationMessages(stage.error)
  const fieldError = (name: keyof FormIn) =>
    errors[name]?.message ?? serverFields[name]

  return (
    <form
      onSubmit={form.handleSubmit((v) => stage.mutate(v), focusFirstError)}
      noValidate
      className="grid gap-4"
    >
      <DialogHeader>
        <DialogTitle>Stage a script</DialogTitle>
        <DialogDescription>
          Draft it with the triage outcome and conventional therapy tried first.
          The doctor reviews and signs; the safety gate checks the TGA approval
          for the date of service before it can be signed or sent.
        </DialogDescription>
      </DialogHeader>

      <div className="grid gap-4 sm:grid-cols-2">
        {!patientId ? (
          <Field
            label="Patient"
            htmlFor="sc-patient"
            error={fieldError("patient_id")}
            className="sm:col-span-2"
          >
            <select
              id="sc-patient"
              className="field-input"
              {...form.register("patient_id")}
            >
              <option value="">Choose a patient</option>
              {patients.map((p) => (
                <option key={p.id} value={p.id}>
                  {patientName(p)}
                </option>
              ))}
            </select>
          </Field>
        ) : null}
        <Field
          label="Product"
          htmlFor="sc-product"
          error={fieldError("medicine_name")}
          className="sm:col-span-2"
        >
          <input
            id="sc-product"
            className="field-input"
            autoComplete="off"
            placeholder="As it will appear on the script"
            {...form.register("medicine_name")}
          />
        </Field>
        <Field
          label="TGA category"
          htmlFor="sc-cat"
          error={fieldError("tga_category")}
        >
          <select
            id="sc-cat"
            className="field-input"
            {...form.register("tga_category")}
          >
            <option value="">Choose</option>
            {Object.entries(TGA_CATEGORIES).map(([code, label]) => (
              <option key={code} value={code}>
                {label}
              </option>
            ))}
          </select>
        </Field>
        <Field
          label="Dosage form"
          htmlFor="sc-form"
          error={fieldError("dosage_form")}
        >
          <select
            id="sc-form"
            className="field-input"
            {...form.register("dosage_form")}
          >
            <option value="">Choose</option>
            {Object.entries(DOSAGE_FORMS).map(([code, label]) => (
              <option key={code} value={code}>
                {label}
              </option>
            ))}
          </select>
        </Field>
        <Field label="Quantity" htmlFor="sc-qty" error={fieldError("quantity")}>
          <input
            id="sc-qty"
            inputMode="decimal"
            className="field-input"
            autoComplete="off"
            {...form.register("quantity")}
          />
        </Field>
        <Field label="Repeats" htmlFor="sc-rep" error={fieldError("repeats")}>
          <input
            id="sc-rep"
            type="number"
            min={0}
            max={12}
            className="field-input"
            {...form.register("repeats")}
          />
        </Field>
        <Field
          label="Directions / titration"
          htmlFor="sc-dir"
          error={fieldError("dose_instruction")}
          className="sm:col-span-2"
        >
          <input
            id="sc-dir"
            className="field-input"
            placeholder="e.g. 0.5 mL nocte, titrate weekly"
            autoComplete="off"
            {...form.register("dose_instruction")}
          />
        </Field>
        <Field
          label="Triage outcome"
          htmlFor="sc-tri"
          error={fieldError("triage_outcome")}
          className="sm:col-span-2"
        >
          <input
            id="sc-tri"
            className="field-input"
            placeholder="e.g. Eligible - chronic pain"
            autoComplete="off"
            {...form.register("triage_outcome")}
          />
        </Field>
        <Field
          label="Conventional therapy first"
          htmlFor="sc-conv"
          error={fieldError("conventional_therapy")}
          className="sm:col-span-2"
        >
          <input
            id="sc-conv"
            className="field-input"
            placeholder="What was tried, and for how long"
            autoComplete="off"
            {...form.register("conventional_therapy")}
          />
        </Field>
        <Field
          label="Reviewing doctor"
          htmlFor="sc-doc"
          error={fieldError("prescriber_id")}
          hint={
            prescribers.length === 0
              ? "Nobody in your practice can sign prescriptions yet."
              : undefined
          }
        >
          <select
            id="sc-doc"
            className="field-input"
            {...form.register("prescriber_id")}
          >
            <option value="">Choose</option>
            {prescribers.map((d) => (
              <option key={d.id} value={d.id}>
                {d.name}
              </option>
            ))}
          </select>
        </Field>
        <Field
          label="Date of service"
          htmlFor="sc-dos"
          error={fieldError("date_of_service")}
        >
          <input
            id="sc-dos"
            type="date"
            className="field-input"
            {...form.register("date_of_service")}
          />
        </Field>
      </div>

      {stage.isError ? (
        <p
          role="alert"
          className="rounded-btn bg-danger-tint px-3 py-2.5 text-[13px] text-danger-deep"
        >
          {describeError(stage.error)}
        </p>
      ) : null}

      <DialogFooter>
        <Button type="button" variant="outline" onClick={() => onClose()}>
          Cancel
        </Button>
        <Button type="submit" disabled={stage.isPending}>
          {stage.isPending ? <Loader2 className="animate-spin" /> : null}
          Stage draft
        </Button>
      </DialogFooter>
    </form>
  )
}

/** The outcome a successful send shows: honest about what "queued" means while no transport exists. */
const sentToast = (script: Prescription) => {
  if (script.state === "DISPATCHED")
    toast.success("Signed and sent to the pharmacy.")
  else if (script.dispatch && !script.dispatch.transport_configured)
    toast.warning(
      "Signed and queued. Not sent: no pharmacy connection is configured yet.",
    )
  else toast.success("Signed and queued for the pharmacy.")
}

/**
 * Review: the gate's answer from the server for the date of service, a password re-entry (the
 * server-side step-up, ADR-F002 interim), then sign and queue - or, for a script that is already
 * signed, queue it. The server evaluates the gate again inside each transaction; this screen only
 * shows the answer it last gave.
 */
export function ReviewSignDialog({
  script,
  action,
  onOpenChange,
}: {
  script: Prescription | null
  action: ScriptAction
  onOpenChange: (open: boolean) => void
}) {
  const queryClient = useQueryClient()
  const [password, setPassword] = useState("")
  // One intent per opening of the dialog: a retry of the same click reuses it (server idempotency).
  const [intent, setIntent] = useState(() => crypto.randomUUID())
  const [forScript, setForScript] = useState(script?.id)
  if (script?.id !== forScript) {
    setForScript(script?.id)
    setPassword("")
    setIntent(crypto.randomUUID())
  }

  const submit = useMutation({
    mutationFn: async () => {
      const s = script as Prescription
      const signed =
        s.state === "DRAFT" ? await scriptsRepo.sign(s.id, password) : s
      return scriptsRepo.dispatch(signed.id, password, intent)
    },
    onSuccess: async (result) => {
      await invalidateScripts(queryClient)
      sentToast(result)
      onOpenChange(false)
    },
    onError: async () => {
      // A refusal may have moved the script (signed, or blocked): show the server's current state.
      await invalidateScripts(queryClient)
    },
  })

  const s = script
  const gate = s?.gate ?? null
  const allowed = gate?.matched === true
  const signing = s?.state === "DRAFT"
  const errorCode = refusalCode(submit.error)

  return (
    <Dialog open={s !== null} onOpenChange={onOpenChange}>
      <DialogContent className="sm:max-w-[600px]">
        {s ? (
          <form
            className="grid gap-4"
            onSubmit={(e) => {
              e.preventDefault()
              submit.mutate()
            }}
          >
            <DialogHeader>
              <DialogTitle>
                {signing ? "Review & sign" : "Review & send"}
              </DialogTitle>
              <DialogDescription>
                {s.patient_name ?? "Patient"} · drafted by{" "}
                {s.drafted_by_name ?? "a colleague"}
              </DialogDescription>
            </DialogHeader>

            <div className="rounded-inner border border-line bg-oat px-4 py-3.5 text-sm">
              <div className="text-[15px] font-semibold">
                {s.medicine_name}{" "}
                <span className="font-normal text-stone">
                  · qty {s.quantity} · {s.repeats} repeats
                </span>
              </div>
              <div className="mt-0.5 text-stone">{s.dose_instruction}</div>
              <dl className="mt-3 grid grid-cols-[150px_minmax(0,1fr)] gap-y-1.5 text-[13px] max-sm:grid-cols-1">
                <dt className="font-semibold">Triage outcome</dt>
                <dd>{s.triage_outcome}</dd>
                <dt className="font-semibold">Conventional first</dt>
                <dd>{s.conventional_therapy}</dd>
                <dt className="font-semibold">Approval grain</dt>
                <dd>
                  {categoryShort(s.tga_category)} · {formLabel(s.dosage_form)}
                </dd>
                <dt className="font-semibold">Date of service</dt>
                <dd>{formatDate(s.date_of_service)}</dd>
              </dl>
            </div>

            <div
              className={
                allowed
                  ? "flex items-start gap-3 rounded-inner bg-ok-tint px-4 py-3 text-sm text-ok-deep"
                  : "flex items-start gap-3 rounded-inner bg-danger-tint px-4 py-3 text-sm text-danger-deep"
              }
              role="status"
            >
              {allowed && gate?.validity_interval ? (
                <>
                  <ShieldCheck className="mt-0.5 size-4 shrink-0" />
                  <span>
                    <span className="font-semibold">Safety gate: clear.</span>{" "}
                    An active approval covers {formatDate(s.date_of_service)}{" "}
                    (covered through{" "}
                    {formatDate(
                      lastCoveredDay(gate.validity_interval.valid_to),
                    )}
                    ). The server checks it again when you sign and send.
                  </span>
                </>
              ) : (
                <>
                  <ShieldAlert className="mt-0.5 size-4 shrink-0" />
                  <span>
                    <span className="font-semibold">Safety gate: blocked.</span>{" "}
                    {gate?.reason_code
                      ? MATCH_REASONS[gate.reason_code]
                      : "No covering approval"}
                    .{" "}
                    {gate?.reason_code ? (
                      <Mono className="text-[11.5px]">{gate.reason_code}</Mono>
                    ) : null}
                    <br />
                    <Link
                      to="/patients/$patientId"
                      params={{ patientId: s.patient_id }}
                      search={{ tab: "approvals" }}
                      className="font-medium underline underline-offset-2"
                    >
                      Open the patient's approvals
                    </Link>
                  </span>
                </>
              )}
            </div>

            {action === null ? (
              <p className="rounded-btn bg-warn-tint px-3 py-2.5 text-[13px] text-warn-deep">
                {signing
                  ? `Assigned to ${s.prescriber_name ?? "the prescriber"}. Only the assigned prescriber can sign it.`
                  : "Your role can't send scripts to a pharmacy."}
              </p>
            ) : (
              <Field
                label={
                  signing ? "Your password, to sign" : "Your password, to send"
                }
                htmlFor="sign-pw"
                hint="Re-enter your password: the server checks it before signing or sending."
              >
                <input
                  id="sign-pw"
                  type="password"
                  autoComplete="current-password"
                  className="field-input"
                  value={password}
                  onChange={(e) => setPassword(e.target.value)}
                  disabled={!allowed}
                />
              </Field>
            )}

            {submit.isError ? (
              <p
                role="alert"
                className="rounded-btn bg-danger-tint px-3 py-2.5 text-[13px] text-danger-deep"
              >
                {describeError(submit.error)}
                {errorCode && errorCode in MATCH_REASONS ? (
                  <Mono className="ml-1 text-[11.5px]">{errorCode}</Mono>
                ) : null}
              </p>
            ) : null}

            <DialogFooter>
              <Button
                type="button"
                variant="outline"
                onClick={() => onOpenChange(false)}
              >
                Close
              </Button>
              <Button
                type="submit"
                disabled={
                  action === null || !allowed || !password || submit.isPending
                }
              >
                {submit.isPending ? <Loader2 className="animate-spin" /> : null}
                {signing ? "Sign & queue for pharmacy" : "Queue for pharmacy"}
              </Button>
            </DialogFooter>
          </form>
        ) : null}
      </DialogContent>
    </Dialog>
  )
}
