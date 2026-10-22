import { zodResolver } from "@hookform/resolvers/zod"
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query"
import { Loader2 } from "lucide-react"
import { useState } from "react"
import { useForm } from "react-hook-form"
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
import {
  CANCEL_REASONS,
  type CancelReason,
  formatQuantity,
  PRESCRIPTION_STATE_LABEL,
  type Prescription,
  type PrescriptionState,
  REASON_LABEL,
  scriptHistoryQuery,
  scriptsRepo,
} from "@/data/scripts"
import {
  EmptyState,
  ErrorState,
  Field,
  FormAlert,
  Mono,
  SkeletonRows,
} from "@/design/primitives"
import { focusFirstError } from "@/lib/form"
import { formatDayMonthTime } from "@/lib/format"
import { describeError, validationMessages } from "@/lib/http"
import { uuid } from "@/lib/uuid"
import { z } from "@/lib/zod"

/**
 * Correcting a script (FEAT-11; docs2/sdlc/07-script-queue; decision D-010): edit a draft, amend a
 * signed script by a new version, cancel with a reason, and read its history. Every change waits for
 * the server's answer (no optimistic update) and then redraws the queue from it.
 */
export const invalidateScripts = (
  queryClient: ReturnType<typeof useQueryClient>,
) =>
  Promise.all([
    queryClient.invalidateQueries({ queryKey: ["scripts"] }),
    queryClient.invalidateQueries({ queryKey: ["dashboard"] }),
  ])

const correction = z.object({
  dose_instruction: z
    .string()
    .trim()
    .min(3, "Enter the directions for use.")
    .max(500),
  quantity: z
    .string()
    .trim()
    .regex(/^\d{1,8}(\.\d{1,2})?$/, "Enter a quantity, e.g. 1 or 2.5.")
    .refine((v) => Number(v) > 0, "The quantity must be more than zero."),
  repeats: z.coerce.number<string>().int().min(0).max(12),
  date_of_service: z.string().regex(/^\d{4}-\d{2}-\d{2}$/),
})
type CorrectionIn = z.input<typeof correction>
type CorrectionOut = z.output<typeof correction>

/** Only the fields that changed: the server records their names, and a no-op is refused. */
function changedFields(script: Prescription, values: CorrectionOut) {
  const changes: Partial<CorrectionOut> & { quantity?: string } = {}
  if (values.dose_instruction !== script.dose_instruction)
    changes.dose_instruction = values.dose_instruction
  if (Number(values.quantity) !== Number(script.quantity))
    changes.quantity = values.quantity
  if (values.repeats !== script.repeats) changes.repeats = values.repeats
  if (values.date_of_service !== script.date_of_service)
    changes.date_of_service = values.date_of_service
  return changes
}

/**
 * Edit a draft in place, or (`amend`) correct a signed script: the server creates a new draft that
 * replaces it, and the original stays as it was signed.
 */
