import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query"
import { Link } from "@tanstack/react-router"
import { ArrowLeft, ExternalLink, Loader2, ShieldAlert } from "lucide-react"
import { useEffect, useId, useMemo, useState } from "react"
import { toast } from "sonner"
import type { InboxMessageDetail } from "@/client/types.gen"
import { Button } from "@/components/ui/button"
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog"
import { DOSAGE_FORMS, TGA_CATEGORIES } from "@/data/approvals"
import {
  APPROVAL_FIELDS,
  CORRECTION_REASONS,
  confidenceTone,
  FIELD_LABELS,
  FIELD_ORDER,
  type FieldName,
  inboxMessageQuery,
  inboxPdfQuery,
  inboxRepo,
  REFUSAL_REASONS,
  REJECT_REASONS,
  STATE_REASONS,
} from "@/data/inbox"
import {
  Card,
  EmptyState,
  ErrorState,
  Field,
  FormAlert,
  Mono,
  PageHeader,
  Pill,
  SkeletonRows,
} from "@/design/primitives"
import { PatientPicker } from "@/features/shared/PatientPicker"
import { formatDate, formatDayMonthTime } from "@/lib/format"
import { describeError } from "@/lib/http"
import { currentUserQuery } from "@/lib/session"

type Values = Partial<Record<FieldName, string>>

const DATE_FIELDS: FieldName[] = ["VALID_FROM", "VALID_TO", "PATIENT_DOB"]
const VOCABULARY: Partial<Record<FieldName, Record<string, string>>> = {
  TGA_CATEGORY: TGA_CATEGORIES,
  DOSAGE_FORM: DOSAGE_FORMS,
}

const leaseIsLive = (m: InboxMessageDetail) =>
  m.lease_expires_at != null && new Date(m.lease_expires_at) > new Date()

/**
 * One inbox message under review (FEAT-09 R15, R16): the PDF beside what was read from it, every
 * value with its confidence and page, the patients the server proposes (none pre-selected), and the
 * four decisions. The server enforces all of it: the claim, the correction reason, the mandatory
 * fields and the approval rules. This screen only makes the right path the easy one.
 */
export function ReviewPage({ messageId }: { messageId: string }) {
  const message = useQuery(inboxMessageQuery(messageId))
  const me = useQuery(currentUserQuery)

  if (message.isPending) return <SkeletonRows rows={8} />
  if (message.isError)
    return (
      <ErrorState error={message.error} onRetry={() => message.refetch()} />
    )

  const m = message.data
  const open =
    m.processing_state === "EXTRACTED" || m.processing_state === "FAILED"
  const mine = open && m.claimed_by === me.data?.id && leaseIsLive(m)
  const takenByOther =
    open &&
    m.claimed_by != null &&
    m.claimed_by !== me.data?.id &&
    leaseIsLive(m)

  return (
    <>
      <Link
        to="/tga-inbox"
        className="mb-3 inline-flex items-center gap-1.5 text-sm text-stone hover:text-ink"
      >
        <ArrowLeft className="size-4" /> TGA inbox
      </Link>
      <PageHeader
        title={m.subject || "(no subject)"}
        subtitle={
          <>
            From <Mono>{m.from_address}</Mono>, received{" "}
            {formatDayMonthTime(m.received_at)}
          </>
        }
      />
      <SenderChecks message={m} />
      <div className="grid gap-5 lg:grid-cols-[minmax(0,1.1fr)_minmax(0,1fr)]">
        <Documents message={m} />
        <div className="grid content-start gap-5">
          {open ? null : <Decided message={m} />}
          {open && m.state_reason ? (
            <FormAlert>
              {STATE_REASONS[m.state_reason] ?? m.state_reason}
            </FormAlert>
          ) : null}
          {takenByOther ? (
            <FormAlert>
              Another reviewer is working on this letter. It returns to the
              queue if they leave it for 15 minutes.
            </FormAlert>
          ) : null}
          {open ? (
            <ReviewForm
              key={`${m.id}-${mine}`}
              message={m}
              editing={mine}
              canClaim={!takenByOther}
            />
          ) : (
            <ReadOnlyFields message={m} />
          )}
        </div>
      </div>
    </>
  )
}

