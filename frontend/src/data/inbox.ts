import { queryOptions } from "@tanstack/react-query"
import { TgaInboxService } from "@/client"
import type {
  AcceptRequest,
  DecisionResult,
  InboxMessageDetail,
  InboxQueue,
  PatientTgaLetter,
} from "@/client/types.gen"

/**
 * The TGA inbox review queue, served by backend/app/modules/tga_inbox/router.py:
 *   GET  /tga-inbox/messages            GET  /tga-inbox/messages/{id}
 *   GET  /tga-inbox/attachments/{id}/content (the PDF, only while clean and hash-verified)
 *   POST /tga-inbox/messages/{id}/claim | accept | reject | defer
 * Every route needs `tga_inbox:process`; the server decides, this layer only asks.
 *
 * Accepting never activates an approval: it creates a `PENDING` one that a second clinician verifies
 * on the approvals register (D-011 §2).
 */

/** The permission that opens the inbox. Hiding the entry is a courtesy; the API refuses without it. */
export const PROCESS_INBOX = "tga_inbox:process"

export const QUEUE_FILTERS = {
  open: { label: "To review", state: undefined },
  VERIFIED: { label: "Accepted", state: "VERIFIED" },
  REJECTED: { label: "Rejected", state: "REJECTED" },
} as const
export type QueueFilter = keyof typeof QUEUE_FILTERS
export const QUEUE_FILTER_KEYS = Object.keys(QUEUE_FILTERS) as QueueFilter[]

export type FieldName = InboxMessageDetail["fields"][number]["field_name"]

/** Display order and labels. The five mandatory fields form the approval itself. */
export const FIELD_LABELS: Record<FieldName, string> = {
  APPROVAL_REFERENCE: "Approval number",
  TGA_CATEGORY: "TGA category",
  DOSAGE_FORM: "Dosage form",
  VALID_FROM: "Valid from",
  VALID_TO: "Valid to (as printed)",
  PATIENT_NAME: "Patient name",
  PATIENT_DOB: "Date of birth",
  PATIENT_IHI: "IHI",
  PATIENT_MEDICARE: "Medicare",
  PRESCRIBER_NAME: "Prescriber",
  PRESCRIBER_HPI_I: "Prescriber HPI-I",
}
export const FIELD_ORDER = Object.keys(FIELD_LABELS) as FieldName[]
export const APPROVAL_FIELDS: FieldName[] = [
  "APPROVAL_REFERENCE",
  "TGA_CATEGORY",
  "DOSAGE_FORM",
  "VALID_FROM",
  "VALID_TO",
]

/** Why a value was changed. PROVISIONAL: the closed list awaits the Clinical Safety Officer. */
export const CORRECTION_REASONS: Record<string, string> = {
  OCR_MISREAD: "The letter was read wrongly",
  NOT_ON_LETTER: "Missing from what was read",
  VOCABULARY_MAPPING: "Mapped to the clinic's category or dosage form",
  LETTER_ERROR_CONFIRMED: "Letter error, confirmed with the TGA",
}

/** Why a message is not recorded. PROVISIONAL, as above. */
export const REJECT_REASONS: Record<string, string> = {
  NOT_A_TGA_APPROVAL: "Not a TGA approval",
  DUPLICATE_OF_EXISTING: "Already recorded",
  PATIENT_NOT_AT_THIS_CLINIC: "Patient is not at this clinic",
  ILLEGIBLE: "Can't be read",
  SUSPICIOUS_SENDER: "Suspicious or unexpected sender",
}

/** Why the pipeline stopped, in words. The server sends codes only. */
export const STATE_REASONS: Record<string, string> = {
  UNTRUSTED_SENDER: "Sender not verified. It can only be rejected.",
  NO_ATTACHMENT: "No attachment",
  NO_USABLE_ATTACHMENT: "No attachment passed the file checks",
  ENCRYPTED: "PDF is password-protected. Read it and enter the values.",
  NEEDS_MANUAL_READ:
    "No text could be read (scanned letter). Enter the values from the PDF.",
}