export function CorrectionForm({
  script,
  amend,
  onDone,
  onBack,
}: {
  script: Prescription
  amend: boolean
  onDone: () => void
  onBack: () => void
}) {
  const queryClient = useQueryClient()
  // One intent per opening of the form: a retried submit answers with the same addendum.
  const [intent] = useState(() => uuid())
  const form = useForm<CorrectionIn, unknown, CorrectionOut>({
    shouldFocusError: false,
    resolver: zodResolver(correction),
    defaultValues: {
      dose_instruction: script.dose_instruction,
      quantity: formatQuantity(script.quantity),
      repeats: String(script.repeats),
      date_of_service: script.date_of_service,
    },
  })
  const [unchanged, setUnchanged] = useState(false)
  const save = useMutation({
    mutationFn: (changes: ReturnType<typeof changedFields>) =>
      amend
        ? scriptsRepo.amend(script.id, changes, intent)
        : scriptsRepo.update(script.id, changes),
    onSuccess: async () => {
      await invalidateScripts(queryClient)
      toast.success(
        amend
          ? "Addendum drafted. Review and sign it to replace the original."
          : "Draft updated.",
      )
      onDone()
    },
    onError: async () => {
      await invalidateScripts(queryClient)
    },
  })
  const { errors } = form.formState
  const server = validationMessages(save.error)
  const fieldError = (name: keyof CorrectionIn) =>
    errors[name]?.message ?? server[name]

  return (
    <form
      noValidate
      className="grid gap-4"
      onSubmit={form.handleSubmit((values) => {
        const changes = changedFields(script, values)
        if (Object.keys(changes).length === 0) {
          setUnchanged(true)
          return
        }
        setUnchanged(false)
        save.mutate(changes)
      }, focusFirstError)}
    >
      <DialogHeader>
        <DialogTitle>
          {amend ? "Amend signed script" : "Edit draft"}
        </DialogTitle>
        <DialogDescription>
          {amend
            ? "A signed script is never edited. Your correction becomes a new draft that replaces it once signed; the original is kept, unchanged."
            : "The draft changes in place. Nothing is signed or sent."}
        </DialogDescription>
      </DialogHeader>
      <p className="text-sm">
        <span className="font-semibold">{script.medicine_name}</span>{" "}
        <span className="text-stone">· {script.patient_name ?? "Patient"}</span>
      </p>
      <Field
        label="Directions"
        htmlFor="fix-dose"
        error={fieldError("dose_instruction")}
      >
        <input
          id="fix-dose"
          className="field-input"
          aria-invalid={fieldError("dose_instruction") ? "true" : undefined}
          {...form.register("dose_instruction")}
        />
      </Field>
      <div className="grid gap-4 sm:grid-cols-3">
        <Field
          label="Quantity"
          htmlFor="fix-qty"
          error={fieldError("quantity")}
        >
          <input
            id="fix-qty"
            inputMode="decimal"
            className="field-input"
            aria-invalid={fieldError("quantity") ? "true" : undefined}
            {...form.register("quantity")}
          />
        </Field>
        <Field label="Repeats" htmlFor="fix-rep" error={fieldError("repeats")}>
          <input
            id="fix-rep"
            type="number"
            min={0}
            max={12}
            className="field-input"
            aria-invalid={fieldError("repeats") ? "true" : undefined}
            {...form.register("repeats")}
          />
        </Field>
        <Field
          label="Date of service"
          htmlFor="fix-dos"
          error={fieldError("date_of_service")}
        >
          <input
            id="fix-dos"
            type="date"
            className="field-input"
            {...form.register("date_of_service")}
          />
        </Field>
      </div>
      {unchanged ? (
        <FormAlert>Change at least one detail first.</FormAlert>
      ) : null}
      {save.isError ? <FormAlert>{describeError(save.error)}</FormAlert> : null}
      <DialogFooter>
        <Button type="button" variant="outline" onClick={onBack}>
          Back
        </Button>
        <Button type="submit" disabled={save.isPending}>
          {save.isPending ? <Loader2 className="animate-spin" /> : null}
          {amend ? "Draft addendum" : "Save draft"}
        </Button>
      </DialogFooter>
    </form>
  )
}

