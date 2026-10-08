import { useQuery, useSuspenseQuery } from "@tanstack/react-query"
import { Plus } from "lucide-react"
import { useState } from "react"
import { Button } from "@/components/ui/button"
import { Checkbox } from "@/components/ui/checkbox"
import { isActionable, scriptsQuery } from "@/data/scripts"
import { Card, EmptyState, Mono, PageHeader } from "@/design/primitives"
import { PrescriptionStatePill } from "@/features/shared/pills"
import { formatDayMonth } from "@/lib/format"
import { currentUserQuery } from "@/lib/session"
import { ScriptCard } from "./ScriptCard"
import { ReviewSignDialog, StageScriptDialog } from "./ScriptDialogs"
import { useScriptActions } from "./useScriptAction"

export function ScriptsPage() {
  const { data: scripts } = useSuspenseQuery(scriptsQuery)
  const { data: me } = useQuery(currentUserQuery)
  const { actionFor, canStage } = useScriptActions()
  const [staging, setStaging] = useState(false)
  // The id, not a copy: the dialog always shows the server's latest answer for the script.
  const [reviewingId, setReviewingId] = useState<string | null>(null)
  const [justMine, setJustMine] = useState(false)

  const queue = scripts.filter((s) => isActionable(s.state))
  const history = scripts
    .filter((s) => !isActionable(s.state))
    .filter((s) => !justMine || s.prescriber_id === me?.id)
  const reviewing = scripts.find((s) => s.id === reviewingId) ?? null

  return (
    <>
      <PageHeader
        title="Script staging queue"
        subtitle="Nurse drafts → doctor reviews & signs. Eligibility and conventional-therapy-first are captured on every draft, and the safety gate checks the TGA approval at the date of service before anything is signed or queued for a pharmacy."
        actions={
          canStage ? (
            <Button onClick={() => setStaging(true)}>
              <Plus /> Stage a draft
            </Button>
          ) : undefined
        }
      />

      <Card title={`Awaiting action (${queue.length})`}>
        {queue.length === 0 ? (
          <EmptyState
            title="The queue is clear."
            body="New drafts from triage appear here for review."
          />
        ) : (
          <div className="space-y-3">
            {queue.map((s) => (
              <ScriptCard
                key={s.id}
                script={s}
                action={actionFor(s)}
                onReview={() => setReviewingId(s.id)}
              />
            ))}
          </div>
        )}
      </Card>

      <Card
        className="mt-3.5"
        title="Recent activity"
        action={
          <label
            htmlFor="just-mine"
            className="flex cursor-pointer items-center gap-2 text-[13px] text-stone max-lg:-my-3 max-lg:min-h-11"
          >
            <Checkbox
              id="just-mine"
              checked={justMine}
              onCheckedChange={(v) => setJustMine(v === true)}
            />
            Just my scripts
          </label>
        }
        bodyClassName="-mx-5 -mb-[18px]"
      >
        {history.length === 0 ? (
          <EmptyState title="Nothing signed and queued yet." />
        ) : (
          <div className="overflow-x-auto">
            <table className="data-table">
              <thead>
                <tr>
                  <th className="pl-5">Patient</th>
                  <th>Product</th>
                  <th className="max-md:hidden">Prescriber</th>
                  <th className="max-md:pr-5">Status</th>
                  <th className="pr-5 max-lg:hidden">Pharmacy reference</th>
                </tr>
              </thead>
              <tbody>
                {history.map((s) => (
                  <tr key={s.id}>
                    <td className="pl-5">
                      <div className="font-semibold">
                        {s.patient_name ?? "Patient"}
                      </div>
                      <div className="text-xs text-stone">
                        {formatDayMonth(
                          s.dispatch?.requested_at ??
                            s.signed_at ??
                            s.created_at,
                        )}
                      </div>
                    </td>
                    <td>{s.medicine_name}</td>
                    <td className="max-md:hidden">
                      {s.prescriber_name ?? "-"}
                    </td>
                    <td className="max-md:pr-5">
                      <PrescriptionStatePill state={s.state} />
                    </td>
                    <td className="pr-5 max-lg:hidden">
                      {s.dispatch?.provider_reference ? (
                        <Mono className="text-[11.5px]">
                          {s.dispatch.provider_reference}
                        </Mono>
                      ) : s.state === "QUEUED" ? (
                        <span className="text-[13px] text-stone">
                          Not sent: no pharmacy connection
                        </span>
                      ) : (
                        <span className="text-stone-faint">-</span>
                      )}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </Card>

      <StageScriptDialog open={staging} onOpenChange={setStaging} />
      <ReviewSignDialog
        script={reviewing}
        action={reviewing ? actionFor(reviewing) : null}
        onOpenChange={(o) => !o && setReviewingId(null)}
      />
    </>
  )
}
