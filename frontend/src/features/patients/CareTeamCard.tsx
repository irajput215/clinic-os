import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query"
import { Loader2, UserPlus } from "lucide-react"
import { useId, useState } from "react"
import { toast } from "sonner"
import { Button } from "@/components/ui/button"
import { practitionersQuery } from "@/data/appointments"
import { canManageCareTeam, careTeamQuery, careTeamRepo } from "@/data/careTeam"
import { myPermissionsQuery } from "@/data/permissions"
import {
  Card,
  ErrorState,
  Field,
  FormAlert,
  SkeletonRows,
} from "@/design/primitives"
import { formatDate } from "@/lib/format"
import { describeError } from "@/lib/http"

/**
 * The patient's care team (T1-34, decision D-007): the doctors and nurses whose access to this record
 * goes through an active care relationship. Shown only to an account that may change it (an owner,
 * administrator or authorised prescriber); the server refuses everyone else whatever this shows.
 * No optimistic update: the list redraws from the server's answer.
 */
export function CareTeamCard({ patientId }: { patientId: string }) {
  const { data: permissions } = useQuery(myPermissionsQuery)
  if (!canManageCareTeam(permissions)) return null
  return <CareTeam patientId={patientId} />
}

function CareTeam({ patientId }: { patientId: string }) {
  const queryClient = useQueryClient()
  const team = useQuery(careTeamQuery(patientId))
  const practitioners = useQuery(practitionersQuery)
  const [choice, setChoice] = useState("")
  const selectId = useId()

  const settle = (data: Awaited<ReturnType<typeof careTeamRepo.add>>) =>
    queryClient.setQueryData(careTeamQuery(patientId).queryKey, data)

  const add = useMutation({
    mutationFn: (practitionerId: string) =>
      careTeamRepo.add(patientId, practitionerId),
    onSuccess: (data) => {
      settle(data)
      setChoice("")
      toast.success("Added to the care team.")
    },
  })
  const end = useMutation({
    mutationFn: (relationshipId: string) =>
      careTeamRepo.end(patientId, relationshipId),
    onSuccess: (data) => {
      settle(data)
      toast.success("Care relationship ended.")
    },
    onError: (error) => toast.error(describeError(error)),
  })

  const members = team.data?.data ?? []
  const onTeam = new Set(members.map((m) => m.practitioner_id))
  const candidates = (practitioners.data ?? []).filter((p) => !onTeam.has(p.id))

  return (
    <Card title="Care team">
      {team.isPending ? (
        <SkeletonRows rows={2} />
      ) : team.isError ? (
        <ErrorState error={team.error} onRetry={() => void team.refetch()} />
      ) : (
        <div className="space-y-3.5">
          {members.length === 0 ? (
            <p className="text-sm text-stone">
              No one yet. Doctors and nurses can open this record once they are
              on its care team.
            </p>
          ) : (
            <ul className="divide-y divide-line-faint" data-testid="care-team">
              {members.map((m) => (
                <li
                  key={m.id}
                  className="flex items-center justify-between gap-3 py-2 text-sm first:pt-0"
                >
                  <span className="min-w-0">
                    <span className="block truncate font-medium">
                      {m.practitioner_name ?? "Former staff member"}
                    </span>
                    <span className="text-xs text-stone">
                      Since {formatDate(m.active_from)}
                    </span>
                  </span>
                  <Button
                    size="sm"
                    variant="outline"
                    className="max-lg:min-h-11"
                    disabled={end.isPending}
                    onClick={() => end.mutate(m.id)}
                    aria-label={`End care relationship with ${m.practitioner_name ?? "former staff member"}`}
                  >
                    {end.isPending && end.variables === m.id ? (
                      <Loader2 className="animate-spin" />
                    ) : null}
                    End
                  </Button>
                </li>
              ))}
            </ul>
          )}
          <form
            className="flex flex-wrap items-end gap-2"
            onSubmit={(e) => {
              e.preventDefault()
              if (choice) add.mutate(choice)
            }}
          >
            <div className="min-w-0 flex-1 basis-48">
              <Field label="Add a clinician" htmlFor={selectId}>
                <select
                  id={selectId}
                  className="field-input"
                  value={choice}
                  onChange={(e) => {
                    setChoice(e.target.value)
                    add.reset()
                  }}
                  disabled={practitioners.isPending || candidates.length === 0}
                >
                  <option value="">
                    {candidates.length === 0 && !practitioners.isPending
                      ? "Everyone is already on the team"
                      : "Choose a doctor or nurse"}
                  </option>
                  {candidates.map((p) => (
                    <option key={p.id} value={p.id}>
                      {p.name} ({p.title})
                    </option>
                  ))}
                </select>
              </Field>
            </div>
            <Button
              type="submit"
              className="min-h-11"
              disabled={!choice || add.isPending}
            >
              {add.isPending ? (
                <Loader2 className="animate-spin" />
              ) : (
                <UserPlus />
              )}
              Add
            </Button>
          </form>
          {add.isError ? (
            <FormAlert>{describeError(add.error)}</FormAlert>
          ) : null}
        </div>
      )}
    </Card>
  )
}
