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
  approvalsRepo,
  CREATION_REASONS,
  categoryShort,
  DOSAGE_FORMS,
  formLabel,
  REVOKE_REASONS,
  TGA_CATEGORIES,
} from "@/data/approvals"
import { patientName, patientsQuery } from "@/data/patients"
import type { TgaApproval } from "@/data/types"
import { Field, Mono } from "@/design/primitives"
import { focusFirstError } from "@/lib/form"
import { clinicToday, formatDate, lastCoveredDay } from "@/lib/format"
import { describeError } from "@/lib/http"
import { z } from "@/lib/zod"

const invalidateApprovals = (queryClient: ReturnType<typeof useQueryClient>) =>
  Promise.all([
    queryClient.invalidateQueries({ queryKey: ["approvals"] }),
    queryClient.invalidateQueries({ queryKey: ["dashboard"] }),
    queryClient.invalidateQueries({ queryKey: ["scripts"] }),
  ])

const twoYearsAfter = (iso: string) =>
  `${Number(iso.slice(0, 4)) + 2}${iso.slice(4)}`

/**
 * The end date is entered exactly as printed on the TGA letter and sent unchanged as `valid_to`.
 *
 * D-006 is open on whether that printed day is covered. Until the Clinical Safety Officer rules, the
 * backend's interim fail-safe reading is half-open, `[valid_from, valid_to)`: the printed end date is
 * NOT covered. The UI must not "correct" the date (for example by adding a day), because that would
 * make the window fail wide, which is the dangerous direction. The hint says so (ADR-F003).
 */
const schema = z
  .object({
    patient_id: z.string().min(1, "Choose the patient."),
    tga_category: z.string().min(1),
    dosage_form: z.string().min(1),
    approval_reference: z
      .string()
      .trim()
      .regex(
        /^[A-Za-z0-9][A-Za-z0-9/_. -]{0,63}$/,
        "Enter the reference as printed on the TGA letter.",
      ),
    creation_reason: z.string().min(1),
    valid_from: z
      .string()
      .regex(/^\d{4}-\d{2}-\d{2}$/, "Enter the start date."),
    valid_to: z
      .string()
      .regex(/^\d{4}-\d{2}-\d{2}$/, "Enter the end date from the letter."),
  })
  .refine((v) => v.valid_to > v.valid_from, {
    path: ["valid_to"],
    message: "The end date must be after the start date.",
  })
  .refine((v) => v.valid_to <= twoYearsAfter(v.valid_from), {
    path: ["valid_to"],
    message: "An approval can't be valid for more than two years.",
  })
type Values = z.infer<typeof schema>

export function RecordApprovalDialog({
  open,
  onOpenChange,
  patientId,
}: {
  open: boolean
  onOpenChange: (open: boolean) => void
  /** Fix the patient (from a patient record); otherwise the dialog offers a picker. */
  patientId?: string
}) {
  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="sm:max-w-[580px]">
        <RecordApprovalForm
          patientId={patientId}
          onClose={() => onOpenChange(false)}
        />
      </DialogContent>
    </Dialog>
  )
}

