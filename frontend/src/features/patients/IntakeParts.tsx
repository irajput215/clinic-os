import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query"
import { Loader2, Plus } from "lucide-react"
import { useId, useState } from "react"
import { toast } from "sonner"
import type { PatientRead } from "@/client/types.gen"
import { Button } from "@/components/ui/button"
import {
  briefingQuery,
  CANNABIS_DURATIONS,
  CANNABIS_FORMS,
  CONDITIONS,
  consentsQuery,
  createPharmacy,
  FLAG_LABELS,
  pharmaciesQuery,
  setPatientPharmacy,
} from "@/data/intake"
import { patientQuery } from "@/data/patients"
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
import { describeError, httpStatus } from "@/lib/http"
import { useCanUpdatePatients } from "./RecordParts"

/**
 * The doctor's intake briefing (manual §5.4): one glance before the first consult, built from the
 * patient's own answers. Shown only to those the server lets read it (`clinical_record:read` under the
 * treating relationship); anyone else, and a patient who never applied online, sees nothing.
 */
export function IntakeBriefingCard({ patientId }: { patientId: string }) {
  const briefing = useQuery({ ...briefingQuery(patientId), retry: false })
  if (briefing.isPending || briefing.isError || briefing.data === null) {
    if (
      briefing.isError &&
      ![403, 404].includes(httpStatus(briefing.error) ?? 0)
    )
      return (
        <Card title="Intake briefing">
          <ErrorState
            error={briefing.error}
            onRetry={() => briefing.refetch()}
          />
        </Card>
      )
    return null
  }
  const b = briefing.data
  const row = (label: string, value: React.ReactNode) => (
    <div className="contents">
      <dt className="text-stone">{label}</dt>
      <dd className="min-w-0 break-words">
        {value || <span className="text-stone-faint">-</span>}
      </dd>
    </div>
  )
  return (
    <Card
      title="Intake briefing"
      action={
        <span className="text-xs text-stone">
          Doctor only · not shown to the patient
        </span>
      }
    >
      {b.safety_flags.length ? (
        <div className="mb-3 flex flex-wrap gap-1.5">
          {b.safety_flags.map((f) => (
            <Pill key={f} tone="warn">
              {FLAG_LABELS[f] ?? f}
            </Pill>
          ))}
        </div>
      ) : null}
      <dl className="grid grid-cols-[130px_minmax(0,1fr)] gap-y-2 text-sm">
        {row(
          "Presenting",
          [
            CONDITIONS[b.primary_condition as keyof typeof CONDITIONS] ??
              b.primary_condition,
            ...b.other_conditions,
          ].join(", "),
        )}
        {row(
          "Tried",
          b.tried_conventional
            ? b.conventional_detail || "Standard treatment"
            : "No standard treatment yet",
        )}
        {row("Medicines", b.current_medicines)}
        {row(
          "Cannabis history",
          b.cannabis_used_before
            ? [
                b.cannabis_forms
                  .map(
                    (f) =>
                      CANNABIS_FORMS[f as keyof typeof CANNABIS_FORMS] ?? f,
                  )
                  .join(", "),
                b.cannabis_duration
                  ? CANNABIS_DURATIONS[
                      b.cannabis_duration as keyof typeof CANNABIS_DURATIONS
                    ]
                  : null,
              ]
                .filter(Boolean)
                .join(" · ")
            : "Never used",
        )}
        {row("Side effects", b.side_effects)}
        {row("What helped", b.what_helped)}
        {row(
          "Pharmacy",
          b.pharmacy
            ? `${String(b.pharmacy.name)}, ${String(b.pharmacy.suburb)}`
            : null,
        )}
        {row(
          "Declaration",
          <span>
            {b.declaration_name}{" "}
            <Mono className="text-stone">
              {formatDayMonthTime(b.declared_at)}
            </Mono>
          </span>,
        )}
      </dl>
    </Card>
  )
}

export function ConsentsCard({ patientId }: { patientId: string }) {
  const consents = useQuery(consentsQuery(patientId))
  return (
    <Card title="Consents">
      {consents.isPending ? (
        <SkeletonRows rows={1} />
      ) : consents.isError ? (
        <ErrorState error={consents.error} onRetry={() => consents.refetch()} />
      ) : consents.data.length === 0 ? (
        <p className="text-sm text-stone">No signed consents on file.</p>
      ) : (
        <ul className="space-y-2 text-sm">
          {consents.data.map((c) => (
            <li
              key={`${c.kind}-${c.signed_at}`}
              className="flex flex-wrap items-baseline gap-2"
            >
              <span className="font-medium">{c.title}</span>
              <Mono className="text-stone">v{c.version}</Mono>
              <span className="text-stone">
                {formatDayMonthTime(c.signed_at)}
              </span>
              {c.current ? null : <Pill tone="warn">Re-consent needed</Pill>}
            </li>
          ))}
        </ul>
      )}
    </Card>
  )
}

