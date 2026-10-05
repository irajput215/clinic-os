/**
 * The patient form's contract: its zod schema, its value shape, and the conversions
 * between form values and the API's request bodies.
 *
 * Every field is a `string` here because the form owns the text the user typed; `""` means
 * "no value". The converters are the only place that turns that into the API's
 * `string | null`, which keeps "the field was left empty" and "the field should be
 * cleared" the same thing on the wire.
 *
 * `mode: "onSubmit"` is set on the forms that use this schema, and the `<form>` carries
 * `noValidate`, so zod owns validation and the browser does not intercept submit — the same
 * deliberate choice the auth forms make.
 */

import { z } from "zod"

import type { PatientCreate, PatientRead, PatientUpdate } from "@/client"
import { isValidDateOnly, localToday, toDateOnly } from "@/lib/date"
import { SEX_AT_BIRTH_VALUES } from "@/lib/patients"

// The API's column limits (`backend/app/modules/patients/schemas.py`). Mirrored here so a
// too-long value is a field error rather than a `422` after the request is sent.
const MAX_NAME = 255
const MAX_STATE = 64
const MAX_POSTCODE = 32
const MAX_PHONE = 64

const requiredText = (label: string, max: number) =>
  z
    .string()
    .trim()
    .min(1, { message: `${label} is required` })
    .max(max, { message: `${label} must be ${max} characters or fewer` })

const optionalText = (label: string, max: number) =>
  z
    .string()
    .trim()
    .max(max, { message: `${label} must be ${max} characters or fewer` })

const requiredDate = (label: string) =>
  z
    .string()
    .min(1, { message: `${label} is required` })
    .refine(isValidDateOnly, { message: `${label} must be a valid date` })

const optionalDate = (label: string) =>
  z.string().refine((value) => value === "" || isValidDateOnly(value), {
    message: `${label} must be a valid date`,
  })

const optionalEmail = z
  .string()
  .trim()
  .max(255, { message: "Email must be 255 characters or fewer" })
  .refine((value) => value === "" || z.email().safeParse(value).success, {
    message: "Invalid email address",
  })

export const patientFormSchema = z.object({
  given_name: requiredText("Given name", MAX_NAME),
  family_name: requiredText("Family name", MAX_NAME),
  preferred_name: optionalText("Preferred name", MAX_NAME),
  // A date of birth in the future is a data-entry error, not a clinical record. The API
  // does not reject it; the form does.
  date_of_birth: requiredDate("Date of birth").refine(
    (value) => value <= localToday(),
    { message: "Date of birth cannot be in the future" },
  ),
  sex_at_birth: z.union([z.literal(""), z.enum(SEX_AT_BIRTH_VALUES)]),
  gender_identity: optionalText("Gender identity", MAX_NAME),
  address_line: optionalText("Address", MAX_NAME),
  suburb: optionalText("Suburb", MAX_NAME),
  state: optionalText("State", MAX_STATE),
  postcode: optionalText("Postcode", MAX_POSTCODE),
  phone: optionalText("Phone", MAX_PHONE),
  email: optionalEmail,
  deceased_at: optionalDate("Date of death"),
})

export type PatientFormValues = z.infer<typeof patientFormSchema>

export const emptyPatientFormValues: PatientFormValues = {
  given_name: "",
  family_name: "",
  preferred_name: "",
  date_of_birth: "",
  sex_at_birth: "",
  gender_identity: "",
  address_line: "",
  suburb: "",
  state: "",
  postcode: "",
  phone: "",
  email: "",
  deceased_at: "",
}

export const patientToFormValues = (
  patient: PatientRead,
): PatientFormValues => ({
  given_name: patient.given_name,
  family_name: patient.family_name,
  preferred_name: patient.preferred_name ?? "",
  date_of_birth: toDateOnly(patient.date_of_birth),
  sex_at_birth: (patient.sex_at_birth ??
    "") as PatientFormValues["sex_at_birth"],
  gender_identity: patient.gender_identity ?? "",
  address_line: patient.address_line ?? "",
  suburb: patient.suburb ?? "",
  state: patient.state ?? "",
  postcode: patient.postcode ?? "",
  phone: patient.phone ?? "",
  email: patient.email ?? "",
  deceased_at: toDateOnly(patient.deceased_at),
})

const blankToNull = (value: string): string | null => {
  const trimmed = value.trim()
  return trimmed === "" ? null : trimmed
}

/**
 * `deceased_at` is a `datetime` on the API and a date in the form, so a form value becomes
 * midnight on that day. The API's column carries no time-of-day meaning.
 */
const dateToTimestamp = (value: string): string | null =>
  value === "" ? null : `${value}T00:00:00`

export const formValuesToCreate = (
  values: PatientFormValues,
): PatientCreate => ({
  given_name: values.given_name.trim(),
  family_name: values.family_name.trim(),
  date_of_birth: values.date_of_birth,
  preferred_name: blankToNull(values.preferred_name),
  sex_at_birth: blankToNull(values.sex_at_birth),
  gender_identity: blankToNull(values.gender_identity),
  address_line: blankToNull(values.address_line),
  suburb: blankToNull(values.suburb),
  state: blankToNull(values.state),
  postcode: blankToNull(values.postcode),
  phone: blankToNull(values.phone),
  email: blankToNull(values.email),
  deceased_at: dateToTimestamp(values.deceased_at),
})

/**
 * The changed fields only, or `null` when nothing changed.
 *
 * `PATCH` applies exactly the fields it is given (`exclude_unset` on the server), so
 * sending the whole form back would rewrite fields the user never touched. An unchanged
 * form sends no request at all rather than an empty body — `422` is the useful answer to a
 * body that carries no fields, not something a "Save" button should produce.
 */
export const formValuesToUpdate = (
  values: PatientFormValues,
  patient: PatientRead,
): PatientUpdate | null => {
  const update: PatientUpdate = {}

  const givenName = values.given_name.trim()
  if (givenName !== patient.given_name) update.given_name = givenName

  const familyName = values.family_name.trim()
  if (familyName !== patient.family_name) update.family_name = familyName

  if (values.date_of_birth !== toDateOnly(patient.date_of_birth)) {
    update.date_of_birth = values.date_of_birth
  }

  const optionalFields = [
    "preferred_name",
    "sex_at_birth",
    "gender_identity",
    "address_line",
    "suburb",
    "state",
    "postcode",
    "phone",
    "email",
  ] as const

  for (const field of optionalFields) {
    const next = blankToNull(values[field])
    if (next !== (patient[field] ?? null)) update[field] = next
  }

  if (values.deceased_at !== toDateOnly(patient.deceased_at)) {
    update.deceased_at = dateToTimestamp(values.deceased_at)
  }

  return Object.keys(update).length > 0 ? update : null
}
