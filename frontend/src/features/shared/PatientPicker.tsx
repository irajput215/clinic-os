import { useQuery } from "@tanstack/react-query"
import { useState } from "react"
import type { PatientRead } from "@/client/types.gen"
import {
  patientName,
  patientQuickFindQuery,
  useSearchTerm,
} from "@/data/patients"
import { Field, Mono } from "@/design/primitives"
import { formatDate, patientRef } from "@/lib/format"
import { describeError } from "@/lib/http"
import { cn } from "@/lib/utils"

/**
 * The patient, found by the server's search (`POST /patients/search`: name, date of birth or PT-
 * reference), so a practice of any size can choose anyone, not only its first page of patients. The
 * term travels in a request body, never a URL. With nothing typed it offers the first few by name.
 * The chosen patient stays shown while the search changes.
 */
export function PatientPicker({
  id,
  value,
  onChange,
  error,
  className,
}: {
  /** The search input's id; the radio group's name is derived from it. */
  id: string
  value: string
  onChange: (id: string) => void
  error?: string
  /** Placement in the parent grid, e.g. `sm:col-span-2`. */
  className?: string
}) {
  const [find, setFind] = useState("")
  const [chosen, setChosen] = useState<PatientRead | null>(null)
  const term = useSearchTerm(find)
  const matches = useQuery(patientQuickFindQuery(term))
  const options = [
    ...(chosen && value === chosen.id ? [chosen] : []),
    ...(matches.data?.data ?? []).filter((p) => p.id !== chosen?.id),
  ]
  return (
    <fieldset className={cn("grid gap-2", className)}>
      <Field label="Patient" htmlFor={id} error={error}>
        <input
          id={id}
          type="search"
          className="field-input"
          autoComplete="off"
          placeholder="Name, date of birth or PT- reference"
          value={find}
          onChange={(e) => setFind(e.target.value)}
        />
      </Field>
      <div
        role="radiogroup"
        aria-label="Matching patients"
        className="grid max-h-48 gap-1 overflow-y-auto rounded-inner border border-line p-1.5"
      >
        {matches.isError ? (
          <p className="px-2 py-1.5 text-[13px] text-danger-deep">
            {describeError(matches.error)}
          </p>
        ) : matches.isPending && options.length === 0 ? (
          <p className="px-2 py-1.5 text-[13px] text-stone">Searching…</p>
        ) : options.length === 0 ? (
          <p className="px-2 py-1.5 text-[13px] text-stone">
            No patient matches that.
          </p>
        ) : (
          options.map((p) => (
            <label
              key={p.id}
              className="flex cursor-pointer items-center gap-2.5 rounded-btn px-2 py-1.5 text-sm hover:bg-oat"
            >
              <input
                type="radio"
                name={`${id}-choice`}
                value={p.id}
                checked={value === p.id}
                onChange={() => {
                  setChosen(p)
                  onChange(p.id)
                }}
              />
              <span className="font-medium">{patientName(p)}</span>
              <span className="text-stone">{formatDate(p.date_of_birth)}</span>
              <Mono className="ml-auto text-[11.5px] text-stone">
                {patientRef(p.id)}
              </Mono>
            </label>
          ))
        )}
      </div>
    </fieldset>
  )
}
