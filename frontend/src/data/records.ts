import { queryOptions } from "@tanstack/react-query"
import { ClinicalRecordsService } from "@/client"
import type { ClinicalRecordSummary, SoapNote } from "@/data/types"

/**
 * Clinical records (consult notes), served by backend/app/modules/clinical_records/router.py:
 *   GET  /patients/{id}/clinical-records      POST /clinical-records
 *   POST /clinical-records/{id}/sign          POST /clinical-records/{id}/amendments
 * A signed record is immutable; a correction is a new version with a mandatory reason. Refusals come
 * back as RFC 7807 with `detail.code` (NOTE_ALREADY_SIGNED, SIGN_NOT_VERSION_AUTHOR,
 * AMENDMENT_REASON_REQUIRED, VERSION_CONFLICT) and are worded in lib/http.ts.
 */

/** The API's largest timeline page (`MAX_TIMELINE_PAGE_SIZE`). */
const PAGE_SIZE = 100

/**
 * Only the sections the clinician actually wrote, trimmed. The API renders every section it is sent
 * into the stored narrative, including an empty one, so a blank textarea must not be sent at all:
 * it would put an empty heading into a permanent clinical record.
 */
const writtenSections = (soap: SoapNote): SoapNote =>
  Object.fromEntries(
    Object.entries(soap)
      .map(([k, v]) => [k, typeof v === "string" ? v.trim() : v])
      .filter(([, v]) => typeof v === "string" && v !== ""),
  )

export const recordsRepo = {
  /** The whole timeline, newest first: every keyset page, so nothing older is silently dropped. */
  listForPatient: async (patientId: string) => {
    const records: ClinicalRecordSummary[] = []
    let cursor: string | undefined
    do {
      const { data: page } =
        await ClinicalRecordsService.recordsListPatientClinicalRecords({
          path: { patient_id: patientId },
          query: { limit: PAGE_SIZE, cursor },
        })
      records.push(...(page.data as ClinicalRecordSummary[]))
      cursor = page.next_cursor ?? undefined
    } while (cursor)
    return records
  },
  create: async (patientId: string, soap: SoapNote) =>
    (
      await ClinicalRecordsService.recordsCreateClinicalRecord({
        body: {
          patient_id: patientId,
          record_type: "NOTE",
          soap: writtenSections(soap),
        },
      })
    ).data,
  sign: async (recordId: string) => {
    await ClinicalRecordsService.recordsSignClinicalRecord({
      path: { record_id: recordId },
    })
  },
  amend: async (recordId: string, soap: SoapNote, reason: string) => {
    await ClinicalRecordsService.recordsAmendClinicalRecord({
      path: { record_id: recordId },
      body: { soap: writtenSections(soap), amendment_reason: reason.trim() },
    })
  },
}

export const patientRecordsQuery = (patientId: string) =>
  queryOptions({
    queryKey: ["records", "patient", patientId],
    queryFn: () => recordsRepo.listForPatient(patientId),
    staleTime: 15_000,
  })

const HEADINGS = ["Subjective", "Objective", "Assessment", "Plan"] as const

/**
 * Split a stored narrative back into its SOAP sections for display.
 *
 * The API stores a SOAP note as one Markdown narrative, `## Subjective\n\n…\n\n## Plan\n\n…`
 * (clinical_records/service.py `_render_soap`), with only the sections that were written. A body
 * that was not written as SOAP (for example a plain `body`) is shown whole, as "Note".
 */
export const parseSoap = (body: string): Array<[string, string]> => {
  const out: Array<[string, string]> = []
  for (const line of body.split("\n")) {
    const heading = /^## (.+)$/.exec(line)?.[1]
    if (heading && (HEADINGS as readonly string[]).includes(heading))
      out.push([heading, ""])
    else if (out.length) out[out.length - 1][1] += `\n${line}`
    else out.push(["Note", line])
  }
  return out
    .map(([label, text]): [string, string] => [label, text.trim()])
    .filter(([, text]) => text !== "")
}
