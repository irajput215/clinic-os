import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query"
import { ArrowDown, ArrowUp, Loader2, Plus, Trash2 } from "lucide-react"
import { useId, useState } from "react"
import { toast } from "sonner"
import type {
  ClinicFormField,
  ClinicFormRead,
  ClinicFormWrite,
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
  clinicFormsQuery,
  clinicFormsRepo,
  FIELD_TYPE_LABELS,
} from "@/data/forms"
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
import { formatDayMonthTime } from "@/lib/format"
import { describeError } from "@/lib/http"

/**
 * Settings > Forms (docs3 Phase 6 feature 05, R6; `tenant:configure`): the clinic's own forms. A
 * published version never changes: editing publishes the next one, and old responses keep showing the
 * version they were answered on. Clinic forms are not scored and raise no safety flags.
 */
export function FormsTab() {
  const forms = useQuery(clinicFormsQuery(true))
  const queryClient = useQueryClient()
  const [editing, setEditing] = useState<ClinicFormRead | "new" | null>(null)
  const retire = useMutation({
    mutationFn: (id: string) => clinicFormsRepo.retire(id),
    onSuccess: async () => {
      await queryClient.invalidateQueries({ queryKey: ["forms", "clinic"] })
      toast.success("Form retired. Its responses stay on patients' records.")
    },
    onError: (error) => toast.error(describeError(error)),
  })
  return (
    <div className="space-y-3.5">
      <div className="flex justify-end">
        <Button onClick={() => setEditing("new")}>
          <Plus /> New form
        </Button>
      </div>
      {forms.isPending ? (
        <SkeletonRows rows={3} />
      ) : forms.isError ? (
        <ErrorState error={forms.error} onRetry={() => forms.refetch()} />
      ) : forms.data.length === 0 ? (
        <Card>
          <EmptyState
            title="No clinic forms yet."
            body="Build a form your staff fill in with patients, such as a follow-up check-in."
          />
        </Card>
      ) : (
        forms.data.map((form) => (
          <Card
            key={form.id}
            title={form.title}
            action={
              form.status === "ACTIVE" ? (
                <span className="flex gap-1.5">
                  <Button
                    size="sm"
                    variant="outline"
                    onClick={() => setEditing(form)}
                  >
                    Edit
                  </Button>
                  <Button
                    size="sm"
                    variant="ghost"
                    disabled={retire.isPending}
                    onClick={() => retire.mutate(form.id)}
                  >
                    Retire
                  </Button>
                </span>
              ) : (
                <Pill tone="neutral">Retired</Pill>
              )
            }
          >
            <p className="mb-2 text-sm text-stone">
              Version <Mono>{form.version}</Mono> · published{" "}
              {formatDayMonthTime(form.published_at)}
              {form.description ? <> · {form.description}</> : null}
            </p>
            <ol className="grid gap-1 text-sm">
              {form.fields.map((f, i) => (
                <li key={f.id} className="flex flex-wrap gap-2">
                  <span className="font-mono text-stone">{i + 1}.</span>
                  <span className="text-ink">{f.label}</span>
                  <span className="text-stone">
                    · {FIELD_TYPE_LABELS[f.type]}
                  </span>
                  {f.required ? <Pill tone="info">Required</Pill> : null}
                </li>
              ))}
            </ol>
          </Card>
        ))
      )}
      {editing ? (
        <BuilderDialog
          form={editing === "new" ? null : editing}
          onClose={() => setEditing(null)}
        />
      ) : null}
    </div>
  )
}

type Draft = ClinicFormField & { optionsText: string }

const slug = (label: string, taken: Set<string>) => {
  const base =
    label
      .toLowerCase()
      .replace(/[^a-z0-9]+/g, "_")
      .replace(/^_+|_+$/g, "")
      .replace(/^[^a-z]+/, "")
      .slice(0, 28) || "field"
  let id = base
  let n = 2
  while (taken.has(id)) id = `${base}_${n++}`
  return id
}

const toDraft = (f: ClinicFormField): Draft => ({
  ...f,
  optionsText: (f.options ?? []).join("\n"),
})