export const REFUSAL_REASONS: Record<string, string> = {
  TOO_LARGE: "Over 25 MB",
  EMPTY_FILE: "Empty file",
  TYPE_NOT_ALLOWED: "Not a PDF",
  DOUBLE_EXTENSION: "Disguised file name",
  TYPE_MISMATCH: "Contents are not a PDF",
  MALWARE_DETECTED: "Malware detected",
  SCAN_ERROR: "Scan failed",
  TOO_MANY_ATTACHMENTS: "More than 10 attachments",
}

export const inboxRepo = {
  queue: async (filter: QueueFilter) =>
    (
      await TgaInboxService.inboxListMessages({
        query: { state: QUEUE_FILTERS[filter].state, limit: 100 },
      })
    ).data as InboxQueue,
  message: async (id: string) =>
    (await TgaInboxService.inboxReadMessage({ path: { message_id: id } }))
      .data as InboxMessageDetail,
  address: async () => (await TgaInboxService.inboxInboxAddress()).data,
  /** The original PDF as a Blob, for an object URL the review screen frames. */
  pdf: async (attachmentId: string) =>
    (
      await TgaInboxService.inboxAttachmentContent({
        path: { attachment_id: attachmentId },
        responseType: "blob",
      })
    ).data as unknown as Blob,
  claim: async (id: string) =>
    (await TgaInboxService.inboxClaimMessage({ path: { message_id: id } }))
      .data as InboxMessageDetail,
  accept: async (id: string, body: AcceptRequest) =>
    (
      await TgaInboxService.inboxAcceptMessage({
        path: { message_id: id },
        body,
      })
    ).data as DecisionResult,
  reject: async (id: string, reasonCode: string) =>
    (
      await TgaInboxService.inboxRejectMessage({
        path: { message_id: id },
        body: { reason_code: reasonCode },
      })
    ).data as DecisionResult,
  defer: async (id: string) =>
    (await TgaInboxService.inboxDeferMessage({ path: { message_id: id } }))
      .data as DecisionResult,
}

export const inboxQueueQuery = (filter: QueueFilter) =>
  queryOptions({
    queryKey: ["inbox", "queue", filter],
    queryFn: () => inboxRepo.queue(filter),
    staleTime: 15_000,
  })

export const inboxMessageQuery = (id: string) =>
  queryOptions({
    queryKey: ["inbox", "message", id],
    queryFn: () => inboxRepo.message(id),
    staleTime: 5_000,
  })

export const inboxAddressQuery = queryOptions({
  queryKey: ["inbox", "address"],
  queryFn: inboxRepo.address,
  staleTime: Number.POSITIVE_INFINITY,
})

export const inboxPdfQuery = (attachmentId: string) =>
  queryOptions({
    queryKey: ["inbox", "pdf", attachmentId],
    queryFn: () => inboxRepo.pdf(attachmentId),
    staleTime: Number.POSITIVE_INFINITY,
    // A PDF is PHI: drop it from memory soon after the screen closes.
    gcTime: 60_000,
  })

/** Confidence as a tone: ok at or over the floor, warn under it, danger when nothing was read. */
export const confidenceTone = (
  confidence: string | null | undefined,
  belowFloor: boolean,
): "ok" | "warn" | "danger" =>
  confidence == null ? "danger" : belowFloor ? "warn" : "ok"

/**
 * The patient's accepted TGA letters, each with a draft note built from the accepted values
 * (`GET /patients/{id}/tga-letters`, `clinical_record:read` with a care relationship). The draft is
 * never stored: it fills the consult-note composer, and becomes a record only when a clinician saves
 * it as their own note and signs it (D-011 §3).
 */
export const patientTgaLettersQuery = (patientId: string) =>
  queryOptions({
    queryKey: ["inbox", "patient-letters", patientId],
    queryFn: async () =>
      (
        await TgaInboxService.inboxPatientTgaLetters({
          path: { patient_id: patientId },
        })
      ).data as PatientTgaLetter[],
    staleTime: 30_000,
    retry: false,
  })
