import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query"
import { Loader2 } from "lucide-react"
import { useId, useState } from "react"
import { toast } from "sonner"
import type { ConsentKindLibrary } from "@/client/types.gen"
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
  consentLibraryQuery,
  consentsRepo,
} from "@/data/consents"
import {
  Card,
  ErrorState,
  Field,
  FormAlert,
  Mono,
  Pill,
  SkeletonRows,
} from "@/design/primitives"
import { formatDayMonthTime } from "@/lib/format"
import { describeError } from "@/lib/http"

/**
 * Settings > Consents (docs3 Phase 6 feature 06, `tenant:configure`): each consent's current text,
 * the clinic's published versions, and how many patients agreed to an older text. Publishing a new
 * version never changes a patient's record: they show "re-consent needed" until they agree again.
 */
export function ConsentsTab() {
  const library = useQuery(consentLibraryQuery)
  const [editing, setEditing] = useState<ConsentKindLibrary | null>(null)
  if (library.isPending) return <SkeletonRows rows={4} />
  if (library.isError)
    return (
      <ErrorState error={library.error} onRetry={() => library.refetch()} />
    )
  return (
    <div className="space-y-3.5">
      {library.data.kinds.map((k) => (
        <Card
          key={k.kind}
          title={k.current.title}
          action={
            <Button size="sm" variant="outline" onClick={() => setEditing(k)}>
              Publish new version
            </Button>
          }
        >
          <div className="mb-2 flex flex-wrap items-center gap-2 text-sm">
            <Pill tone={k.current.source === "CLINIC" ? "clay" : "neutral"}>
              {k.current.source === "CLINIC"
                ? "Your clinic's wording"
                : "Platform default"}
            </Pill>
            <Mono className="text-stone">{k.current.version}</Mono>
            {k.current.published_at ? (
              <span className="text-stone">
                published {formatDayMonthTime(k.current.published_at)}
              </span>
            ) : null}
            {k.patients_needing_reconsent > 0 ? (
              <Pill tone="warn">
                {k.patients_needing_reconsent} patient
                {k.patients_needing_reconsent === 1 ? "" : "s"} to re-consent
              </Pill>
            ) : null}
          </div>
          <p className="whitespace-pre-wrap text-sm leading-relaxed text-ink">
            {k.current.body}
          </p>
          {k.clinic_versions.length > 1 ? (
            <p className="mt-2 text-xs text-stone">
              Earlier versions:{" "}
              {k.clinic_versions
                .slice(1)
                .map((v) => v.version)
                .join(", ")}
            </p>
          ) : null}
        </Card>
      ))}
      {editing ? (
        <PublishDialog kind={editing} onClose={() => setEditing(null)} />
      ) : null}
    </div>
  )
}

function PublishDialog({
  kind,
  onClose,
}: {
  kind: ConsentKindLibrary
  onClose: () => void
}) {
  const queryClient = useQueryClient()
  const id = useId()
  const [title, setTitle] = useState(kind.current.title)
  const [body, setBody] = useState(kind.current.body)
  const unchanged =
    title.trim() === kind.current.title && body.trim() === kind.current.body
  const publish = useMutation({
    mutationFn: () =>
      consentsRepo.publish(kind.kind as ConsentKind, title.trim(), body.trim()),
    onSuccess: async (published) => {
      await queryClient.invalidateQueries({ queryKey: ["consents"] })
      await queryClient.invalidateQueries({ queryKey: ["patients"] })
      toast.success(
        `Published ${published.version}. Patients on the old text will need to re-consent.`,
      )
      onClose()
    },
  })
  return (
    <Dialog open onOpenChange={(open) => (open ? null : onClose())}>
      <DialogContent className="sm:max-w-[680px]">
        <DialogHeader>
          <DialogTitle>Publish a new version</DialogTitle>
          <DialogDescription>
            A published version can't be edited. Every patient who agreed to an
            earlier text will show "re-consent needed" until they agree to this
            one.
          </DialogDescription>
        </DialogHeader>
        <Field label="Title" htmlFor={`${id}-title`}>
          <input
            id={`${id}-title`}
            className="field-input"
            value={title}
            maxLength={200}
            onChange={(e) => setTitle(e.target.value)}
          />
        </Field>
        <Field
          label="Text the patient agrees to"
          htmlFor={`${id}-body`}
          hint={`${body.length} / 10000`}
        >
          <textarea
            id={`${id}-body`}
            className="field-input min-h-[220px] resize-y leading-relaxed"
            value={body}
            maxLength={10_000}
            onChange={(e) => setBody(e.target.value)}
          />
        </Field>
        {publish.isError ? (
          <FormAlert>{describeError(publish.error)}</FormAlert>
        ) : null}
        <DialogFooter>
          <Button variant="outline" onClick={onClose}>
            Cancel
          </Button>
          <Button
            disabled={
              unchanged ||
              body.trim().length < 20 ||
              title.trim().length < 3 ||
              publish.isPending
            }
            onClick={() => publish.mutate()}
          >
            {publish.isPending ? <Loader2 className="animate-spin" /> : null}
            Publish
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}
