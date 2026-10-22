import { useQuery } from "@tanstack/react-query"
import { myPermissionsQuery } from "@/data/permissions"
import type { Prescription, PrescriptionState } from "@/data/scripts"
import { currentUserQuery } from "@/lib/session"
import type { ScriptAction } from "./ScriptCard"

/** Where each correction may start from: the server's own rule (decision D-010). */
const CANCELLABLE: readonly PrescriptionState[] = [
  "DRAFT",
  "SIGNED",
  "BLOCKED",
  "FAILED",
]
const AMENDABLE: readonly PrescriptionState[] = ["SIGNED", "BLOCKED", "FAILED"]

/**
 * Which buttons a script shows to this person. Advisory only: the server re-decides permission,
 * prescriber of record, care relationship, step-up, state and the gate on every request. A
 * permission set the API could not report counts as held, so the server's `403` is the answer
 * rather than a hidden control.
 */
export function useScriptActions() {
  const { data: me } = useQuery(currentUserQuery)
  const { data: permissions } = useQuery({
    ...myPermissionsQuery,
    retry: false,
  })
  const holds = (code: string) =>
    !permissions?.known || permissions.codes.includes(code)
  // Editing and cancelling are for the script's own people: who drafted it, or its prescriber.
  const own = (s: Prescription) =>
    me?.id !== undefined &&
    (s.drafted_by === me.id || s.prescriber_id === me.id)

  const actionFor = (s: Prescription): ScriptAction => {
    if (s.state === "DRAFT")
      return s.prescriber_id === me?.id && holds("prescription:sign")
        ? "sign"
        : null
    if (s.state === "SIGNED" || s.state === "BLOCKED" || s.state === "FAILED")
      return holds("prescription:dispatch") ? "send" : null
    return null
  }
  const canEdit = (s: Prescription) =>
    s.state === "DRAFT" && own(s) && holds("prescription:modify")
  const canCancel = (s: Prescription) =>
    CANCELLABLE.includes(s.state) && own(s) && holds("prescription:modify")
  const canAmend = (s: Prescription) =>
    AMENDABLE.includes(s.state) &&
    s.prescriber_id === me?.id &&
    holds("prescription:sign")
  return {
    actionFor,
    canStage: holds("prescription:create"),
    canEdit,
    canCancel,
    canAmend,
  }
}