function SenderChecks({ message }: { message: InboxMessageDetail }) {
  const results = [
    ["SPF", message.spf_result],
    ["DKIM", message.dkim_result],
    ["DMARC", message.dmarc_result],
  ] as const
  const untrusted = message.state_reason === "UNTRUSTED_SENDER"
  return (
    <div className="mb-5 flex flex-wrap items-center gap-2 text-sm text-stone">
      {untrusted ? (
        <ShieldAlert className="size-4 text-danger" aria-hidden />
      ) : null}
      <span>Sender checks:</span>
      {results.map(([name, value]) => (
        <Pill
          key={name}
          tone={value === "PASS" ? "ok" : value ? "danger" : "neutral"}
        >
          {name} {value ?? "not reported"}
        </Pill>
      ))}
    </div>
  )
}

function Documents({ message }: { message: InboxMessageDetail }) {
  const viewable = message.attachments.filter((a) => a.viewable)
  const [selected, setSelected] = useState(viewable[0]?.id)
  const refused = message.attachments.filter((a) => !a.viewable)
  return (
    <Card title="Letter" className="lg:sticky lg:top-4 lg:self-start">
      {viewable.length > 1 ? (
        <div className="mb-3 flex flex-wrap gap-1.5" role="tablist">
          {viewable.map((a) => (
            <button
              key={a.id}
              type="button"
              role="tab"
              aria-selected={selected === a.id}
              onClick={() => setSelected(a.id)}
              className="rounded-full border border-line px-3 py-1 text-[13px] aria-selected:border-clay aria-selected:bg-clay-tint"
            >
              {a.filename}
            </button>
          ))}
        </div>
      ) : null}
      {selected ? (
        <PdfFrame attachmentId={selected} />
      ) : (
        <EmptyState
          title="No file passed the checks."
          body="Nothing from this message was stored, so there is nothing to show."
        />
      )}
      {refused.length > 0 ? (
        <ul className="mt-3 grid gap-1.5 text-sm">
          {refused.map((a) => (
            <li key={a.id} className="flex flex-wrap items-center gap-2">
              <Pill tone="danger">Refused</Pill>
              <span className="text-stone">{a.filename}</span>
              <span className="text-stone-faint">
                {a.refusal_reason
                  ? (REFUSAL_REASONS[a.refusal_reason] ?? a.refusal_reason)
                  : null}
              </span>
            </li>
          ))}
        </ul>
      ) : null}
    </Card>
  )
}

function PdfFrame({ attachmentId }: { attachmentId: string }) {
  const pdf = useQuery(inboxPdfQuery(attachmentId))
  const [url, setUrl] = useState<string>()
  useEffect(() => {
    if (!pdf.data) return
    const next = URL.createObjectURL(
      new Blob([pdf.data], { type: "application/pdf" }),
    )
    setUrl(next)
    return () => URL.revokeObjectURL(next)
  }, [pdf.data])

  if (pdf.isPending) return <SkeletonRows rows={6} />
  if (pdf.isError)
    return <ErrorState error={pdf.error} onRetry={() => pdf.refetch()} />
  if (!url) return null
  return (
    <div className="grid gap-2">
      <iframe
        title="TGA letter (PDF)"
        src={url}
        className="h-[70vh] min-h-[420px] w-full rounded-inner border border-line bg-oat"
      />
      <a
        href={url}
        target="_blank"
        rel="noopener noreferrer"
        className="inline-flex items-center gap-1.5 text-sm text-stone hover:text-ink"
      >
        <ExternalLink className="size-4" /> Open in a new tab
      </a>
    </div>
  )
}

function useExtracted(message: InboxMessageDetail) {
  // The source document is the first stored attachment that has values; accept names it.
  const source =
    message.attachments.find(
      (a) => a.viewable && message.fields.some((f) => f.attachment_id === a.id),
    ) ?? message.attachments.find((a) => a.viewable)
  const fields = message.fields.filter((f) => f.attachment_id === source?.id)
  const byName = Object.fromEntries(
    fields.map((f) => [f.field_name, f]),
  ) as Partial<Record<FieldName, (typeof fields)[number]>>
  return { source, byName }
}

function ConfidenceNote({
  field,
}: {
  field?: InboxMessageDetail["fields"][number]
}) {
  if (!field || field.value == null) return <Pill tone="danger">Not read</Pill>
  return (
    <span className="inline-flex items-center gap-1.5">
      <Pill
        tone={confidenceTone(field.confidence, field.below_floor)}
        title={`Found by ${field.method?.toLowerCase().replace(/_/g, " ")}`}
      >
        {Number(field.confidence).toFixed(2)}
      </Pill>
      {field.page_number ? (
        <span className="text-xs text-stone-faint">p.{field.page_number}</span>
      ) : null}
    </span>
  )
}

