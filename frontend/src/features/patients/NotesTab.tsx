import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query"
import { Loader2, Lock, PenLine } from "lucide-react"
import { useId, useState } from "react"
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
import { parseSoap, patientRecordsQuery, recordsRepo } from "@/data/records"
import type { ClinicalRecordSummary, SoapNote } from "@/data/types"
import {
  Card,
  EmptyState,
  ErrorState,
  Field,
  Pill,
  SkeletonRows,
} from "@/design/primitives"
import { formatDayMonthTime } from "@/lib/format"
import { describeError } from "@/lib/http"
import { currentUserQuery } from "@/lib/session"

const SECTIONS: Array<[keyof SoapNote, string, string]> = [
  [
    "subjective",
    "Subjective",
    "Presenting complaint, history, patient's account",
  ],
  ["objective", "Objective", "Examination, observations, measures"],
  ["assessment", "Assessment", "Clinical impression, eligibility"],
  ["plan", "Plan", "Treatment, product, titration, review"],
]

function SoapEditor({
  value,
  onChange,
}: {
  value: SoapNote
  onChange: (v: SoapNote) => void
}) {
  // Two editors can be on the page at once (the new note and the amend dialog), so ids are unique
  // per instance; otherwise a label in the dialog would point at the textarea behind it.
  const id = useId()
  return (
    <div className="grid gap-3 sm:grid-cols-2">
      {SECTIONS.map(([key, label, hint]) => (
        <Field key={key} label={label} htmlFor={`${id}-${key}`}>
          <textarea
            id={`${id}-${key}`}
            rows={3}
            placeholder={hint}
            className="field-input min-h-[84px] resize-y leading-relaxed"
            value={value[key] ?? ""}
            onChange={(e) => onChange({ ...value, [key]: e.target.value })}
          />
        </Field>
      ))}
    </div>
  )
}

const isEmpty = (s: SoapNote) => !SECTIONS.some(([k]) => s[k]?.trim())

export function NotesTab({ patientId }: { patientId: string }) {
  const queryClient = useQueryClient()
  const records = useQuery(patientRecordsQuery(patientId))
  const { data: me } = useQuery(currentUserQuery)
  const [draft, setDraft] = useState<SoapNote>({})
  const [amending, setAmending] = useState<ClinicalRecordSummary | null>(null)
  const invalidate = () =>
    queryClient.invalidateQueries({
      queryKey: ["records", "patient", patientId],
    })

  const create = useMutation({
    mutationFn: () => recordsRepo.create(patientId, draft),
    onSuccess: async () => {
      setDraft({})
      await invalidate()
      toast.success("Note saved as a draft. Sign it to lock it.")
    },
    onError: (e) => toast.error(describeError(e)),
  })
  const sign = useMutation({
    mutationFn: (id: string) => recordsRepo.sign(id),
    onSuccess: async () => {
      await invalidate()
      toast.success("Note signed. It can no longer be edited, only amended.")
    },
    onError: (e) => toast.error(describeError(e)),
  })

  return (
    <div className="space-y-3.5">
      <Card title="New consult note">
        <SoapEditor value={draft} onChange={setDraft} />
        <div className="mt-3.5 flex items-center justify-between gap-3">
          <p className="text-xs text-stone">
            A saved note is a draft until you sign it. A signed note is
            permanent; corrections are added as amendments with a reason.
          </p>
          <Button
            disabled={isEmpty(draft) || create.isPending}
            onClick={() => create.mutate()}
          >
            {create.isPending ? <Loader2 className="animate-spin" /> : null}
            Save note
          </Button>
        </div>
      </Card>

      <Card title="Consult history">
        {records.isPending ? (
          <SkeletonRows rows={3} />
        ) : records.isError ? (
          <ErrorState error={records.error} onRetry={() => records.refetch()} />
        ) : records.data.length === 0 ? (
          <EmptyState title="No consult notes yet." />
        ) : (
          <ol className="space-y-3">
            {records.data.map((r) => {
              const v = r.latest_version
              return (
                <li
                  key={r.id}
                  className="rounded-inner border border-line bg-paper px-4 py-3.5"
                >
                  <div className="mb-2 flex flex-wrap items-center gap-2 text-[13px]">
                    <span className="font-mono text-stone">
                      {formatDayMonthTime(v.created_at)}
                    </span>
                    {r.signed_at ? (
                      <Pill tone="ok">
                        <Lock className="size-3" /> Signed
                      </Pill>
                    ) : (
                      <Pill tone="warn">Draft</Pill>
                    )}
                    {r.current_version > 1 ? (
                      <Pill tone="purple">Amended · v{r.current_version}</Pill>
                    ) : null}
                    <span className="ml-auto flex gap-1">
                      {!r.signed_at && r.author_id === me?.id ? (
                        <Button
                          size="sm"
                          disabled={sign.isPending}
                          onClick={() => sign.mutate(r.id)}
                        >
                          Sign
                        </Button>
                      ) : null}
                      {r.signed_at ? (
                        <Button
                          size="sm"
                          variant="ghost"
                          onClick={() => setAmending(r)}
                        >
                          <PenLine /> Amend
                        </Button>
                      ) : null}
                    </span>
                  </div>
                  <dl className="grid gap-x-4 gap-y-1.5 text-sm sm:grid-cols-[110px_minmax(0,1fr)]">
                    {parseSoap(v.body).map(([label, text], i) => (
                      <div key={`${label}-${i}`} className="contents">
                        <dt className="text-xs font-semibold tracking-[0.06em] text-stone uppercase sm:pt-0.5">
                          {label}
                        </dt>
                        <dd className="whitespace-pre-line">{text}</dd>
                      </div>
                    ))}
                  </dl>
                  {v.amendment_reason ? (
                    <p className="mt-2 border-line-faint border-t pt-2 text-xs text-stone">
                      Amendment reason: {v.amendment_reason}
                    </p>
                  ) : null}
                </li>
              )
            })}
          </ol>
        )}
      </Card>

      <AmendDialog
        record={amending}
        onOpenChange={(o) => !o && setAmending(null)}
        onDone={invalidate}
      />
    </div>
  )
}

