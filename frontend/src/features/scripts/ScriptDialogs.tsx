import { zodResolver } from "@hookform/resolvers/zod"
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query"
import { Link } from "@tanstack/react-router"
import { Loader2, ShieldAlert, ShieldCheck } from "lucide-react"
import { useEffect, useState } from "react"
import { useForm } from "react-hook-form"
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
import { categoryShort, formLabel } from "@/data/approvals"
import { patientName, patientsQuery } from "@/data/patients"
import { previewPractitionersQuery } from "@/data/preview/practitioners"
import { productsQuery, scriptsRepo } from "@/data/scripts"
import {
  MATCH_REASONS,
  type Practitioner,
  type Product,
  type Script,
} from "@/data/types"
import { ErrorState, Field, Mono } from "@/design/primitives"
import { focusFirstError } from "@/lib/form"
import { clinicToday, formatDate, lastCoveredDay } from "@/lib/format"
import { describeError, httpStatus } from "@/lib/http"
import { currentUserQuery, signIn } from "@/lib/session"
import { z } from "@/lib/zod"

const invalidateScripts = (queryClient: ReturnType<typeof useQueryClient>) =>
  Promise.all([
    queryClient.invalidateQueries({ queryKey: ["scripts"] }),
    queryClient.invalidateQueries({ queryKey: ["dashboard"] }),
  ])