export function PharmacyCard({ patient }: { patient: PatientRead }) {
  const pharmacies = useQuery(pharmaciesQuery)
  const canUpdate = useCanUpdatePatients()
  const queryClient = useQueryClient()
  const [choosing, setChoosing] = useState(false)
  const [choice, setChoice] = useState("")
  const [adding, setAdding] = useState(false)
  const [name, setName] = useState("")
  const [suburb, setSuburb] = useState("")
  const [email, setEmail] = useState("")
  const ids = {
    select: useId(),
    name: useId(),
    suburb: useId(),
    email: useId(),
  }
  const current = pharmacies.data?.find(
    (p) => p.id === patient.preferred_pharmacy_id,
  )
  const save = useMutation({
    mutationFn: async () => {
      let id = choice || null
      if (adding) {
        const created = await createPharmacy({
          name: name.trim(),
          suburb: suburb.trim(),
          email: email.trim() || null,
        })
        await queryClient.invalidateQueries({
          queryKey: pharmaciesQuery.queryKey,
        })
        id = created.id
      }
      return setPatientPharmacy(patient.id, id)
    },
    onSuccess: (saved) => {
      queryClient.setQueryData(patientQuery(saved.id).queryKey, saved)
      setChoosing(false)
      setAdding(false)
      toast.success("Pharmacy changed")
    },
  })
  return (
    <Card
      title="Pharmacy"
      action={
        canUpdate && !choosing ? (
          <Button
            size="sm"
            variant="outline"
            onClick={() => {
              setChoice(patient.preferred_pharmacy_id ?? "")
              setChoosing(true)
            }}
          >
            Change pharmacy
          </Button>
        ) : undefined
      }
    >
      {!choosing ? (
        current ? (
          <p className="text-sm">
            <span className="font-medium">{current.name}</span>{" "}
            <span className="text-stone">· {current.suburb}</span>
            {current.email ? null : (
              <span className="mt-1 block text-xs text-warn-deep">
                No email on file: scripts to this pharmacy need a manual
                handoff.
              </span>
            )}
          </p>
        ) : (
          <p className="text-sm text-stone">No pharmacy chosen yet.</p>
        )
      ) : (
        <form
          noValidate
          className="grid gap-3"
          onSubmit={(e) => {
            e.preventDefault()
            save.mutate()
          }}
        >
          {!adding ? (
            <Field label="Pharmacy" htmlFor={ids.select}>
              <select
                id={ids.select}
                className="field-input"
                value={choice}
                onChange={(e) => setChoice(e.target.value)}
              >
                <option value="">None</option>
                {(pharmacies.data ?? []).map((p) => (
                  <option key={p.id} value={p.id}>
                    {p.name} · {p.suburb}
                  </option>
                ))}
              </select>
            </Field>
          ) : (
            <div className="grid gap-3 sm:grid-cols-3">
              <Field label="Name" htmlFor={ids.name}>
                <input
                  id={ids.name}
                  className="field-input"
                  value={name}
                  onChange={(e) => setName(e.target.value)}
                />
              </Field>
              <Field label="Suburb" htmlFor={ids.suburb}>
                <input
                  id={ids.suburb}
                  className="field-input"
                  value={suburb}
                  onChange={(e) => setSuburb(e.target.value)}
                />
              </Field>
              <Field
                label="Email"
                htmlFor={ids.email}
                hint="Powers the handoff"
              >
                <input
                  id={ids.email}
                  type="email"
                  className="field-input"
                  value={email}
                  onChange={(e) => setEmail(e.target.value)}
                />
              </Field>
            </div>
          )}
          {save.isError ? (
            <FormAlert>{describeError(save.error)}</FormAlert>
          ) : null}
          <div className="flex flex-wrap justify-end gap-2">
            {!adding ? (
              <Button
                type="button"
                variant="ghost"
                onClick={() => setAdding(true)}
              >
                <Plus /> Add pharmacy
              </Button>
            ) : null}
            <Button
              type="button"
              variant="outline"
              onClick={() => {
                setChoosing(false)
                setAdding(false)
              }}
            >
              Cancel
            </Button>
            <Button
              type="submit"
              disabled={
                save.isPending || (adding && !(name.trim() && suburb.trim()))
              }
            >
              {save.isPending ? <Loader2 className="animate-spin" /> : null}
              Save
            </Button>
          </div>
        </form>
      )}
    </Card>
  )
}