function ReviewForm({
  message,
  editing,
  canClaim,
}: {
  message: InboxMessageDetail
  editing: boolean
  canClaim: boolean
}) {
  const queryClient = useQueryClient()
  const formId = useId()
  const { source, byName } = useExtracted(message)
  const initial = useMemo<Values>(
    () =>
      Object.fromEntries(
        FIELD_ORDER.map((name) => [name, byName[name]?.value ?? ""]),
      ),
    [byName],
  )
  const [values, setValues] = useState<Values>(initial)
  const [patientId, setPatientId] = useState("")
  const [otherPatient, setOtherPatient] = useState(false)
  const [reason, setReason] = useState("")
  const [rejecting, setRejecting] = useState(false)
  const untrusted = message.state_reason === "UNTRUSTED_SENDER"

  const changed = FIELD_ORDER.filter(
    (name) => (values[name] ?? "").trim() !== (initial[name] ?? "").trim(),
  )
  const missing = APPROVAL_FIELDS.filter((name) => !(values[name] ?? "").trim())

  const refresh = () =>
    Promise.all([
      queryClient.invalidateQueries({ queryKey: ["inbox"] }),
      queryClient.invalidateQueries({ queryKey: ["approvals"] }),
    ])

  const claim = useMutation({
    mutationFn: () => inboxRepo.claim(message.id),
    onSuccess: (detail) => {
      queryClient.setQueryData(["inbox", "message", message.id], detail)
    },
    onError: (error) => toast.error(describeError(error)),
  })
  const defer = useMutation({
    mutationFn: () => inboxRepo.defer(message.id),
    onSuccess: async () => {
      toast.success("Returned to the queue")
      await refresh()
    },
    onError: (error) => toast.error(describeError(error)),
  })
  const accept = useMutation({
    mutationFn: () =>
      inboxRepo.accept(message.id, {
        patient_id: patientId,
        attachment_id: source?.id ?? "",
        values: Object.fromEntries(
          changed.map((name) => [name, (values[name] ?? "").trim()]),
        ),
        correction_reason: changed.length > 0 ? reason || null : null,
      }),
    onSuccess: async () => {
      toast.success(
        "Accepted. A pending approval was recorded; a second clinician must verify it on the register.",
      )
      await refresh()
    },
  })

  const blocked =
    !patientId ||
    missing.length > 0 ||
    (changed.length > 0 && !reason) ||
    !source

  return (
    <Card
      title={
        untrusted
          ? "Unverified sender"
          : editing
            ? "Check and accept"
            : "What was read"
      }
      action={
        editing ? (
          <Pill tone="clay">You're reviewing</Pill>
        ) : canClaim ? (
          <Button
            size="sm"
            onClick={() => claim.mutate()}
            disabled={claim.isPending}
          >
            {claim.isPending ? <Loader2 className="animate-spin" /> : null}
            Start review
          </Button>
        ) : null
      }
    >
      <form
        id={formId}
        className="grid gap-5"
        onSubmit={(event) => {
          event.preventDefault()
          if (!blocked) accept.mutate()
        }}
      >
        {untrusted ? (
          <p className="text-sm text-stone">
            Nothing was read: the sender could not be verified, so no attachment
            was opened. Reject it, or ask the TGA to resend from its verified
            address.
          </p>
        ) : (
          <>
            <fieldset className="grid gap-3" disabled={!editing || untrusted}>
              <legend className="mb-1 text-[13px] font-semibold text-ink">
                The approval
              </legend>
              {APPROVAL_FIELDS.map((name) => (
                <FieldRow
                  key={name}
                  name={name}
                  value={values[name] ?? ""}
                  extracted={byName[name]}
                  changed={changed.includes(name)}
                  onChange={(v) => setValues((s) => ({ ...s, [name]: v }))}
                />
              ))}
              <p className="text-xs text-stone">
                Enter the end date exactly as printed. The printed day itself is
                not covered (D-006).
              </p>
            </fieldset>

            <fieldset className="grid gap-3" disabled={!editing || untrusted}>
              <legend className="mb-1 text-[13px] font-semibold text-ink">
                Patient and prescriber, as read
              </legend>
              {FIELD_ORDER.filter((n) => !APPROVAL_FIELDS.includes(n)).map(
                (name) => (
                  <FieldRow
                    key={name}
                    name={name}
                    value={values[name] ?? ""}
                    extracted={byName[name]}
                    changed={changed.includes(name)}
                    onChange={(v) => setValues((s) => ({ ...s, [name]: v }))}
                  />
                ),
              )}
            </fieldset>
          </>
        )}

        {editing && !untrusted ? (
          <>
            <fieldset className="grid gap-2">
              <legend className="mb-1 text-[13px] font-semibold text-ink">
                Which patient is this?
              </legend>
              {message.candidates.length === 0 ? (
                <p className="text-sm text-stone">
                  No patient matched on two identifiers. Find them below, or
                  reject the letter if they are not at this clinic.
                </p>
              ) : (
                <p className="text-xs text-stone">
                  Proposed because these identifiers agree. Nothing is chosen
                  for you.
                </p>
              )}
              {message.candidates.map((c) => (
                <label
                  key={c.patient_id}
                  className="flex cursor-pointer items-center gap-3 rounded-inner border border-line px-3 py-2.5 has-[:checked]:border-clay has-[:checked]:bg-clay-tint"
                >
                  <input
                    type="radio"
                    name={`${formId}-patient`}
                    checked={!otherPatient && patientId === c.patient_id}
                    onChange={() => {
                      setOtherPatient(false)
                      setPatientId(c.patient_id)
                    }}
                  />
                  <span className="font-medium text-ink">{c.display_name}</span>
                  <Mono className="text-stone">
                    {formatDate(c.date_of_birth)}
                  </Mono>
                  <span className="ml-auto flex gap-1">
                    {c.agreed.map((id) => (
                      <Pill key={id} tone="info">
                        {id}
                      </Pill>
                    ))}
                  </span>
                </label>
              ))}
              {message.candidates.length > 0 ? (
                <label className="flex items-center gap-3 px-3 py-1.5 text-sm">
                  <input
                    type="radio"
                    name={`${formId}-patient`}
                    checked={otherPatient}
                    onChange={() => {
                      setOtherPatient(true)
                      setPatientId("")
                    }}
                  />
                  Someone else
                </label>
              ) : null}
              {otherPatient || message.candidates.length === 0 ? (
                <PatientPicker
                  id={`${formId}-find`}
                  value={patientId}
                  onChange={setPatientId}
                />
              ) : null}
            </fieldset>

            {changed.length > 0 ? (
              <Field
                label="Why were values changed?"
                htmlFor={`${formId}-reason`}
                hint={`Changed: ${changed.map((n) => FIELD_LABELS[n]).join(", ")}`}
              >
                <select
                  id={`${formId}-reason`}
                  className="field-input"
                  value={reason}
                  onChange={(e) => setReason(e.target.value)}
                  aria-invalid={!reason}
                >
                  <option value="">Choose a reason</option>
                  {Object.entries(CORRECTION_REASONS).map(([code, label]) => (
                    <option key={code} value={code}>
                      {label}
                    </option>
                  ))}
                </select>
              </Field>
            ) : null}

            {accept.isError ? (
              <FormAlert>{describeError(accept.error)}</FormAlert>
            ) : null}
            {missing.length > 0 ? (
              <p className="text-xs text-stone">
                Still needed: {missing.map((n) => FIELD_LABELS[n]).join(", ")}
              </p>
            ) : null}
          </>
        ) : null}
      </form>

      {editing ? (
        <div className="mt-5 flex flex-wrap items-center gap-2 border-t border-line-faint pt-4">
          {untrusted ? null : (
            <Button
              type="submit"
              form={formId}
              disabled={blocked || accept.isPending}
            >
              {accept.isPending ? <Loader2 className="animate-spin" /> : null}
              Accept and record as pending
            </Button>
          )}
          <Button variant="outline" onClick={() => setRejecting(true)}>
            Reject
          </Button>
          <Button
            variant="ghost"
            onClick={() => defer.mutate()}
            disabled={defer.isPending}
          >
            Return to queue
          </Button>
        </div>
      ) : null}

      <RejectDialog
        open={rejecting}
        onOpenChange={setRejecting}
        messageId={message.id}
        onDone={refresh}
      />
    </Card>
  )
}

