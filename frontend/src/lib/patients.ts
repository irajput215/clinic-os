/**
 * Patient vocabulary and display helpers, shared by the list, the detail view and the form.
 *
 * The vocabulary mirrors `backend/app/modules/patients/models.py`
 * (`SEX_AT_BIRTH_VOCABULARY`) so the select, the schema and the API cannot drift: the
 * label is for display, the value is what is sent. Nothing here reads or writes an
 * identifier — this slice of the API exposes none.
 */

import type { PatientRead } from "@/client"

export const SEX_AT_BIRTH_VALUES = [
  "FEMALE",
  "MALE",
  "INTERSEX",
  "UNKNOWN",
] as const

export type SexAtBirth = (typeof SEX_AT_BIRTH_VALUES)[number]

export const SEX_AT_BIRTH_OPTIONS: ReadonlyArray<{
  value: SexAtBirth
  label: string
}> = [
  { value: "FEMALE", label: "Female" },
  { value: "MALE", label: "Male" },
  { value: "INTERSEX", label: "Intersex" },
  { value: "UNKNOWN", label: "Unknown" },
]

/** Shown wherever a field the API returns as `null` has no value to display. */
export const EMPTY_VALUE = "—"

export const displayOrEmpty = (value: string | null | undefined): string =>
  value && value.trim() !== "" ? value : EMPTY_VALUE

export const sexAtBirthLabel = (value: string | null | undefined): string => {
  const option = SEX_AT_BIRTH_OPTIONS.find((item) => item.value === value)
  return option ? option.label : displayOrEmpty(value)
}

/** "Given Family" — the patient's name as a page heading. */
export const patientFullName = (
  patient: Pick<PatientRead, "given_name" | "family_name">,
): string => `${patient.given_name} ${patient.family_name}`

/** "Family, Given" — the name as a table row, which is the usual clinical ordering. */
export const patientListName = (
  patient: Pick<PatientRead, "given_name" | "family_name">,
): string => `${patient.family_name}, ${patient.given_name}`
