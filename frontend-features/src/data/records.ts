import { queryOptions } from "@tanstack/react-query"
import { apiCall } from "@/data/api"
import { sourceOf } from "@/data/capabilities"
import { uuid } from "@/data/preview/seed"
import { readPreview, writePreview } from "@/data/preview/store"
import type { ClinicalRecordSummary, SoapNote } from "@/data/types"
import { Refusal } from "@/lib/http"

/**
 * Clinical records (consult notes). API routes (feat/clinical-records,
 * backend/app/modules/clinical_records/router.py):
 *   GET  /patients/{id}/clinical-records      POST /clinical-records
 *   POST /clinical-records/{id}/sign          POST /clinical-records/{id}/amendments
 * A signed version is immutable; a correction is a new version with a mandatory reason.
 */
interface RecordsRepo {
  listForPatient(patientId: string): Promise<ClinicalRecordSummary[]>
  create(patientId: string, soap: SoapNote): Promise<{ id: string }>
  sign(recordId: string): Promise<void>
  amend(recordId: string, soap: SoapNote, reason: string): Promise<void>
}

const api: RecordsRepo = {
  listForPatient: async (patientId) =>
    (
      await apiCall<{ data: ClinicalRecordSummary[] }>(
        "GET",
        "/api/v1/patients/{patient_id}/clinical-records",
        { path: { patient_id: patientId } },
      )
    ).data,
  create: (patientId, soap) =>
    apiCall("POST", "/api/v1/clinical-records", {
      body: { patient_id: patientId, record_type: "NOTE", soap },
    }),
  sign: async (recordId) => {
    await apiCall("POST", "/api/v1/clinical-records/{record_id}/sign", {
      path: { record_id: recordId },
    })
  },
  amend: async (recordId, soap, reason) => {
    await apiCall("POST", "/api/v1/clinical-records/{record_id}/amendments", {
      path: { record_id: recordId },
      body: { soap, amendment_reason: reason },
    })
  },
}

/** The backend renders SOAP into the single narrative column; the preview does the same. */
export const renderSoap = (soap: SoapNote) =>
  (
    [
      ["S", soap.subjective],
      ["O", soap.objective],
      ["A", soap.assessment],
      ["P", soap.plan],
    ] as const
  )
    .filter(([, v]) => v?.trim())
    .map(([k, v]) => `${k}: ${v?.trim()}`)
    .join("\n")

const preview: RecordsRepo = {
  listForPatient: async (patientId) =>
    (await readPreview()).records
      .filter((r) => r.patient_id === patientId)
      .sort((a, b) => b.created_at.localeCompare(a.created_at)),
  create: (patientId, soap) =>
    writePreview((s) => {
      const body = renderSoap(soap)
      if (!body)
        throw new Refusal(
          "EMPTY_NOTE",
          "Write at least one section of the note.",
        )
      const id = uuid()
      const now = new Date().toISOString()
      s.records.unshift({
        id,
        patient_id: patientId,
        record_type: "NOTE",
        author_id: s.me,
        current_version: 1,
        signed_at: null,
        deleted_at: null,
        created_at: now,
        latest_version: {
          id: uuid(),
          clinical_record_id: id,
          version: 1,
          body,
          body_format: "PLAIN",
          author_id: s.me,
          signed_at: null,
          supersedes_version: null,
          amendment_reason: null,
          created_at: now,
        },
      })
      return { id }
    }),
  sign: (recordId) =>
    writePreview((s) => {
      const r = s.records.find((x) => x.id === recordId)
      if (!r) throw new Refusal("NOT_FOUND", "That note isn't available.")
      if (r.signed_at)
        throw new Refusal(
          "RECORD_ALREADY_SIGNED",
          "This note is already signed.",
        )
      if (r.author_id !== s.me)
        throw new Refusal("NOT_AUTHOR", "Only the author can sign this note.")
      const now = new Date().toISOString()
      r.signed_at = now
      r.latest_version.signed_at = now
    }),
  amend: (recordId, soap, reason) =>
    writePreview((s) => {
      const r = s.records.find((x) => x.id === recordId)
      if (!r) throw new Refusal("NOT_FOUND", "That note isn't available.")
      if (!reason.trim())
        throw new Refusal(
          "AMENDMENT_REASON_REQUIRED",
          "Say why the note is being amended.",
        )
      const body = renderSoap(soap)
      if (!body)
        throw new Refusal(
          "EMPTY_NOTE",
          "Write at least one section of the note.",
        )
      const now = new Date().toISOString()
      r.current_version += 1
      r.latest_version = {
        id: uuid(),
        clinical_record_id: r.id,
        version: r.current_version,
        body,
        body_format: "PLAIN",
        author_id: s.me,
        signed_at: now,
        supersedes_version: r.current_version - 1,
        amendment_reason: reason.trim(),
        created_at: now,
      }
    }),
}

export const recordsRepo: RecordsRepo =
  sourceOf("clinicalRecords") === "api" ? api : preview

export const patientRecordsQuery = (patientId: string) =>
  queryOptions({
    queryKey: ["records", "patient", patientId],
    queryFn: () => recordsRepo.listForPatient(patientId),
    staleTime: 15_000,
  })

/** Split a stored `S: … / O: … / A: … / P: …` narrative back into sections for display. */
export const parseSoap = (body: string): Array<[string, string]> => {
  const labels: Record<string, string> = {
    S: "Subjective",
    O: "Objective",
    A: "Assessment",
    P: "Plan",
  }
  const out: Array<[string, string]> = []
  for (const line of body.split("\n")) {
    const m = /^([SOAP]):\s?(.*)$/.exec(line)
    if (m) out.push([labels[m[1]], m[2]])
    else if (out.length) out[out.length - 1][1] += `\n${line}`
    else out.push(["Note", line])
  }
  return out
}