/** Mounted fresh each time the dialog opens, so it always starts from its defaults. */
function RecordApprovalForm({
  patientId,
  onClose,
}: {
  patientId?: string
  onClose: () => void
}) {
  const queryClient = useQueryClient()
  const patients = useQuery({ ...patientsQuery, enabled: !patientId })
  const today = clinicToday()
  const defaults: Values = {
    patient_id: patientId ?? "",
    tga_category: "CATEGORY_3",
    dosage_form: "ORAL_LIQUID",
    approval_reference: "",
    creation_reason: "NEW_APPLICATION",
    valid_from: today,
    valid_to: "",
  }
  const form = useForm<Values>({
    shouldFocusError: false,
    resolver: zodResolver(schema),
    defaultValues: defaults,
  })
  const { errors } = form.formState

  const create = useMutation({
    mutationFn: (v: Values) => approvalsRepo.create(v),
    onSuccess: async () => {
      await invalidateApprovals(queryClient)
      toast.success(
        "Approval recorded. A second clinician must verify it before it can authorise a script.",
      )
      onClose()
    },
  })

  return (
    <form
      onSubmit={form.handleSubmit((v) => create.mutate(v), focusFirstError)}
      noValidate
      className="grid gap-4"
    >
      <DialogHeader>
        <DialogTitle>Record a TGA approval</DialogTitle>
        <DialogDescription>
          Enter it exactly as the TGA issued it. It stays pending until another
          clinician checks it against the letter.
        </DialogDescription>
      </DialogHeader>

      {!patientId ? (
        <Field
          label="Patient"
          htmlFor="ap-patient"
          error={errors.patient_id?.message}
        >
          <select
            id="ap-patient"
            className="field-input"
            {...form.register("patient_id")}
          >
            <option value="">
              {patients.isPending ? "Loading patients…" : "Choose a patient"}
            </option>
            {patients.data?.data.map((p) => (
              <option key={p.id} value={p.id}>
                {patientName(p)}
              </option>
            ))}
          </select>
        </Field>
      ) : null}

      <div className="grid gap-4 sm:grid-cols-2">
        <Field label="TGA category" htmlFor="ap-cat">
          <select
            id="ap-cat"
            className="field-input"
            {...form.register("tga_category")}
          >
            {Object.entries(TGA_CATEGORIES).map(([v, l]) => (
              <option key={v} value={v}>
                {l}
              </option>
            ))}
          </select>
        </Field>
        <Field label="Dosage form" htmlFor="ap-form">
          <select
            id="ap-form"
            className="field-input"
            {...form.register("dosage_form")}
          >
            {Object.entries(DOSAGE_FORMS).map(([v, l]) => (
              <option key={v} value={v}>
                {l}
              </option>
            ))}
          </select>
        </Field>
        <Field
          label="TGA reference"
          htmlFor="ap-ref"
          error={errors.approval_reference?.message}
          hint="e.g. SAS-B 2026-114592"
        >
          <input
            id="ap-ref"
            className="field-input font-mono"
            autoComplete="off"
            {...form.register("approval_reference")}
          />
        </Field>
        <Field label="Reason" htmlFor="ap-reason">
          <select
            id="ap-reason"
            className="field-input"
            {...form.register("creation_reason")}
          >
            {Object.entries(CREATION_REASONS).map(([v, l]) => (
              <option key={v} value={v}>
                {l}
              </option>
            ))}
          </select>
        </Field>
        <Field
          label="Valid from"
          htmlFor="ap-from"
          error={errors.valid_from?.message}
        >
          <input
            id="ap-from"
            type="date"
            className="field-input"
            {...form.register("valid_from")}
          />
        </Field>
        <Field
          label="Valid to (as on the letter)"
          htmlFor="ap-to"
          error={errors.valid_to?.message}
          hint="Two years at most"
        >
          <input
            id="ap-to"
            type="date"
            className="field-input"
            {...form.register("valid_to")}
          />
        </Field>
      </div>

      <p className="rounded-btn bg-info-tint px-3 py-2.5 text-[13px] text-info-deep">
        Until the clinical safety ruling on end dates (D-006), the end date
        itself is <span className="font-semibold">not</span> covered: a script
        dated that day will be blocked. Enter the date exactly as printed; don't
        adjust it.
      </p>

      {create.isError ? (
        <p
          role="alert"
          className="rounded-btn bg-danger-tint px-3 py-2.5 text-[13px] text-danger-deep"
        >
          {describeError(create.error)}
        </p>
      ) : null}

      <DialogFooter>
        <Button type="button" variant="outline" onClick={() => onClose()}>
          Cancel
        </Button>
        <Button type="submit" disabled={create.isPending}>
          {create.isPending ? <Loader2 className="animate-spin" /> : null}
          Record approval
        </Button>
      </DialogFooter>
    </form>
  )
}

function ApprovalSummary({ approval }: { approval: TgaApproval }) {
  return (
    <dl className="grid grid-cols-[120px_minmax(0,1fr)] gap-y-2 rounded-inner bg-oat px-4 py-3 text-sm">
      <dt className="text-stone">Category</dt>
      <dd>
        {categoryShort(approval.tga_category)} ·{" "}
        {formLabel(approval.dosage_form)}
      </dd>
      <dt className="text-stone">Window</dt>
      <dd>
        {formatDate(approval.valid_from)} to {formatDate(approval.valid_to)}
        <span className="text-stone">
          {" "}
          (covered through {formatDate(lastCoveredDay(approval.valid_to))})
        </span>
      </dd>
    </dl>
  )
}

