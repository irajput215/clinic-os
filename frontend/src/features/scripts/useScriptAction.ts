import { useQuery } from "@tanstack/react-query"
import { myPermissionsQuery } from "@/data/permissions"
import type { Prescription } from "@/data/scripts"
import { currentUserQuery } from "@/lib/session"
import type { ScriptAction } from "./ScriptCard"

/**
 * Which button a script shows to this person. Advisory only: the server re-decides permission,
 * prescriber of record, step-up and the gate on every request. A permission set the API could not
 * report counts as held, so the server's `403` is the answer rather than a hidden control.
 */
export function useScriptActions() {
  const { data: me } = useQuery(currentUserQuery)
  const { data: permissions } = useQuery({
    ...myPermissionsQuery,
    retry: false,
  })
  const holds = (code: string) =>
    !permissions?.known || permissions.codes.includes(code)

  const actionFor = (s: Prescription): ScriptAction => {
    if (s.state === "DRAFT")
      return s.prescriber_id === me?.id && holds("prescription:sign")
        ? "sign"
        : null
    if (s.state === "SIGNED" || s.state === "BLOCKED" || s.state === "FAILED")
      return holds("prescription:dispatch") ? "send" : null
    return null
  }
  return { actionFor, canStage: holds("prescription:create") }
}
