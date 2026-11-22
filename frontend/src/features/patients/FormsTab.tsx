import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query"
import { AlertTriangle, ClipboardList, Loader2 } from "lucide-react"
import { useId, useState } from "react"
import { toast } from "sonner"
import type {
  ClinicFormRead,
  ClinicFormResponseRead,
  FormResponseRead,
  InstrumentRead,
  SafetyFlagRead,
} from "@/client/types.gen"
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
  type AnswerValue,
  bandTone,
  clinicFormsQuery,
  clinicFormsRepo,
  formatAnswer,
  formsRepo,
  INSTRUMENT_SHORT,
  instrumentsQuery,
  patientFormsQuery,
} from "@/data/forms"
import {
  Card,
  EmptyState,
  ErrorState,
  Field,
  FormAlert,
  Mono,
  NotForYourRole,
  Pill,
  SkeletonRows,
} from "@/design/primitives"
import { formatDayMonthTime } from "@/lib/format"
import { describeError, isForbidden } from "@/lib/http"
import { cn } from "@/lib/utils"

/**
 * Questionnaires on the patient record (docs3 Phase 6 feature 05): open safety flags first, then
 * record PHQ-9, GAD-7 or K10, then the history with scores over time. The server scores, bands and
 * raises flags; a band is a label for the clinician, never a diagnosis.
 */
export function FormsTab({ patientId }: { patientId: string }) {
  const forms = useQuery(patientFormsQuery(patientId))
  const catalogue = useQuery(instrumentsQuery)
  const clinicForms = useQuery({ ...clinicFormsQuery(false), retry: false })
  const [recording, setRecording] = useState<InstrumentRead | null>(null)
  const [filling, setFilling] = useState<ClinicFormRead | null>(null)

  if (forms.isError && isForbidden(forms.error)) return <NotForYourRole />

  return (
    <div className="space-y-3.5">
      {forms.data && forms.data.open_flags.length > 0 ? (
        <OpenFlags
          patientId={patientId}
          flags={forms.data.open_flags}
          actions={catalogue.data?.acknowledge_actions ?? []}
        />
      ) : null}

      <Card title="Record a questionnaire">
        <div className="flex flex-wrap gap-2">
          {(catalogue.data?.instruments ?? []).map((instrument) => (
            <Button
              key={instrument.code}
              variant="outline"
              onClick={() => setRecording(instrument)}
            >
              <ClipboardList /> {INSTRUMENT_SHORT[instrument.code]}
            </Button>
          ))}
          {(clinicForms.data ?? []).map((form) => (
            <Button
              key={form.id}
              variant="outline"
              onClick={() => setFilling(form)}
            >
              <ClipboardList /> {form.title}
            </Button>
          ))}
        </div>
        <p className="mt-2.5 text-xs text-stone">
          Entered by staff with the patient, in clinic or on a call. PHQ-9,
          GAD-7 and K10 are scored by their published rules; the clinic's own
          forms are not scored.
        </p>
      </Card>

      <Card title="History">
        {forms.isPending ? (
          <SkeletonRows rows={3} />
        ) : forms.isError ? (
          <ErrorState error={forms.error} onRetry={() => forms.refetch()} />
        ) : forms.data.responses.length === 0 ? (
          <EmptyState title="No questionnaires recorded yet." />
        ) : (
          <History responses={forms.data.responses} />
        )}
      </Card>

      {forms.data?.clinic_responses?.length ? (
        <Card title="Clinic forms">
          <ClinicHistory responses={forms.data.clinic_responses} />
        </Card>
      ) : null}

      {filling ? (
        <ClinicFormDialog
          patientId={patientId}
          form={filling}
          onClose={() => setFilling(null)}
        />
      ) : null}

      {recording ? (
        <RecordDialog
          patientId={patientId}
          instrument={recording}
          onClose={() => setRecording(null)}
        />
      ) : null}
    </div>
  )
}

