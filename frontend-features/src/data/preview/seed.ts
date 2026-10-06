import type { PatientRead, UserPublic } from "@/client/types.gen"
import type {
  Appointment,
  AppointmentStatus,
  AppointmentType,
  ClinicalRecordSummary,
  Practitioner,
  Product,
  Script,
  TgaApproval,
} from "@/data/types"
import { APPOINTMENT_TYPES } from "@/data/types"
import { addDays, clinicToday } from "@/lib/format"
import { displayName } from "@/lib/session"
import { previewMatch } from "./gate"
import { clinicInstant, plusMinutes } from "./time"

export interface PreviewState {
  version: 2
  seededFor: string
  seededOn: string
  me: string
  practitioners: Practitioner[]
  products: Product[]
  appointments: Appointment[]
  scripts: Script[]
  approvals: TgaApproval[]
  records: ClinicalRecordSummary[]
}

/** A UUID v4, from the platform's CSPRNG. */
export const uuid = () => crypto.randomUUID()

export const PRODUCTS: Product[] = [
  {
    id: "prd-calmleaf-cbd-100",
    name: "Calmleaf CBD 100",
    tga_category: "CATEGORY_1",
    dosage_form: "ORAL_LIQUID",
    pack: "30 mL",
    schedule: "S4",
  },
  {
    id: "prd-meridian-balance",
    name: "Meridian Balance 10:10 Oil",
    tga_category: "CATEGORY_3",
    dosage_form: "ORAL_LIQUID",
    pack: "30 mL",
    schedule: "S8",
  },
  {
    id: "prd-meridian-night",
    name: "Meridian Night 5:20 Oil",
    tga_category: "CATEGORY_4",
    dosage_form: "ORAL_LIQUID",
    pack: "30 mL",
    schedule: "S8",
  },
  {
    id: "prd-solace-t22",
    name: "Solace T22 Flower",
    tga_category: "CATEGORY_5",
    dosage_form: "DRIED_FLOWER",
    pack: "10 g",
    schedule: "S8",
  },
  {
    id: "prd-solace-t25",
    name: "Solace T25 Flower",
    tga_category: "CATEGORY_5",
    dosage_form: "DRIED_FLOWER",
    pack: "10 g",
    schedule: "S8",
  },
  {
    id: "prd-aurora-caps",
    name: "Aurora 10 Capsules",
    tga_category: "CATEGORY_3",
    dosage_form: "CAPSULE",
    pack: "60 caps",
    schedule: "S8",
  },
]

const PHARMACIES = [
  "Leaf & Stone Pharmacy",
  "Terra Dispensary Chemist",
  "GreenLeaf Compounding",
]

/** An eScript-like token, `EVQ` + 17 base32 characters, from the CSPRNG. */
export const escriptToken = () => {
  const alphabet = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"
  const bytes = crypto.getRandomValues(new Uint8Array(17))
  return `EVQ${Array.from(bytes, (b) => alphabet[b % alphabet.length]).join("")}`
}

/**
 * Seed a believable clinic around the tenant's REAL patients, so every preview record links to a
 * patient the API actually returns. With no patients, nothing patient-linked is seeded.
 */
