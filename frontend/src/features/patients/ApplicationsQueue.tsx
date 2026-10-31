import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query"
import { useNavigate } from "@tanstack/react-router"
import { Loader2 } from "lucide-react"
import { useEffect, useId, useState } from "react"
import { toast } from "sonner"
import type { ApplicationCard } from "@/client/types.gen"
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
  acceptApplication,
  applicationQuery,
  applicationsQuery,
  CANNABIS_DURATIONS,
  CANNABIS_FORMS,
  CONDITIONS,
  FLAG_LABELS,
  REJECT_REASONS,
  rejectApplication,
} from "@/data/intake"
import {
  Card,
  EmptyState,
  ErrorState,
  Field,
  FormAlert,
  Mono,
  Pill,
  SkeletonRows,
} from "@/design/primitives"
import { age, formatDate, formatDayMonthTime } from "@/lib/format"
import { describeError } from "@/lib/http"

/**
 * Patients > Online applications (manual §5.4): the queue, oldest first, each card with its flags.
 * Opening one shows the answers; Accept files the consents, declaration and pharmacy onto the record,
 * Reject cancels the held booking. The server decides who may do either.
 */
export function ApplicationsQueue() {
  const queue = useQuery(applicationsQuery("SUBMITTED"))
  const [openId, setOpenId] = useState<string | null>(null)
  return (
    <Card bodyClassName="-mx-5 -my-[18px]">
      {queue.isPending ? (
        <div className="p-5">
          <SkeletonRows rows={3} />
        </div>
      ) : queue.isError ? (
        <div className="p-5">
          <ErrorState error={queue.error} onRetry={() => queue.refetch()} />
        </div>
      ) : queue.data.length === 0 ? (
        <EmptyState
          title="No new applications."
          body="Applications from your public booking page appear here for review."
        />
      ) : (
        <ul className="divide-y divide-line-faint">
          {queue.data.map((a) => (
            <li key={a.id}>
              <button
                type="button"
                className="flex w-full flex-wrap items-center gap-x-3 gap-y-1.5 px-5 py-3.5 text-left hover:bg-oat/50 max-lg:min-h-11"
                onClick={() => setOpenId(a.id)}
                aria-label={`Review application from ${a.patient_name}`}
              >
                <span className="font-semibold">{a.patient_name}</span>
                <span className="text-sm text-stone">
                  {formatDate(a.date_of_birth)} · {age(a.date_of_birth)}
                </span>
                {a.matched_existing ? (
                  <Pill tone="info">Existing patient</Pill>
                ) : null}
                <Flags flags={a.flags} />
                <span className="ml-auto text-xs text-stone">
                  Applied {formatDayMonthTime(a.created_at)}
                  {a.appointment_starts_at
                    ? ` · booked ${formatDayMonthTime(a.appointment_starts_at)}`
                    : ""}
                </span>
              </button>
            </li>
          ))}
        </ul>
      )}
      <ApplicationDialog
        card={queue.data?.find((a) => a.id === openId) ?? null}
        onOpenChange={(o) => !o && setOpenId(null)}
      />
    </Card>
  )
}

export function Flags({ flags }: { flags: string[] }) {
  return (
    <>
      {flags.map((f) => (
        <Pill
          key={f}
          tone={
            f === "CANNABIS_NAIVE" || f === "NO_CONVENTIONAL_THERAPY"
              ? "neutral"
              : "warn"
          }
        >
          {FLAG_LABELS[f] ?? f}
        </Pill>
      ))}
    </>
  )
}

const yes = (v: unknown) => (v ? "Yes" : "No")