function OpenFlags({
  patientId,
  flags,
  actions,
}: {
  patientId: string
  flags: SafetyFlagRead[]
  actions: { code: string; label: string }[]
}) {
  const queryClient = useQueryClient()
  const id = useId()
  const [choice, setChoice] = useState<Record<string, string>>({})
  const acknowledge = useMutation({
    mutationFn: (flag: SafetyFlagRead) =>
      formsRepo.acknowledge(flag.id, choice[flag.id] ?? ""),
    onSuccess: async () => {
      await queryClient.invalidateQueries({
        queryKey: ["forms", "patient", patientId],
      })
      toast.success("Safety flag acknowledged")
    },
    onError: (error) => toast.error(describeError(error)),
  })
  return (
    <section
      aria-label="Open safety flags"
      className="rounded-card border border-danger bg-danger-tint px-5 py-4"
    >
      <h2 className="mb-2 flex items-center gap-2 text-base font-semibold text-danger-deep">
        <AlertTriangle className="size-4" aria-hidden /> Safety flag needs a
        response
      </h2>
      <ul className="grid gap-3">
        {flags.map((flag) => (
          <li key={flag.id} className="grid gap-2">
            <p className="text-sm text-ink">
              {flag.description}{" "}
              <span className="text-stone">
                Raised {formatDayMonthTime(flag.raised_at)}.
              </span>
            </p>
            <div className="flex flex-wrap items-end gap-2">
              <Field
                label="What was done"
                htmlFor={`${id}-${flag.id}`}
                className="min-w-[260px] flex-1"
              >
                <select
                  id={`${id}-${flag.id}`}
                  className="field-input"
                  value={choice[flag.id] ?? ""}
                  onChange={(e) =>
                    setChoice((s) => ({ ...s, [flag.id]: e.target.value }))
                  }
                >
                  <option value="">Choose an action</option>
                  {actions.map((a) => (
                    <option key={a.code} value={a.code}>
                      {a.label}
                    </option>
                  ))}
                </select>
              </Field>
              <Button
                disabled={!choice[flag.id] || acknowledge.isPending}
                onClick={() => acknowledge.mutate(flag)}
              >
                {acknowledge.isPending ? (
                  <Loader2 className="animate-spin" />
                ) : null}
                Acknowledge
              </Button>
            </div>
          </li>
        ))}
      </ul>
    </section>
  )
}