/** Four-eyes step 2: the verifier re-types the reference from the TGA letter. */
export function VerifyApprovalDialog({
  approval,
  onOpenChange,
}: {
  approval: TgaApproval | null
  onOpenChange: (open: boolean) => void
}) {
  const queryClient = useQueryClient()
  const [reference, setReference] = useState("")
  // A different approval starts with an empty reference field.
  const [forApproval, setForApproval] = useState(approval?.id)
  if (approval?.id !== forApproval) {
    setForApproval(approval?.id)
    setReference("")
  }
  const verify = useMutation({
    mutationFn: () => approvalsRepo.verify(approval!.id, reference),
    onSuccess: async () => {
      await invalidateApprovals(queryClient)
      toast.success("Approval verified and active")
      onOpenChange(false)
    },
  })
  return (
    <Dialog open={approval !== null} onOpenChange={onOpenChange}>
      <DialogContent>
        {approval ? (
          <form
            className="grid gap-4"
            onSubmit={(e) => {
              e.preventDefault()
              verify.mutate()
            }}
          >
            <DialogHeader>
              <DialogTitle>Verify approval</DialogTitle>
              <DialogDescription>
                Check this against the TGA letter, then type the reference
                exactly as it's printed. The person who entered it can't verify
                it.
              </DialogDescription>
            </DialogHeader>
            <ApprovalSummary approval={approval} />
            <Field label="TGA reference from the letter" htmlFor="verify-ref">
              <input
                id="verify-ref"
                className="field-input font-mono"
                autoComplete="off"
                autoFocus
                value={reference}
                onChange={(e) => setReference(e.target.value)}
              />
            </Field>
            {verify.isError ? (
              <p
                role="alert"
                className="rounded-btn bg-danger-tint px-3 py-2.5 text-[13px] text-danger-deep"
              >
                {describeError(verify.error)}
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
              <Button
                type="submit"
                disabled={!reference.trim() || verify.isPending}
              >
                {verify.isPending ? <Loader2 className="animate-spin" /> : null}
                Verify and activate
              </Button>
            </DialogFooter>
          </form>
        ) : null}
      </DialogContent>
    </Dialog>
  )
}

export function RevokeApprovalDialog({
  approval,
  onOpenChange,
}: {
  approval: TgaApproval | null
  onOpenChange: (open: boolean) => void
}) {
  const queryClient = useQueryClient()
  const [reason, setReason] = useState("CLINICAL_DECISION")
  const revoke = useMutation({
    mutationFn: () => approvalsRepo.revoke(approval!.id, reason),
    onSuccess: async () => {
      await invalidateApprovals(queryClient)
      toast.success("Approval revoked")
      onOpenChange(false)
    },
  })
  return (
    <Dialog open={approval !== null} onOpenChange={onOpenChange}>
      <DialogContent>
        {approval ? (
          <div className="grid gap-4">
            <DialogHeader>
              <DialogTitle>Revoke approval</DialogTitle>
              <DialogDescription>
                Scripts can't be sent against a revoked approval. This can't be
                undone; a new grant must be recorded and verified.
              </DialogDescription>
            </DialogHeader>
            <ApprovalSummary approval={approval} />
            <p className="text-sm">
              Reference <Mono>{approval.approval_reference}</Mono>
            </p>
            <Field label="Reason" htmlFor="revoke-reason">
              <select
                id="revoke-reason"
                className="field-input"
                value={reason}
                onChange={(e) => setReason(e.target.value)}
              >
                {Object.entries(REVOKE_REASONS).map(([v, l]) => (
                  <option key={v} value={v}>
                    {l}
                  </option>
                ))}
              </select>
            </Field>
            {revoke.isError ? (
              <p
                role="alert"
                className="rounded-btn bg-danger-tint px-3 py-2.5 text-[13px] text-danger-deep"
              >
                {describeError(revoke.error)}
              </p>
            ) : null}
            <DialogFooter>
              <Button
                type="button"
                variant="outline"
                onClick={() => onOpenChange(false)}
              >
                Keep approval
              </Button>
              <Button
                variant="destructive"
                disabled={revoke.isPending}
                onClick={() => revoke.mutate()}
              >
                {revoke.isPending ? <Loader2 className="animate-spin" /> : null}
                Revoke
              </Button>
            </DialogFooter>
          </div>
        ) : null}
      </DialogContent>
    </Dialog>
  )
}
