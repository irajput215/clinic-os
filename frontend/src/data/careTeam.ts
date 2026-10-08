import { queryOptions } from "@tanstack/react-query"
import { CareRelationshipsService } from "@/client"
import type { CareTeamPublic } from "@/client/types.gen"
import type { MyPermissions } from "@/data/permissions"
import { retryTransient } from "@/lib/http"

/**
 * A patient's care team: the practitioners with an active care relationship
 * (backend/app/modules/care_relationships; docs2/sdlc/02-patients/api.md, "Care team"; decision
 * D-007). A doctor's or nurse's access to a patient's record goes through it (T1-34).
 *
 * Only an account whose own `patient:update` is not itself relationship-bound may see or change the
 * team (an owner, administrator or authorised prescriber); the server decides, the screen only hides.
 */
export const PATIENT_UPDATE = "patient:update"

export const canManageCareTeam = (permissions: MyPermissions | undefined) =>
  permissions?.known === true &&
  permissions.codes.includes(PATIENT_UPDATE) &&
  !permissions.relationshipBound.includes(PATIENT_UPDATE)

export const careTeamQuery = (patientId: string) =>
  queryOptions({
    queryKey: ["patients", "care-team", patientId],
    queryFn: async (): Promise<CareTeamPublic> =>
      (
        await CareRelationshipsService.relationshipsListCareTeam({
          path: { patient_id: patientId },
        })
      ).data,
    retry: retryTransient,
    staleTime: 30_000,
  })

export const careTeamRepo = {
  add: async (patientId: string, practitionerId: string) =>
    (
      await CareRelationshipsService.relationshipsRecordCareRelationship({
        path: { patient_id: patientId },
        body: { practitioner_id: practitionerId },
      })
    ).data,
  end: async (patientId: string, relationshipId: string) =>
    (
      await CareRelationshipsService.relationshipsEndCareRelationship({
        path: { patient_id: patientId, care_relationship_id: relationshipId },
      })
    ).data,
}