function FieldRow({
  name,
  value,
  extracted,
  changed,
  onChange,
}: {
  name: FieldName
  value: string
  extracted?: InboxMessageDetail["fields"][number]
  changed: boolean
  onChange: (value: string) => void
}) {
  const id = useId()
  const vocabulary = VOCABULARY[name]
  const unknownToken =
    vocabulary && value && !(value in vocabulary) ? value : undefined
  return (
    <div className="grid gap-1 sm:grid-cols-[150px_minmax(0,1fr)_auto] sm:items-center sm:gap-3">
      <label htmlFor={id} className="text-[13px] text-stone">
        {FIELD_LABELS[name]}
      </label>
      {vocabulary ? (
        <select
          id={id}
          className="field-input"
          value={value}
          onChange={(e) => onChange(e.target.value)}
          aria-invalid={Boolean(unknownToken)}
        >
          <option value="">Choose</option>
          {unknownToken ? (
            <option value={unknownToken}>
              Read as {unknownToken}: choose a listed value
            </option>
          ) : null}
          {Object.entries(vocabulary).map(([code, label]) => (
            <option key={code} value={code}>
              {label}
            </option>
          ))}
        </select>
      ) : (
        <input
          id={id}
          className={
            DATE_FIELDS.includes(name) ? "field-input font-mono" : "field-input"
          }
          type={DATE_FIELDS.includes(name) ? "date" : "text"}
          value={value}
          onChange={(e) => onChange(e.target.value)}
          autoComplete="off"
          spellCheck={false}
        />
      )}
      <span className="flex items-center gap-1.5">
        {changed ? (
          <Pill tone="clay">Changed</Pill>
        ) : (
          <ConfidenceNote field={extracted} />
        )}
      </span>
    </div>
  )
}