export const seedPreview = (
  me: UserPublic,
  patients: PatientRead[],
): PreviewState => {
  const today = clinicToday()
  const now = new Date().toISOString()
  const myName = displayName(me)

  const practitioners: Practitioner[] = [
    { id: me.id, name: myName, role: "DOCTOR", title: "Practice Principal" },
    {
      id: "prac-whitfield",
      name: "Dr James Whitfield",
      role: "DOCTOR",
      title: "Contractor GP",
    },
    {
      id: "prac-nair",
      name: "Dr Priya Nair",
      role: "DOCTOR",
      title: "Contractor GP",
    },
    {
      id: "prac-dunn",
      name: "Claire Dunn, RN",
      role: "NURSE",
      title: "Triage Nurse",
    },
    {
      id: "prac-yates",
      name: "Ben Yates, RN",
      role: "NURSE",
      title: "Triage Nurse",
    },
  ]
  const nurse = practitioners[3]

  const state: PreviewState = {
    version: 2,
    seededFor: me.id,
    seededOn: today,
    me: me.id,
    practitioners,
    products: PRODUCTS,
    appointments: [],
    scripts: [],
    approvals: [],
    records: [],
  }
  if (patients.length === 0) return state

  const pick = (i: number) => patients[i % patients.length]
  const nameOf = (p: PatientRead) =>
    `${p.preferred_name || p.given_name} ${p.family_name}`
  const product = (id: string) => PRODUCTS.find((p) => p.id === id)!

  // ---- Approvals: one per interesting gate outcome --------------------------------------------
  const approval = (
    patient: PatientRead,
    productId: string,
    from: number,
    to: number,
    state: TgaApproval["state"],
    ref: string,
    createdBy: string,
  ): TgaApproval => {
    const prd = product(productId)
    return {
      id: uuid(),
      tenant_id: me.tenant_id ?? "",
      patient_id: patient.id,
      tga_category: prd.tga_category,
      dosage_form: prd.dosage_form,
      approval_reference: ref,
      valid_from: addDays(today, from),
      valid_to: addDays(today, to),
      state,
      source: "MANUAL_ENTRY",
      created_by: createdBy,
      verified_by: state === "ACTIVE" ? me.id : null,
      verified_at: state === "ACTIVE" ? now : null,
      revoked_by: null,
      revoked_at: null,
      revoked_reason_code: null,
      superseded_by_id: null,
      supersedes_id: null,
      created_at: plusMinutes(now, -60 * 24 * Math.abs(from)),
      updated_at: now,
    }
  }
  state.approvals = [
    approval(
      pick(0),
      "prd-solace-t25",
      -351,
      15,
      "ACTIVE",
      "SAS-B 2026-114592",
      nurse.id,
    ),
    approval(
      pick(0),
      "prd-meridian-balance",
      -120,
      610,
      "ACTIVE",
      "SAS-B 2026-114601",
      nurse.id,
    ),
    approval(
      pick(1),
      "prd-calmleaf-cbd-100",
      -200,
      160,
      "ACTIVE",
      "SAS-B 2026-104374",
      nurse.id,
    ),
    approval(
      pick(2),
      "prd-meridian-balance",
      -364,
      1,
      "ACTIVE",
      "SAS-B 2025-098834",
      nurse.id,
    ),
    approval(
      pick(3),
      "prd-solace-t22",
      -2,
      700,
      "PENDING",
      "SAS-B 2026-121907",
      nurse.id,
    ),
    approval(
      pick(5),
      "prd-meridian-night",
      -500,
      -30,
      "EXPIRED",
      "SAS-B 2024-077120",
      nurse.id,
    ),
  ]

  // ---- Scripts awaiting review, one of which the gate will refuse -----------------------------
  const draft = (
    patient: PatientRead,
    productId: string,
    qty: string,
    repeats: number,
    directions: string,
    triage: string | null,
    conventional: string | null,
    minutesAgo: number,
    drafter = nurse,
  ): Script => {
    const prd = product(productId)
    const s: Script = {
      id: uuid(),
      patient_id: patient.id,
      patient_name: nameOf(patient),
      product_id: prd.id,
      product_name: prd.name,
      tga_category: prd.tga_category,
      dosage_form: prd.dosage_form,
      quantity: qty,
      repeats,
      directions,
      triage_outcome: triage,
      conventional_therapy: conventional,
      state: "AWAITING_REVIEW",
      drafted_by: drafter.id,
      drafted_by_name: drafter.name,
      prescriber_id: me.id,
      prescriber_name: myName,
      date_of_service: today,
      created_at: plusMinutes(now, -minutesAgo),
      signed_at: null,
      sent_at: null,
      escript_token: null,
      pharmacy: null,
      gate: null,
    }
    s.gate = previewMatch(state.approvals, s)
    return s
  }
  state.scripts = [
    draft(
      pick(0),
      "prd-solace-t25",
      "10 g",
      2,
      "Vaporise 0.1 g as needed, max 1 g/day",
      "Existing patient - renewal",
      "Documented at intake",
      45,
    ),
    draft(
      pick(1),
      "prd-calmleaf-cbd-100",
      "30 mL",
      2,
      "0.5 mL nocte, titrate weekly",
      "Eligible - anxiety, conventional therapy failed",
      "SSRIs 9 months, CBT 12 sessions",
      130,
    ),
    draft(
      pick(2),
      "prd-meridian-balance",
      "30 mL",
      3,
      "0.4 mL BD",
      "Existing patient - renewal",
      "Documented at intake (2025)",
      260,
    ),
    draft(
      pick(4),
      "prd-solace-t22",
      "10 g",
      0,
      "Vaporise 0.1 g as needed",
      "Eligible - chronic pain, conventional therapy failed",
      "Paracetamol/NSAIDs 12 months, physiotherapy",
      380,
    ),
    draft(
      pick(3),
      "prd-solace-t22",
      "10 g",
      1,
      "Vaporise 0.1 g nocte",
      "Eligible - insomnia",
      "Sleep hygiene, melatonin 6 months",
      610,
    ),
  ]

  // ---- A few already sent, for the recent-activity table --------------------------------------
  const sent = (
    patient: PatientRead,
    productId: string,
    daysAgo: number,
    pharmacy: number,
  ): Script => {
    const s = draft(
      patient,
      productId,
      product(productId).pack,
      2,
      "As directed",
      null,
      null,
      daysAgo * 1440,
      practitioners[0],
    )
    return {
      ...s,
      state: "SENT",
      date_of_service: addDays(today, -daysAgo),
      signed_at: plusMinutes(now, -daysAgo * 1440 + 30),
      sent_at: plusMinutes(now, -daysAgo * 1440 + 31),
      escript_token: escriptToken(),
      pharmacy: PHARMACIES[pharmacy % PHARMACIES.length],
    }
  }
  state.scripts.push(
    sent(pick(0), "prd-meridian-balance", 2, 0),
    sent(pick(1), "prd-calmleaf-cbd-100", 6, 1),
    sent(pick(0), "prd-solace-t25", 12, 0),
    sent(pick(2), "prd-meridian-balance", 20, 2),
  )

  // ---- Today's appointments and the rest of the fortnight -------------------------------------
  const nowMinutes = (() => {
    const t = new Intl.DateTimeFormat("en-GB", {
      timeZone: "Australia/Sydney",
      hour: "2-digit",
      minute: "2-digit",
      hour12: false,
    }).format(new Date())
    const [h, m] = t.split(":").map(Number)
    return h * 60 + m
  })()
  const booking = (
    patient: PatientRead,
    practitioner: Practitioner,
    date: string,
    hhmm: string,
    type: AppointmentType,
  ): Appointment => {
    const starts = clinicInstant(date, hhmm)
    const [h, m] = hhmm.split(":").map(Number)
    let status: AppointmentStatus = "CONFIRMED"
    if (date < today) status = "COMPLETED"
    else if (date === today) {
      const start = h * 60 + m
      status =
        start + 30 < nowMinutes
          ? "COMPLETED"
          : start <= nowMinutes
            ? "ARRIVED"
            : "CONFIRMED"
    } else status = "BOOKED"
    return {
      id: uuid(),
      patient_id: patient.id,
      patient_name: nameOf(patient),
      practitioner_id: practitioner.id,
      type,
      status,
      starts_at: starts,
      ends_at: plusMinutes(starts, APPOINTMENT_TYPES[type].minutes),
      source: "STAFF",
      created_at: now,
    }
  }
  const [okafor, whitfield, nair, dunn, yates] = practitioners
  const plan: Array<[number, Practitioner, string, AppointmentType]> = [
    [0, dunn, "09:00", "NURSE_TRIAGE"],
    [1, okafor, "09:45", "FOLLOW_UP"],
    [2, whitfield, "10:15", "FOLLOW_UP"],
    [0, okafor, "11:30", "INITIAL_CONSULT"],
    [3, whitfield, "14:00", "FOLLOW_UP"],
    [4, nair, "15:30", "FOLLOW_UP"],
    [5, yates, "16:00", "NURSE_TRIAGE"],
  ]
  for (const [i, prac, hhmm, type] of plan)
    state.appointments.push(booking(pick(i), prac, today, hhmm, type))
  for (let d = 1; d <= 12; d++) {
    const date = addDays(today, d)
    const weekday = new Date(`${date}T12:00:00Z`).getUTCDay()
    if (weekday === 0 || weekday === 6) continue
    state.appointments.push(
      booking(pick(d), okafor, date, "09:30", "FOLLOW_UP"),
      booking(pick(d + 2), whitfield, date, "11:00", "INITIAL_CONSULT"),
      booking(pick(d + 3), dunn, date, "13:15", "NURSE_TRIAGE"),
    )
  }

  // ---- A signed consult note for the first two patients ---------------------------------------
  for (const [i, body] of [
    [
      0,
      "S: Chronic lumbar pain, 7/10 most days. Sleep improved on current regimen.\nO: Alert, mobile, no sedation. BP 124/78.\nA: Stable on Category 5 flower; approval renewal due within the month.\nP: Continue current dose. Lodge SAS-B renewal. Review in 4 weeks.",
    ],
    [
      1,
      "S: Generalised anxiety, partial response to SSRIs over 9 months.\nO: Calm, engaged. GAD-7 13.\nA: Eligible for Category 1 CBD trial.\nP: Calmleaf CBD 100, 0.5 mL nocte, titrate weekly. Review in 2 weeks.",
    ],
  ] as const) {
    const patient = pick(i)
    const id = uuid()
    const created = plusMinutes(now, -1440 * (i + 3))
    state.records.push({
      id,
      patient_id: patient.id,
      record_type: "NOTE",
      author_id: me.id,
      current_version: 1,
      signed_at: created,
      deleted_at: null,
      created_at: created,
      latest_version: {
        id: uuid(),
        clinical_record_id: id,
        version: 1,
        body,
        body_format: "PLAIN",
        author_id: me.id,
        signed_at: created,
        supersedes_version: null,
        amendment_reason: null,
        created_at: created,
      },
    })
  }

  return state
}