const schema = z.object({
  patient_id: z.string().min(1, "Choose the patient."),
  product_id: z.string().min(1, "Choose a product."),
  quantity: z.string().trim().min(1, "Enter the quantity.").max(32),
  repeats: z.coerce.number<string>().int().min(0).max(5),
  directions: z
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

/** Nurse (or doctor) stages a draft; a doctor reviews and signs it later. */
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
  const products = useQuery(productsQuery)
  const practitioners = useQuery(previewPractitionersQuery)
  const { data: me } = useQuery(currentUserQuery)
  const failed = products.error ?? practitioners.error ?? patients.error
  if (failed) return <ErrorState error={failed} />
  if (
    !products.data ||
    !practitioners.data ||
    !me ||
    (!patientId && !patients.data)
  )
    return (
      <div className="flex justify-center py-10 text-stone">
        <Loader2 className="animate-spin" />
      </div>
    )
  return (
    <StageScriptFields
      patientId={patientId}
      onClose={onClose}
      patients={patients.data?.data ?? []}
      products={products.data}
      doctors={practitioners.data.filter((p) => p.role === "DOCTOR")}
      meId={me.id}
    />
  )
}

function StageScriptFields({
  patientId,
  onClose,
  patients,
  products,
  doctors,
  meId,
}: {
  patientId?: string
  onClose: () => void
  patients: PatientRead[]
  products: Product[]
  doctors: Practitioner[]
  meId: string
}) {
  const queryClient = useQueryClient()

  const defaults: FormIn = {
    patient_id: patientId ?? "",
    product_id: "",
    quantity: "",
    repeats: "2",
    directions: "",
    triage_outcome: "",
    conventional_therapy: "",
    prescriber_id: doctors.some((d) => d.id === meId) ? meId : "",
    date_of_service: clinicToday(),
  }
  const form = useForm<FormIn, unknown, FormOut>({
    shouldFocusError: false,
    resolver: zodResolver(schema),
    defaultValues: defaults,
  })
  const { errors } = form.formState

  const productId = form.watch("product_id")
  const product = products.find((p) => p.id === productId)
  useEffect(() => {
    if (product && !form.getValues("quantity"))
      form.setValue("quantity", product.pack)
  }, [product, form])

  const stage = useMutation({
    mutationFn: (v: FormOut) => {
      const patient = patients.find((p) => p.id === v.patient_id)
      return scriptsRepo.stage({
        ...v,
        patient_name: patient ? patientName(patient) : "",
      })
    },
    onSuccess: async (script) => {
      await invalidateScripts(queryClient)
      if (script.gate?.matched)
        toast.success(`Staged for ${script.prescriber_name} to review`)
      else
        toast.warning(
          "Staged, but no TGA approval covers it yet. It can't be sent until one does.",
        )
      onClose()
    },
  })

  return (
    <form
      onSubmit={form.handleSubmit(
        (v) => stage.mutate(v),
        focusFirstError(form.setFocus),
      )}
      noValidate
      className="grid gap-4"
    >
      <DialogHeader>
        <DialogTitle>Stage a script</DialogTitle>
        <DialogDescription>
          Draft it with the triage outcome and conventional therapy tried first.
          The doctor reviews and signs; the safety gate checks the TGA approval
          before anything is sent.
        </DialogDescription>
      </DialogHeader>

      <div className="grid gap-4 sm:grid-cols-2">
        {!patientId ? (
          <Field
            label="Patient"
            htmlFor="sc-patient"
            error={errors.patient_id?.message}
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
          error={errors.product_id?.message}
          hint={
            product
              ? `${categoryShort(product.tga_category)} · ${formLabel(product.dosage_form)} · ${product.schedule}`
              : undefined
          }
          className="sm:col-span-2"
        >
          <select
            id="sc-product"
            className="field-input"
            {...form.register("product_id")}
          >
            <option value="">Choose from the catalogue</option>
            {products.map((p) => (
              <option key={p.id} value={p.id}>
                {p.name}
              </option>
            ))}
          </select>
        </Field>
        <Field
          label="Quantity"
          htmlFor="sc-qty"
          error={errors.quantity?.message}
        >
          <input
            id="sc-qty"
            className="field-input"
            autoComplete="off"
            {...form.register("quantity")}
          />
        </Field>
        <Field label="Repeats" htmlFor="sc-rep" error={errors.repeats?.message}>
          <input
            id="sc-rep"
            type="number"
            min={0}
            max={5}
            className="field-input"
            {...form.register("repeats")}
          />
        </Field>
        <Field
          label="Directions / titration"
          htmlFor="sc-dir"
          error={errors.directions?.message}
          className="sm:col-span-2"
        >
          <input
            id="sc-dir"
            className="field-input"
            placeholder="e.g. 0.5 mL nocte, titrate weekly"
            autoComplete="off"
            {...form.register("directions")}
          />
        </Field>
        <Field
          label="Triage outcome"
          htmlFor="sc-tri"
          error={errors.triage_outcome?.message}
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
          error={errors.conventional_therapy?.message}
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
          error={errors.prescriber_id?.message}
        >
          <select
            id="sc-doc"
            className="field-input"
            {...form.register("prescriber_id")}
          >
            <option value="">Choose</option>
            {doctors.map((d) => (
              <option key={d.id} value={d.id}>
                {d.name}
              </option>
            ))}
          </select>
        </Field>
        <Field label="Date of service" htmlFor="sc-dos">
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

/**
 * Doctor review: the gate's answer for the date of service, a password re-entry (step-up), then sign
 * and send. The gate is evaluated again at sign time; this screen only shows what it will say.
 */
export function ReviewSignDialog({
  script,
  onOpenChange,
}: {
  script: Script | null
  onOpenChange: (open: boolean) => void
}) {
  const queryClient = useQueryClient()
  const { data: me } = useQuery(currentUserQuery)
  const [password, setPassword] = useState("")
  // A different script starts with an empty password field.
  const [forScript, setForScript] = useState(script?.id)
  if (script?.id !== forScript) {
    setForScript(script?.id)
    setPassword("")
  }

  const gate = useQuery({
    queryKey: ["gate", script?.id, script?.date_of_service],
    queryFn: () => scriptsRepo.gate(script!),
    enabled: script !== null,
    staleTime: 0,
  })

  const sign = useMutation({
    mutationFn: async () => {
      try {
        await signIn(me!.email, password)
      } catch (error) {
        const status = httpStatus(error)
        if (status === 400 || status === 401)
          throw new Error("That password isn't right. Re-enter it to sign.")
        throw error
      }
      return scriptsRepo.signAndSend(script!.id)
    },
    onSuccess: async (result) => {
      await invalidateScripts(queryClient)
      if (result.state === "SENT") {
        toast.success(`Signed and sent to ${result.pharmacy}`)
        onOpenChange(false)
      } else {
        toast.error("Blocked by the safety gate. Nothing was sent.")
        await gate.refetch()
      }
    },
  })

  const s = script
  const allowed = gate.data?.matched === true
  const mine = s && me && s.prescriber_id === me.id

  return (
    <Dialog open={s !== null} onOpenChange={onOpenChange}>
      <DialogContent className="sm:max-w-[600px]">
        {s ? (
          <form
            className="grid gap-4"
            onSubmit={(e) => {
              e.preventDefault()
              sign.mutate()
            }}
          >
            <DialogHeader>
              <DialogTitle>Review & sign</DialogTitle>
              <DialogDescription>
                {s.patient_name} · drafted by {s.drafted_by_name}
              </DialogDescription>
            </DialogHeader>

            <div className="rounded-inner border border-line bg-oat px-4 py-3.5 text-sm">
              <div className="text-[15px] font-semibold">
                {s.product_name}{" "}
                <span className="font-normal text-stone">
                  · {s.quantity} · {s.repeats} repeats
                </span>
              </div>
              <div className="mt-0.5 text-stone">{s.directions}</div>
              <dl className="mt-3 grid grid-cols-[150px_minmax(0,1fr)] gap-y-1.5 text-[13px]">
                <dt className="font-semibold">Triage outcome</dt>
                <dd>{s.triage_outcome ?? "-"}</dd>
                <dt className="font-semibold">Conventional first</dt>
                <dd>{s.conventional_therapy ?? "-"}</dd>
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
                gate.isPending
                  ? "rounded-inner border border-line px-4 py-3 text-sm text-stone"
                  : allowed
                    ? "flex items-start gap-3 rounded-inner bg-ok-tint px-4 py-3 text-sm text-ok-deep"
                    : "flex items-start gap-3 rounded-inner bg-danger-tint px-4 py-3 text-sm text-danger-deep"
              }
              role="status"
            >
              {gate.isPending ? (
                "Checking the TGA approval…"
              ) : gate.isError ? (
                <>
                  <ShieldAlert className="mt-0.5 size-4 shrink-0" />
                  <span>
                    The safety gate couldn't be reached, so this can't be
                    signed. {describeError(gate.error)}
                  </span>
                </>
              ) : allowed && gate.data?.validity_interval ? (
                <>
                  <ShieldCheck className="mt-0.5 size-4 shrink-0" />
                  <span>
                    <span className="font-semibold">Safety gate: clear.</span>{" "}
                    An active approval covers {formatDate(s.date_of_service)}{" "}
                    (covered through{" "}
                    {formatDate(
                      lastCoveredDay(gate.data.validity_interval.valid_to),
                    )}
                    ).
                  </span>
                </>
              ) : (
                <>
                  <ShieldAlert className="mt-0.5 size-4 shrink-0" />
                  <span>
                    <span className="font-semibold">Safety gate: blocked.</span>{" "}
                    {gate.data?.reason_code
                      ? MATCH_REASONS[gate.data.reason_code]
                      : "No covering approval"}
                    .{" "}
                    <Mono className="text-[11.5px]">
                      {gate.data?.reason_code}
                    </Mono>
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

            {!mine ? (
              <p className="rounded-btn bg-warn-tint px-3 py-2.5 text-[13px] text-warn-deep">
                Assigned to {s.prescriber_name}. Only the assigned prescriber
                can sign it.
              </p>
            ) : (
              <Field
                label="Your password, to sign"
                htmlFor="sign-pw"
                hint="Signing a prescription needs you to re-enter your password."
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

            {sign.isError ? (
              <p
                role="alert"
                className="rounded-btn bg-danger-tint px-3 py-2.5 text-[13px] text-danger-deep"
              >
                {sign.error instanceof Error && !httpStatus(sign.error)
                  ? sign.error.message
                  : describeError(sign.error)}
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
                disabled={!mine || !allowed || !password || sign.isPending}
              >
                {sign.isPending ? <Loader2 className="animate-spin" /> : null}
                Sign & send to pharmacy
              </Button>
            </DialogFooter>
          </form>
        ) : null}
      </DialogContent>
    </Dialog>
  )
}