/** Cancel before anything is sent, with a reason code (never free text). */
export function CancelForm({
  script,
  onDone,
  onBack,
}: {
  script: Prescription
  onDone: () => void
  onBack: () => void
}) {
  const queryClient = useQueryClient()
  const [reason, setReason] = useState<CancelReason | "">("")
  const [missing, setMissing] = useState(false)
  const cancel = useMutation({
    mutationFn: (code: CancelReason) => scriptsRepo.cancel(script.id, code),
    onSuccess: async () => {
      await invalidateScripts(queryClient)
      toast.success("Script cancelled.")
      onDone()
    },
    onError: async () => {
      await invalidateScripts(queryClient)
    },
  })
  return (
    <form
      noValidate
      className="grid gap-4"
      onSubmit={(e) => {
        e.preventDefault()
        if (!reason) {
          setMissing(true)
          document.getElementById("cancel-reason")?.focus()
          return
        }
        cancel.mutate(reason)
      }}
    >
      <DialogHeader>
        <DialogTitle>Cancel script</DialogTitle>
        <DialogDescription>
          {script.medicine_name} for {script.patient_name ?? "this patient"}. A
          cancelled script can't be signed or sent, and stays in the record.
        </DialogDescription>
      </DialogHeader>
      <Field
        label="Reason"
        htmlFor="cancel-reason"
        error={missing && !reason ? "Choose why it is cancelled." : undefined}
      >
        <select
          id="cancel-reason"
          className="field-input"
          value={reason}
          aria-invalid={missing && !reason ? "true" : undefined}
          onChange={(e) => {
            setReason(e.target.value as CancelReason | "")
            cancel.reset()
          }}
        >
          <option value="">Choose a reason</option>
          {Object.entries(CANCEL_REASONS).map(([code, label]) => (
            <option key={code} value={code}>
              {label}
            </option>
          ))}
        </select>
      </Field>
      {cancel.isError ? (
        <FormAlert>{describeError(cancel.error)}</FormAlert>
      ) : null}
      <DialogFooter>
        <Button type="button" variant="outline" onClick={onBack}>
          Back
        </Button>
        <Button type="submit" variant="destructive" disabled={cancel.isPending}>
          {cancel.isPending ? <Loader2 className="animate-spin" /> : null}
          Cancel script
        </Button>
      </DialogFooter>
    </form>
  )
}

const stateLabel = (state: string | null | undefined) =>
  state ? (PRESCRIPTION_STATE_LABEL[state as PrescriptionState] ?? state) : ""

/** Every transition of one script, oldest first: what, who, when and why. */
export function ScriptHistory({ script }: { script: Prescription }) {
  const history = useQuery(scriptHistoryQuery(script.id))
  if (history.isPending) return <SkeletonRows rows={3} />
  if (history.isError)
    return (
      <ErrorState error={history.error} onRetry={() => history.refetch()} />
    )
  const { data, supersedes_id, superseded_by_id } = history.data
  if (data.length === 0) return <EmptyState title="No history recorded." />
  return (
    <div className="grid gap-3">
      <ol className="grid gap-2.5" data-testid="script-history">
        {data.map((event) => (
          <li
            key={`${event.occurred_at}-${event.to_state}`}
            className="grid grid-cols-[minmax(0,1fr)_auto] gap-x-3 rounded-inner border border-line px-3.5 py-2.5 text-sm"
          >
            <span className="font-medium">
              {event.from_state
                ? `${stateLabel(event.from_state)} → ${stateLabel(event.to_state)}`
                : `Staged: ${stateLabel(event.to_state)}`}
            </span>
            <Mono className="text-[11.5px] text-stone">
              {formatDayMonthTime(event.occurred_at)}
            </Mono>
            <span className="text-[13px] text-stone">
              {event.actor_name ?? "System"}
              {event.reason
                ? ` · ${REASON_LABEL[event.reason] ?? event.reason}`
                : ""}
            </span>
          </li>
        ))}
      </ol>
      {supersedes_id ? (
        <p className="text-[13px] text-stone">
          This script is an addendum: it corrects an earlier signed script.
        </p>
      ) : null}
      {superseded_by_id ? (
        <p className="text-[13px] text-stone">
          Replaced by an addendum: the original is kept as it was signed.
        </p>
      ) : null}
    </div>
  )
}

/** The history on its own, for a script with nothing left to do (the patient's Scripts tab). */
export function ScriptHistoryDialog({
  script,
  onOpenChange,
}: {
  script: Prescription | null
  onOpenChange: (open: boolean) => void
}) {
  return (
    <Dialog open={script !== null} onOpenChange={onOpenChange}>
      <DialogContent className="sm:max-w-[560px]">
        {script ? (
          <div className="grid gap-4">
            <DialogHeader>
              <DialogTitle>Script history</DialogTitle>
              <DialogDescription>
                {script.medicine_name} · {script.patient_name ?? "Patient"}
              </DialogDescription>
            </DialogHeader>
            <ScriptHistory script={script} />
            <DialogFooter>
              <Button
                type="button"
                variant="outline"
                onClick={() => onOpenChange(false)}
              >
                Close
              </Button>
            </DialogFooter>
          </div>
        ) : null}
      </DialogContent>
    </Dialog>
  )
}
