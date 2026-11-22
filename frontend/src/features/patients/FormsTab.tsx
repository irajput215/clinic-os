import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query"
import { AlertTriangle, ClipboardList, Loader2 } from "lucide-react"
import { useId, useState } from "react"
import { toast } from "sonner"
import type {
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
  bandTone,
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
  const [recording, setRecording] = useState<InstrumentRead | null>(null)

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
        </div>
        <p className="mt-2.5 text-xs text-stone">
          Entered by staff with the patient, in clinic or on a call. Scores use
          each questionnaire's published rules.
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