function RejectDialog({
  open,
  onOpenChange,
  messageId,
  onDone,
}: {
  open: boolean
  onOpenChange: (open: boolean) => void
  messageId: string
  onDone: () => Promise<unknown>
}) {
  const [code, setCode] = useState("")
  const id = useId()
  const reject = useMutation({
    mutationFn: () => inboxRepo.reject(messageId, code),
    onSuccess: async () => {
      toast.success("Rejected. Nothing was recorded.")
      onOpenChange(false)
      await onDone()
    },
  })
  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent>
        <DialogHeader>
          <DialogTitle>Reject this letter</DialogTitle>
          <DialogDescription>
            No approval is recorded. The letter stays in the inbox history.
          </DialogDescription>
        </DialogHeader>
        <Field label="Reason" htmlFor={id}>
          <select
            id={id}
            className="field-input"
            value={code}
            onChange={(e) => setCode(e.target.value)}
          >
            <option value="">Choose a reason</option>
            {Object.entries(REJECT_REASONS).map(([value, label]) => (
              <option key={value} value={value}>
                {label}
              </option>
            ))}
          </select>
        </Field>
        {reject.isError ? (
          <FormAlert>{describeError(reject.error)}</FormAlert>
        ) : null}
        <DialogFooter>
          <Button variant="outline" onClick={() => onOpenChange(false)}>
            Cancel
          </Button>
          <Button
            variant="destructive"
            disabled={!code || reject.isPending}
            onClick={() => reject.mutate()}
          >
            {reject.isPending ? <Loader2 className="animate-spin" /> : null}
            Reject
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}

function Decided({ message }: { message: InboxMessageDetail }) {
  if (message.processing_state === "VERIFIED")
    return (
      <Card title="Accepted">
        <p className="text-sm text-stone">
          Recorded as a pending approval
          {message.decided_at
            ? ` on ${formatDayMonthTime(message.decided_at)}`
            : ""}
          {message.decision_reason && message.decision_reason !== "ACCEPTED"
            ? ", with corrections"
            : ""}
          . It authorises nothing until a second clinician verifies it.
        </p>
        <div className="mt-3 flex flex-wrap gap-2">
          <Button asChild size="sm">
            <Link to="/approvals" search={{ filter: "pending" }}>
              Open pending approvals
            </Link>
          </Button>
          {message.patient_id ? (
            <Button asChild size="sm" variant="outline">
              <Link
                to="/patients/$patientId"
                params={{ patientId: message.patient_id }}
              >
                Open patient
              </Link>
            </Button>
          ) : null}
        </div>
      </Card>
    )
  return (
    <Card title="Rejected">
      <p className="text-sm text-stone">
        {message.decision_reason
          ? (REJECT_REASONS[message.decision_reason] ?? message.decision_reason)
          : null}
        {message.decided_at
          ? ` · ${formatDayMonthTime(message.decided_at)}`
          : ""}
      </p>
    </Card>
  )
}

function ReadOnlyFields({ message }: { message: InboxMessageDetail }) {
  const { byName } = useExtracted(message)
  return (
    <Card title="What was read">
      <dl className="grid gap-2 text-sm sm:grid-cols-[150px_minmax(0,1fr)_auto]">
        {FIELD_ORDER.map((name) => (
          <div key={name} className="contents">
            <dt className="text-stone">{FIELD_LABELS[name]}</dt>
            <dd className="font-mono text-ink">{byName[name]?.value ?? "—"}</dd>
            <dd>
              <ConfidenceNote field={byName[name]} />
            </dd>
          </div>
        ))}
      </dl>
    </Card>
  )
}