function History({ responses }: { responses: FormResponseRead[] }) {
  const trend = (code: string) =>
    responses
      .filter((r) => r.instrument === code && !r.corrected_by_id)
      .slice(0, 6)
      .reverse()
      .map((r) => r.total_score)
  const codes = [...new Set(responses.map((r) => r.instrument))]
  return (
    <div className="grid gap-4">
      <div className="flex flex-wrap gap-3 text-sm">
        {codes.map((code) => (
          <span
            key={code}
            className="rounded-inner border border-line px-3 py-1.5"
          >
            <span className="font-medium text-ink">
              {INSTRUMENT_SHORT[code]}
            </span>{" "}
            <Mono className="text-stone">{trend(code).join(" → ")}</Mono>
          </span>
        ))}
      </div>
      <div className="relative overflow-x-auto">
        <table className="data-table">
          <thead>
            <tr>
              <th className="pl-5">Recorded</th>
              <th>Questionnaire</th>
              <th>Score</th>
              <th className="pr-5">Band</th>
            </tr>
          </thead>
          <tbody>
            {responses.map((r) => (
              <tr key={r.id} className={cn(r.corrected_by_id && "opacity-60")}>
                <td className="pl-5">
                  <Mono>{formatDayMonthTime(r.created_at)}</Mono>
                </td>
                <td>
                  {INSTRUMENT_SHORT[r.instrument]}
                  {r.corrected_by_id ? (
                    <span className="ml-2 text-xs text-stone">corrected</span>
                  ) : null}
                </td>
                <td>
                  <Mono>{r.total_score}</Mono>
                </td>
                <td className="pr-5">
                  <span className="inline-flex flex-wrap gap-1.5">
                    <Pill tone={bandTone(r.band)}>{r.band_label}</Pill>
                    {r.flags.map((f) => (
                      <Pill
                        key={f.id}
                        tone={f.status === "OPEN" ? "danger" : "neutral"}
                        title={f.description}
                      >
                        {f.status === "OPEN"
                          ? "Safety flag"
                          : "Flag acknowledged"}
                      </Pill>
                    ))}
                  </span>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  )
}

function RecordDialog({
  patientId,
  instrument,
  onClose,
}: {
  patientId: string
  instrument: InstrumentRead
  onClose: () => void
}) {
  const queryClient = useQueryClient()
  const id = useId()
  const [answers, setAnswers] = useState<(number | null)[]>(
    instrument.items.map(() => null),
  )
  const [difficulty, setDifficulty] = useState<number | null>(null)
  const complete = answers.every((a) => a !== null)
  const running = answers.reduce<number>((sum, a) => sum + (a ?? 0), 0)
  const band = complete
    ? instrument.bands.find((b) => b.low <= running && running <= b.high)
    : undefined

  const record = useMutation({
    mutationFn: () =>
      formsRepo.record(patientId, {
        instrument: instrument.code,
        instrument_version: instrument.version,
        answers: answers as number[],
        difficulty,
      }),
    onSuccess: async (saved) => {
      await queryClient.invalidateQueries({
        queryKey: ["forms", "patient", patientId],
      })
      if (saved.flags.length > 0)
        toast.error(
          "Saved. A safety flag was raised: respond to it now, at the top of this tab.",
          { duration: 15_000 },
        )
      else
        toast.success(
          `Saved: ${INSTRUMENT_SHORT[saved.instrument]} ${saved.total_score} (${saved.band_label})`,
        )
      onClose()
    },
  })

  return (
    <Dialog open onOpenChange={(open) => (open ? null : onClose())}>
      <DialogContent className="max-h-[90vh] overflow-y-auto sm:max-w-[720px]">
        <DialogHeader>
          <DialogTitle>{instrument.title}</DialogTitle>
          <DialogDescription>{instrument.stem}</DialogDescription>
        </DialogHeader>
        <ol className="grid gap-4">
          {instrument.items.map((item, index) => (
            <li key={item}>
              <fieldset>
                <legend className="mb-1.5 text-sm text-ink">
                  <span className="mr-1.5 font-mono text-stone">
                    {index + 1}.
                  </span>
                  {item}
                </legend>
                <div className="flex flex-wrap gap-1.5">
                  {instrument.options.map((option) => (
                    <label
                      key={option.value}
                      className="cursor-pointer rounded-full border border-line px-3 py-1.5 text-[13px] has-[:checked]:border-clay has-[:checked]:bg-clay-tint has-[:focus-visible]:ring-2 has-[:focus-visible]:ring-clay"
                    >
                      <input
                        type="radio"
                        className="sr-only"
                        name={`${id}-${index}`}
                        checked={answers[index] === option.value}
                        onChange={() =>
                          setAnswers((s) =>
                            s.map((a, i) => (i === index ? option.value : a)),
                          )
                        }
                      />
                      {option.label}
                    </label>
                  ))}
                </div>
              </fieldset>
            </li>
          ))}
        </ol>
        {instrument.difficulty_question ? (
          <Field
            label="Difficulty (not scored)"
            htmlFor={`${id}-difficulty`}
            hint={instrument.difficulty_question}
          >
            <select
              id={`${id}-difficulty`}
              className="field-input"
              value={difficulty ?? ""}
              onChange={(e) =>
                setDifficulty(
                  e.target.value === "" ? null : Number(e.target.value),
                )
              }
            >
              <option value="">Not asked</option>
              {instrument.difficulty_options.map((label, value) => (
                <option key={label} value={value}>
                  {label}
                </option>
              ))}
            </select>
          </Field>
        ) : null}
        {record.isError ? (
          <FormAlert>{describeError(record.error)}</FormAlert>
        ) : null}
        <DialogFooter className="items-center gap-3 sm:justify-between">
          <p className="text-sm text-stone" aria-live="polite">
            Score <Mono className="text-ink">{running}</Mono> of{" "}
            {instrument.max_score}
            {band ? <> · {band.label}</> : <> · answer every question</>}
          </p>
          <div className="flex gap-2">
            <Button variant="outline" onClick={onClose}>
              Cancel
            </Button>
            <Button
              disabled={!complete || record.isPending}
              onClick={() => record.mutate()}
            >
              {record.isPending ? <Loader2 className="animate-spin" /> : null}
              Save
            </Button>
          </div>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}

function ClinicHistory({ responses }: { responses: ClinicFormResponseRead[] }) {
  return (
    <ul className="grid gap-2">
      {responses.map((r) => (
        <li
          key={r.id}
          className={cn(
            "rounded-inner border border-line",
            r.corrected_by_id && "opacity-60",
          )}
        >
          <details>
            <summary className="flex cursor-pointer flex-wrap items-center gap-2 px-3.5 py-2.5 text-sm">
              <span className="font-medium text-ink">{r.title}</span>
              <Mono className="text-stone">v{r.version}</Mono>
              <span className="text-stone">
                {formatDayMonthTime(r.created_at)}
              </span>
              {r.corrected_by_id ? (
                <span className="text-xs text-stone">corrected</span>
              ) : null}
            </summary>
            <dl className="grid gap-x-4 gap-y-1.5 border-t border-line-faint px-3.5 py-3 text-sm sm:grid-cols-[220px_minmax(0,1fr)]">
              {r.fields.map((f) => (
                <div key={f.id} className="contents">
                  <dt className="text-stone">{f.label}</dt>
                  <dd className="whitespace-pre-wrap text-ink">
                    {formatAnswer(r.answers[f.id])}
                  </dd>
                </div>
              ))}
            </dl>
          </details>
        </li>
      ))}
    </ul>
  )
}

function ClinicFormDialog({
  patientId,
  form,
  onClose,
}: {
  patientId: string
  form: ClinicFormRead
  onClose: () => void
}) {
  const queryClient = useQueryClient()
  const id = useId()
  const [answers, setAnswers] = useState<Record<string, AnswerValue>>({})
  const set = (fieldId: string, value: AnswerValue) =>
    setAnswers((a) => ({ ...a, [fieldId]: value }))
  const missing = form.fields.filter(
    (f) =>
      f.required &&
      (answers[f.id] === undefined ||
        answers[f.id] === null ||
        answers[f.id] === ""),
  )
  const save = useMutation({
    mutationFn: () =>
      clinicFormsRepo.respond(patientId, form.version_id, answers),
    onSuccess: async () => {
      await queryClient.invalidateQueries({
        queryKey: ["forms", "patient", patientId],
      })
      toast.success(`Saved: ${form.title}`)
      onClose()
    },
  })
  return (
    <Dialog open onOpenChange={(open) => (open ? null : onClose())}>
      <DialogContent className="max-h-[90vh] overflow-y-auto sm:max-w-[680px]">
        <DialogHeader>
          <DialogTitle>{form.title}</DialogTitle>
          <DialogDescription>
            {form.description ?? "Fill in with the patient."}
          </DialogDescription>
        </DialogHeader>
        <div className="grid gap-4">
          {form.fields.map((f) => {
            const fieldId = `${id}-${f.id}`
            const label = f.required ? `${f.label} *` : f.label
            const value = answers[f.id]
            if (
              f.type === "CHOICE" ||
              f.type === "YES_NO" ||
              f.type === "SCALE"
            ) {
              const options: { label: string; value: AnswerValue }[] =
                f.type === "CHOICE"
                  ? (f.options ?? []).map((o) => ({ label: o, value: o }))
                  : f.type === "YES_NO"
                    ? [
                        { label: "Yes", value: true },
                        { label: "No", value: false },
                      ]
                    : Array.from(
                        {
                          length: (f.scale_max ?? 10) - (f.scale_min ?? 0) + 1,
                        },
                        (_, i) => ({
                          label: String((f.scale_min ?? 0) + i),
                          value: (f.scale_min ?? 0) + i,
                        }),
                      )
              return (
                <fieldset key={f.id}>
                  <legend className="field-label">{label}</legend>
                  <div className="flex flex-wrap gap-1.5">
                    {options.map((o) => (
                      <label
                        key={String(o.value)}
                        className="cursor-pointer rounded-full border border-line px-3 py-1.5 text-[13px] has-[:checked]:border-clay has-[:checked]:bg-clay-tint has-[:focus-visible]:ring-2 has-[:focus-visible]:ring-clay"
                      >
                        <input
                          type="radio"
                          className="sr-only"
                          name={fieldId}
                          checked={value === o.value}
                          onChange={() => set(f.id, o.value)}
                        />
                        {o.label}
                      </label>
                    ))}
                  </div>
                </fieldset>
              )
            }
            return (
              <Field key={f.id} label={label} htmlFor={fieldId}>
                {f.type === "LONG_TEXT" ? (
                  <textarea
                    id={fieldId}
                    className="field-input min-h-[96px] resize-y"
                    maxLength={5000}
                    value={(value as string) ?? ""}
                    onChange={(e) => set(f.id, e.target.value)}
                  />
                ) : (
                  <input
                    id={fieldId}
                    className={
                      f.type === "DATE"
                        ? "field-input font-mono"
                        : "field-input"
                    }
                    type={f.type === "DATE" ? "date" : "text"}
                    maxLength={500}
                    value={(value as string) ?? ""}
                    onChange={(e) => set(f.id, e.target.value)}
                  />
                )}
              </Field>
            )
          })}
        </div>
        {save.isError ? (
          <FormAlert>{describeError(save.error)}</FormAlert>
        ) : null}
        <DialogFooter className="items-center gap-3 sm:justify-between">
          <p className="text-sm text-stone">
            {missing.length > 0
              ? `Still needed: ${missing.map((f) => f.label).join(", ")}`
              : "Ready to save."}
          </p>
          <div className="flex gap-2">
            <Button variant="outline" onClick={onClose}>
              Cancel
            </Button>
            <Button
              disabled={missing.length > 0 || save.isPending}
              onClick={() => save.mutate()}
            >
              {save.isPending ? <Loader2 className="animate-spin" /> : null}
              Save
            </Button>
          </div>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}
