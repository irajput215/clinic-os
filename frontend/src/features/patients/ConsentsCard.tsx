import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query"
import { Loader2 } from "lucide-react"
import { useId, useState } from "react"
import { toast } from "sonner"
import type { KindStatus } from "@/client/types.gen"
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
  type ConsentKind,
  consentsRepo,
  patientConsentsQuery,
  STATUS_LABEL,
} from "@/data/consents"
import {
  Card,
  ErrorState,
  Field,
  FormAlert,
  Mono,
  NotForYourRole,
  Pill,
  SkeletonRows,
} from "@/design/primitives"
import { useCanUpdatePatients } from "@/features/patients/RecordParts"
import { formatDayMonthTime } from "@/lib/format"
import { describeError, isForbidden } from "@/lib/http"

/**
 * The patient's consents (docs3 Phase 6 feature 06): each kind's status against the clinic's current
 * text, with recording in clinic and withdrawal. The server decides every status.
 */
export function ConsentsCard({ patientId }: { patientId: string }) {
  const consents = useQuery(patientConsentsQuery(patientId))
  const canUpdate = useCanUpdatePatients()
  const [recording, setRecording] = useState<KindStatus | null>(null)
  const [withdrawing, setWithdrawing] = useState<KindStatus | null>(null)

  if (consents.isError && isForbidden(consents.error)) return <NotForYourRole />

  return (
    <Card title="Consents">
      {consents.isPending ? (
        <SkeletonRows rows={3} />
      ) : consents.isError ? (
        <ErrorState error={consents.error} onRetry={() => consents.refetch()} />
      ) : (
        <ul className="divide-y divide-line-faint">
          {consents.data.kinds.map((k) => {
            const status = STATUS_LABEL[k.status]
            return (
              <li
                key={k.kind}
                className="grid gap-1.5 py-3 first:pt-0 last:pb-0"
              >
                <div className="flex flex-wrap items-center gap-2">
                  <span className="font-medium text-ink">{k.title}</span>
                  <Pill tone={status.tone}>{status.label}</Pill>
                  {canUpdate ? (
                    <span className="ml-auto flex gap-1.5">
                      {k.status !== "CURRENT" ? (
                        <Button
                          size="sm"
                          variant="outline"
                          onClick={() => setRecording(k)}
                        >
                          Record consent
                        </Button>
                      ) : null}
                      {k.status === "CURRENT" ||
                      k.status === "NEEDS_RECONSENT" ? (
                        <Button
                          size="sm"
                          variant="ghost"
                          onClick={() => setWithdrawing(k)}
                        >
                          Withdraw
                        </Button>
                      ) : null}
                    </span>
                  ) : null}
                </div>
                <p className="text-xs text-stone">
                  {k.signed_at ? (
                    <>
                      Agreed to <Mono>{k.signed_version}</Mono> on{" "}
                      {formatDayMonthTime(k.signed_at)}
                      {k.status === "NEEDS_RECONSENT" ? (
                        <>
                          {" "}
                          · current is <Mono>{k.current_version}</Mono>
                        </>
                      ) : null}
                    </>
                  ) : (
                    "Never given."
                  )}
                  {k.withdrawn_at ? (
                    <> · withdrawn {formatDayMonthTime(k.withdrawn_at)}</>
                  ) : null}
                </p>
                {k.status === "WITHDRAWN" || k.status === "NOT_GIVEN" ? (
                  <p className="text-xs text-warn-deep">{k.stops}</p>
                ) : null}
              </li>
            )
          })}
        </ul>
      )}
      {recording ? (
        <RecordDialog
          patientId={patientId}
          kind={recording}
          onClose={() => setRecording(null)}
        />
      ) : null}
      {withdrawing ? (
        <WithdrawDialog
          patientId={patientId}
          kind={withdrawing}
          onClose={() => setWithdrawing(null)}
        />
      ) : null}
    </Card>
  )
}

function useRefresh(patientId: string) {
  const queryClient = useQueryClient()
  return () =>
    queryClient.invalidateQueries({
      queryKey: ["patients", "detail", patientId, "consents"],
    })
}

function RecordDialog({
  patientId,
  kind,
  onClose,
}: {
  patientId: string
  kind: KindStatus
  onClose: () => void
}) {
  const refresh = useRefresh(patientId)
  const record = useMutation({
    mutationFn: () =>
      consentsRepo.record(
        patientId,
        kind.kind as ConsentKind,
        kind.current_version,
      ),
    onSuccess: async () => {
      await refresh()
      toast.success(`${kind.title} recorded`)
      onClose()
    },
  })
  return (
    <Dialog open onOpenChange={(open) => (open ? null : onClose())}>
      <DialogContent className="sm:max-w-[620px]">
        <DialogHeader>
          <DialogTitle>{kind.title}</DialogTitle>
          <DialogDescription>
            Show or read the patient this text. Record their consent only once
            they have agreed to it. Version <Mono>{kind.current_version}</Mono>.
          </DialogDescription>
        </DialogHeader>
        <blockquote className="max-h-[45vh] overflow-y-auto whitespace-pre-wrap rounded-inner border border-line bg-oat px-4 py-3 text-sm leading-relaxed text-ink">
          {kind.current_body}
        </blockquote>
        {record.isError ? (
          <FormAlert>{describeError(record.error)}</FormAlert>
        ) : null}
        <DialogFooter>
          <Button variant="outline" onClick={onClose}>
            Cancel
          </Button>
          <Button disabled={record.isPending} onClick={() => record.mutate()}>
            {record.isPending ? <Loader2 className="animate-spin" /> : null}
            The patient agrees
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}

function WithdrawDialog({
  patientId,
  kind,
  onClose,
}: {
  patientId: string
  kind: KindStatus
  onClose: () => void
}) {
  const refresh = useRefresh(patientId)
  const id = useId()
  const [method, setMethod] = useState<"" | "IN_PERSON" | "PHONE" | "WRITTEN">(
    "",
  )
  const withdraw = useMutation({
    mutationFn: () =>
      consentsRepo.withdraw(
        patientId,
        kind.kind as ConsentKind,
        method as "IN_PERSON",
      ),
    onSuccess: async () => {
      await refresh()
      toast.success(`${kind.title} withdrawn`)
      onClose()
    },
  })
  return (
    <Dialog open onOpenChange={(open) => (open ? null : onClose())}>
      <DialogContent>
        <DialogHeader>
          <DialogTitle>Withdraw: {kind.title}</DialogTitle>
          <DialogDescription>Effective now. {kind.stops}</DialogDescription>
        </DialogHeader>
        <Field label="How did the patient withdraw it?" htmlFor={id}>
          <select
            id={id}
            className="field-input"
            value={method}
            onChange={(e) => setMethod(e.target.value as typeof method)}
          >
            <option value="">Choose</option>
            <option value="IN_PERSON">In person</option>
            <option value="PHONE">By phone</option>
            <option value="WRITTEN">In writing</option>
          </select>
        </Field>
        {withdraw.isError ? (
          <FormAlert>{describeError(withdraw.error)}</FormAlert>
        ) : null}
        <DialogFooter>
          <Button variant="outline" onClick={onClose}>
            Cancel
          </Button>
          <Button
            variant="destructive"
            disabled={!method || withdraw.isPending}
            onClick={() => withdraw.mutate()}
          >
            {withdraw.isPending ? <Loader2 className="animate-spin" /> : null}
            Withdraw
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}