function AmendDialog({
  record,
  onOpenChange,
  onDone,
}: {
  record: ClinicalRecordSummary | null
  onOpenChange: (o: boolean) => void
  onDone: () => Promise<unknown>
}) {
  const [soap, setSoap] = useState<SoapNote>({})
  const [reason, setReason] = useState("")
  const [seededFor, setSeededFor] = useState<string | null>(null)
  if (record && seededFor !== record.id) {
    const fromBody: SoapNote = {}
    for (const [label, text] of parseSoap(record.latest_version.body)) {
      const key = SECTIONS.find(([, l]) => l === label)?.[0]
      if (key) fromBody[key] = text
    }
    setSoap(fromBody)
    setReason("")
    setSeededFor(record.id)
  }
  const amend = useMutation({
    mutationFn: () => recordsRepo.amend(record!.id, soap, reason),
    onSuccess: async () => {
      await onDone()
      toast.success("Amendment added. The original stays on the record.")
      setSeededFor(null)
      onOpenChange(false)
    },
  })
  return (
    <Dialog open={record !== null} onOpenChange={onOpenChange}>
      <DialogContent className="sm:max-w-[680px]">
        <DialogHeader>
          <DialogTitle>Amend signed note</DialogTitle>
          <DialogDescription>
            The signed version is kept unchanged. This adds a new version with
            your reason.
          </DialogDescription>
        </DialogHeader>
        <SoapEditor value={soap} onChange={setSoap} />
        <Field label="Reason for amendment" htmlFor="amend-reason">
          <input
            id="amend-reason"
            className="field-input"
            value={reason}
            onChange={(e) => setReason(e.target.value)}
            placeholder="e.g. Corrected dose in plan"
          />
        </Field>
        {amend.isError ? (
          <p
            role="alert"
            className="rounded-btn bg-danger-tint px-3 py-2.5 text-[13px] text-danger-deep"
          >
            {describeError(amend.error)}
          </p>
        ) : null}
        <DialogFooter>
          <Button variant="outline" onClick={() => onOpenChange(false)}>
            Cancel
          </Button>
          <Button
            disabled={!reason.trim() || isEmpty(soap) || amend.isPending}
            onClick={() => amend.mutate()}
          >
            {amend.isPending ? <Loader2 className="animate-spin" /> : null}
            Add amendment
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}