function ApplicationDialog({
  card,
  onOpenChange,
}: {
  card: ApplicationCard | null
  onOpenChange: (open: boolean) => void
}) {
  const queryClient = useQueryClient()
  const navigate = useNavigate()
  const detail = useQuery({
    ...applicationQuery(card?.id ?? ""),
    enabled: card !== null,
  })
  const [rejecting, setRejecting] = useState(false)
  const [reason, setReason] =
    useState<keyof typeof REJECT_REASONS>("NOT_ELIGIBLE")
  const [note, setNote] = useState("")
  const reasonId = useId()
  const noteId = useId()
  useEffect(() => {
    if (card) {
      setRejecting(false)
      setNote("")
    }
  }, [card])
  const settle = async () => {
    await queryClient.invalidateQueries({ queryKey: ["intake"] })
    await queryClient.invalidateQueries({ queryKey: ["patients"] })
  }
  const accept = useMutation({
    mutationFn: () => acceptApplication(card!.id),
    onSuccess: async (r) => {
      await settle()
      toast.success("Application accepted")
      onOpenChange(false)
      navigate({
        to: "/patients/$patientId",
        params: { patientId: r.patient_id },
      })
    },
  })
  const reject = useMutation({
    mutationFn: () =>
      rejectApplication(card!.id, {
        reason_code: reason,
        note: note.trim() || null,
      }),
    onSuccess: async () => {
      await settle()
      toast.success("Application rejected; the booking was cancelled")
      onOpenChange(false)
    },
  })
  const a = (detail.data?.answers ?? {}) as Record<string, unknown>
  const safety = (a.safety ?? {}) as Record<string, boolean>
  const row = (label: string, value: React.ReactNode) => (
    <div className="contents">
      <dt className="text-stone">{label}</dt>
      <dd className="min-w-0 break-words">
        {value || <span className="text-stone-faint">-</span>}
      </dd>
    </div>
  )
  const pharmacy = detail.data?.pharmacy as
    | Record<string, string>
    | null
    | undefined
  return (
    <Dialog open={card !== null} onOpenChange={onOpenChange}>
      <DialogContent className="sm:max-w-[640px]">
        <DialogHeader>
          <DialogTitle>{card?.patient_name ?? "Application"}</DialogTitle>
          <DialogDescription>
            Online application. Answers are the patient's own, for the doctor.
          </DialogDescription>
        </DialogHeader>
        {detail.isPending ? (
          <SkeletonRows rows={6} />
        ) : detail.isError ? (
          <ErrorState error={detail.error} />
        ) : (
          <div className="grid max-h-[60vh] gap-4 overflow-y-auto pr-1 text-sm">
            <div className="flex flex-wrap gap-1.5">
              <Flags flags={detail.data.flags} />
            </div>
            <dl className="grid grid-cols-[150px_minmax(0,1fr)] gap-y-2">
              {row(
                "Condition",
                CONDITIONS[a.primary_condition as keyof typeof CONDITIONS],
              )}
              {row(
                "Other conditions",
                ((a.other_conditions as string[]) ?? []).join(", "),
              )}
              {row("Current medicines", a.current_medicines as string)}
              {row("Psychosis history", yes(safety.psychosis_history))}
              {row(
                "Pregnant / breastfeeding",
                yes(safety.pregnant_or_breastfeeding),
              )}
              {row("Heart condition", yes(safety.heart_condition))}
              {row("Substance dependence", yes(safety.substance_dependence))}
              {row(
                "Standard treatment",
                a.tried_conventional
                  ? (a.conventional_detail as string) || "Yes"
                  : "Not tried",
              )}
              {row(
                "Cannabis before",
                a.cannabis_used_before
                  ? [
                      ((a.cannabis_forms as string[]) ?? [])
                        .map(
                          (f) =>
                            CANNABIS_FORMS[f as keyof typeof CANNABIS_FORMS] ??
                            f,
                        )
                        .join(", "),
                      CANNABIS_DURATIONS[
                        a.cannabis_duration as keyof typeof CANNABIS_DURATIONS
                      ],
                    ]
                      .filter(Boolean)
                      .join(" · ") || "Yes"
                  : "Never",
              )}
              {row("Side effects", a.side_effects as string)}
              {row("What helped", a.what_helped as string)}
              {row(
                "Address",
                [a.address_line, a.suburb, a.state, a.postcode]
                  .filter(Boolean)
                  .join(", "),
              )}
              {row(
                "Pharmacy",
                pharmacy
                  ? `${pharmacy.name}, ${pharmacy.suburb}${pharmacy.kind === "OWN" ? " (patient's own)" : ""}`
                  : null,
              )}
              {row(
                "Consents",
                detail.data.consents
                  .map((c) => `${c.kind.toLowerCase()} v${c.version}`)
                  .join(" · "),
              )}
              {row(
                "Declaration",
                <span>
                  {detail.data.declaration_name}{" "}
                  <Mono className="text-stone">
                    {formatDayMonthTime(detail.data.declared_at)}
                  </Mono>
                </span>,
              )}
            </dl>
            {rejecting ? (
              <div className="grid gap-3 rounded-inner border border-line bg-oat/40 p-3.5">
                <Field label="Reason" htmlFor={reasonId}>
                  <select
                    id={reasonId}
                    className="field-input"
                    value={reason}
                    onChange={(e) =>
                      setReason(e.target.value as keyof typeof REJECT_REASONS)
                    }
                  >
                    {Object.entries(REJECT_REASONS).map(([k, label]) => (
                      <option key={k} value={k}>
                        {label}
                      </option>
                    ))}
                  </select>
                </Field>
                <Field
                  label="Note"
                  htmlFor={noteId}
                  hint="Optional, for the clinic only"
                >
                  <input
                    id={noteId}
                    className="field-input"
                    maxLength={500}
                    value={note}
                    onChange={(e) => setNote(e.target.value)}
                  />
                </Field>
              </div>
            ) : null}
          </div>
        )}
        {accept.isError || reject.isError ? (
          <FormAlert>{describeError(accept.error ?? reject.error)}</FormAlert>
        ) : null}
        <DialogFooter>
          {rejecting ? (
            <>
              <Button variant="outline" onClick={() => setRejecting(false)}>
                Back
              </Button>
              <Button
                variant="destructive"
                disabled={reject.isPending}
                onClick={() => reject.mutate()}
              >
                {reject.isPending ? <Loader2 className="animate-spin" /> : null}
                Reject and cancel booking
              </Button>
            </>
          ) : (
            <>
              <Button
                variant="outline"
                disabled={!detail.isSuccess}
                onClick={() => setRejecting(true)}
              >
                Reject
              </Button>
              <Button
                disabled={!detail.isSuccess || accept.isPending}
                onClick={() => accept.mutate()}
              >
                {accept.isPending ? <Loader2 className="animate-spin" /> : null}
                Accept
              </Button>
            </>
          )}
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}
