import { queryOptions } from "@tanstack/react-query"
import { AuthService, PrescriptionsService } from "@/client"
import type { PrescriptionCreate, PrescriptionRead } from "@/client/types.gen"
import type { TgaMatchResponse } from "@/data/types"

/**
 * Prescriptions (the script queue), served by backend/app/modules/prescriptions/router.py
 * (docs2/sdlc/07-script-queue/api.md, agreed 2026-10-07):
 *   GET  /prescriptions?state=&prescriber_id=&patient_id=&cursor=   POST /prescriptions
 *   POST /prescriptions/{id}/sign       POST /prescriptions/{id}/dispatch (Idempotency-Key)
 *   GET  /prescriptions/prescribers     POST /auth/step-up (the interim password step-up)
 *
 * The safety gate's answer on every actionable script comes from the server, evaluated now. The
 * server also decides at sign and at dispatch, inside the transaction, so nothing here is a control:
 * the screens only show what the server said.
 *
 * No pharmacy transport exists: a dispatched script is `QUEUED` and the API says
 * `transport_configured: false`. The UI says "queued, not sent", never "sent".
 */

export const PRESCRIPTION_STATES = [
  "DRAFT",
  "SIGNED",
  "BLOCKED",
  "QUEUED",
  "DISPATCHED",
  "FAILED",
  "REQUIRES_RECONCILIATION",
  "CANCELLED",
  "REVERSED",
] as const
export type PrescriptionState = (typeof PRESCRIPTION_STATES)[number]

/** The generated read, with `state` and `gate` narrowed to the values the backend allows. */
export type Prescription = Omit<PrescriptionRead, "state" | "gate"> & {
  state: PrescriptionState
  gate: TgaMatchResponse | null
}

/** States that still need a person: sign a draft, or send a signed/blocked/failed one. */
export const ACTIONABLE: readonly PrescriptionState[] = [
  "DRAFT",
  "SIGNED",
  "BLOCKED",
  "FAILED",
]
export const isActionable = (state: PrescriptionState) =>
  ACTIONABLE.includes(state)

export const PRESCRIPTION_STATE_LABEL: Record<PrescriptionState, string> = {
  DRAFT: "Awaiting review",
  SIGNED: "Signed, not sent",
  BLOCKED: "Blocked by safety gate",
  QUEUED: "Queued, not sent",
  DISPATCHED: "Sent to pharmacy",
  FAILED: "Send failed",
  REQUIRES_RECONCILIATION: "Needs reconciliation",
  CANCELLED: "Cancelled",
  REVERSED: "Reversed",
}

/** The API sends a decimal string ("1.00"); show it as a clinician writes it ("1", "2.5"). */
export const formatQuantity = (quantity: string) => {
  const n = Number(quantity)
  return Number.isFinite(n) ? String(n) : quantity
}

/** The API's largest page (prescriptions/service.py `MAX_PAGE_SIZE`). */
const PAGE_SIZE = 100

const listAll = async (query: {
  patient_id?: string
}): Promise<Prescription[]> => {
  const all: Prescription[] = []
  let cursor: string | undefined
  do {
    const { data: page } = await PrescriptionsService.listPrescriptions({
      query: { limit: PAGE_SIZE, cursor, ...query },
    })
    all.push(...(page.data as Prescription[]))
    cursor = page.next_cursor ?? undefined
  } while (cursor)
  return all
}

/** A fresh single-use step-up grant for one operation on one script (ADR-F002 interim). */
const stepUp = async (
  password: string,
  operation: "prescription.sign" | "prescription.dispatch",
  id: string,
) =>
  (
    await AuthService.stepUp({
      body: { password, operation, resource_id: id },
    })
  ).data.step_up_token

export const scriptsRepo = {
  list: () => listAll({}),
  listForPatient: (patientId: string) => listAll({ patient_id: patientId }),
  prescribers: async () =>
    (await PrescriptionsService.listPrescribers()).data.data,
  stage: async (body: PrescriptionCreate) =>
    (await PrescriptionsService.stagePrescription({ body }))
      .data as Prescription,
  sign: async (id: string, password: string) =>
    (
      await PrescriptionsService.signPrescription({
        path: { prescription_id: id },
        body: {
          step_up_token: await stepUp(password, "prescription.sign", id),
        },
      })
    ).data as Prescription,
  /**
   * `intentKey` is one per send attempt from the dialog: a network retry of the same attempt reuses
   * it and the server answers with the first result instead of queueing twice.
   */
  dispatch: async (id: string, password: string, intentKey: string) =>
    (
      await PrescriptionsService.dispatchPrescription({
        path: { prescription_id: id },
        headers: { "Idempotency-Key": intentKey },
        body: {
          step_up_token: await stepUp(password, "prescription.dispatch", id),
        },
      })
    ).data as Prescription,
}

export const scriptsQuery = queryOptions({
  queryKey: ["scripts"],
  queryFn: scriptsRepo.list,
  staleTime: 10_000,
})

export const patientScriptsQuery = (patientId: string) =>
  queryOptions({
    queryKey: ["scripts", "patient", patientId],
    queryFn: () => scriptsRepo.listForPatient(patientId),
    staleTime: 10_000,
  })

export const prescribersQuery = queryOptions({
  queryKey: ["prescribers"],
  queryFn: scriptsRepo.prescribers,
  staleTime: 5 * 60_000,
})