function BuilderDialog({
  form,
  onClose,
}: {
  form: ClinicFormRead | null
  onClose: () => void
}) {
  const queryClient = useQueryClient()
  const id = useId()
  const [title, setTitle] = useState(form?.title ?? "")
  const [description, setDescription] = useState(form?.description ?? "")
  const [fields, setFields] = useState<Draft[]>(
    form ? form.fields.map(toDraft) : [],
  )

  const update = (index: number, patch: Partial<Draft>) =>
    setFields((all) =>
      all.map((f, i) => (i === index ? { ...f, ...patch } : f)),
    )
  const move = (index: number, by: number) =>
    setFields((all) => {
      const next = [...all]
      const [item] = next.splice(index, 1)
      next.splice(index + by, 0, item)
      return next
    })
  const add = () =>
    setFields((all) => [
      ...all,
      {
        id: slug("question", new Set(all.map((f) => f.id))),
        label: "",
        type: "TEXT",
        required: false,
        optionsText: "",
      },
    ])

  const body = (): ClinicFormWrite => ({
    title: title.trim(),
    description: description.trim() || null,
    fields: fields.map(({ optionsText, ...f }) => ({
      id: f.id,
      label: f.label.trim(),
      type: f.type,
      required: f.required ?? false,
      help: null,
      options:
        f.type === "CHOICE"
          ? optionsText
              .split("\n")
              .map((o) => o.trim())
              .filter(Boolean)
          : [],
      scale_min: f.type === "SCALE" ? (f.scale_min ?? 0) : null,
      scale_max: f.type === "SCALE" ? (f.scale_max ?? 10) : null,
    })),
  })

  const save = useMutation({
    mutationFn: () =>
      form
        ? clinicFormsRepo.publishVersion(form.id, body())
        : clinicFormsRepo.create(body()),
    onSuccess: async (saved) => {
      await queryClient.invalidateQueries({ queryKey: ["forms", "clinic"] })
      toast.success(`Published version ${saved.version} of “${saved.title}”`)
      onClose()
    },
  })
  const incomplete =
    title.trim().length < 3 ||
    fields.length === 0 ||
    fields.some((f) => !f.label.trim())

  return (
    <Dialog open onOpenChange={(open) => (open ? null : onClose())}>
      <DialogContent className="max-h-[90vh] overflow-y-auto sm:max-w-[760px]">
        <DialogHeader>
          <DialogTitle>
            {form ? `Edit “${form.title}”` : "New form"}
          </DialogTitle>
          <DialogDescription>
            {form
              ? `Saving publishes version ${form.version + 1}. Answers already given keep version ${form.version}.`
              : "Publishing makes the form available to staff on every patient's Questionnaires tab."}
          </DialogDescription>
        </DialogHeader>
        <div className="grid gap-3 sm:grid-cols-2">
          <Field label="Title" htmlFor={`${id}-title`}>
            <input
              id={`${id}-title`}
              className="field-input"
              maxLength={120}
              value={title}
              onChange={(e) => setTitle(e.target.value)}
            />
          </Field>
          <Field label="Description (optional)" htmlFor={`${id}-desc`}>
            <input
              id={`${id}-desc`}
              className="field-input"
              maxLength={500}
              value={description}
              onChange={(e) => setDescription(e.target.value)}
            />
          </Field>
        </div>
        <ol className="grid gap-3">
          {fields.map((f, index) => (
            <li
              key={f.id}
              className="grid gap-2 rounded-inner border border-line p-3"
            >
              <div className="grid gap-2 sm:grid-cols-[minmax(0,1fr)_170px_auto]">
                <Field
                  label={`Question ${index + 1}`}
                  htmlFor={`${id}-${f.id}-label`}
                >
                  <input
                    id={`${id}-${f.id}-label`}
                    className="field-input"
                    maxLength={200}
                    value={f.label}
                    onChange={(e) => update(index, { label: e.target.value })}
                  />
                </Field>
                <Field label="Type" htmlFor={`${id}-${f.id}-type`}>
                  <select
                    id={`${id}-${f.id}-type`}
                    className="field-input"
                    value={f.type}
                    onChange={(e) =>
                      update(index, { type: e.target.value as Draft["type"] })
                    }
                  >
                    {Object.entries(FIELD_TYPE_LABELS).map(([value, label]) => (
                      <option key={value} value={value}>
                        {label}
                      </option>
                    ))}
                  </select>
                </Field>
                <div className="flex items-end gap-1">
                  <Button
                    size="sm"
                    variant="ghost"
                    aria-label="Move up"
                    disabled={index === 0}
                    onClick={() => move(index, -1)}
                  >
                    <ArrowUp />
                  </Button>
                  <Button
                    size="sm"
                    variant="ghost"
                    aria-label="Move down"
                    disabled={index === fields.length - 1}
                    onClick={() => move(index, 1)}
                  >
                    <ArrowDown />
                  </Button>
                  <Button
                    size="sm"
                    variant="ghost"
                    aria-label="Remove question"
                    onClick={() =>
                      setFields((all) => all.filter((_, i) => i !== index))
                    }
                  >
                    <Trash2 />
                  </Button>
                </div>
              </div>
              {f.type === "CHOICE" ? (
                <Field
                  label="Options, one per line"
                  htmlFor={`${id}-${f.id}-options`}
                >
                  <textarea
                    id={`${id}-${f.id}-options`}
                    className="field-input min-h-[72px]"
                    value={f.optionsText}
                    onChange={(e) =>
                      update(index, { optionsText: e.target.value })
                    }
                  />
                </Field>
              ) : null}
              {f.type === "SCALE" ? (
                <div className="grid grid-cols-2 gap-2 sm:w-[260px]">
                  <Field label="From" htmlFor={`${id}-${f.id}-min`}>
                    <input
                      id={`${id}-${f.id}-min`}
                      type="number"
                      min={0}
                      max={9}
                      className="field-input"
                      value={f.scale_min ?? 0}
                      onChange={(e) =>
                        update(index, { scale_min: Number(e.target.value) })
                      }
                    />
                  </Field>
                  <Field label="To" htmlFor={`${id}-${f.id}-max`}>
                    <input
                      id={`${id}-${f.id}-max`}
                      type="number"
                      min={1}
                      max={10}
                      className="field-input"
                      value={f.scale_max ?? 10}
                      onChange={(e) =>
                        update(index, { scale_max: Number(e.target.value) })
                      }
                    />
                  </Field>
                </div>
              ) : null}
              <label className="flex items-center gap-2 text-sm">
                <input
                  type="checkbox"
                  checked={f.required ?? false}
                  onChange={(e) =>
                    update(index, { required: e.target.checked })
                  }
                />
                Required
              </label>
            </li>
          ))}
        </ol>
        <Button variant="outline" onClick={add} disabled={fields.length >= 50}>
          <Plus /> Add a question
        </Button>
        {save.isError ? (
          <FormAlert>{describeError(save.error)}</FormAlert>
        ) : null}
        <DialogFooter>
          <Button variant="outline" onClick={onClose}>
            Cancel
          </Button>
          <Button
            disabled={incomplete || save.isPending}
            onClick={() => save.mutate()}
          >
            {save.isPending ? <Loader2 className="animate-spin" /> : null}
            Publish
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}
