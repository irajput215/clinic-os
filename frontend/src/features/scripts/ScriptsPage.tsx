import { useQuery, useSuspenseQuery } from "@tanstack/react-query"
import { Plus } from "lucide-react"
import { useState } from "react"
import { Button } from "@/components/ui/button"
import { Checkbox } from "@/components/ui/checkbox"
import { isActionable, scriptsQuery } from "@/data/scripts"
import type { Script } from "@/data/types"
import {
  Card,
  EmptyState,
  Mono,
  PageHeader,
  Pill,
  PreviewBanner,
} from "@/design/primitives"
import { ScriptStatePill } from "@/features/shared/pills"
import { formatDayMonth } from "@/lib/format"
import { currentUserQuery } from "@/lib/session"
import { ScriptCard } from "./ScriptCard"
import { ReviewSignDialog, StageScriptDialog } from "./ScriptDialogs"

export function ScriptsPage() {
  const { data: scripts } = useSuspenseQuery(scriptsQuery)
  const { data: me } = useQuery(currentUserQuery)
  const [staging, setStaging] = useState(false)
  const [reviewing, setReviewing] = useState<Script | null>(null)
  const [justMine, setJustMine] = useState(false)

  const queue = scripts.filter((s) => isActionable(s.state))
  const history = scripts
    .filter((s) => !isActionable(s.state))
    .filter((s) => !justMine || s.prescriber_id === me?.id)

  return (
    <>
      <PageHeader
        title="Script staging queue"
        subtitle="Nurse drafts → doctor reviews & signs. Eligibility and conventional-therapy-first are captured on every draft, and the safety gate checks the TGA approval at the date of service before anything reaches a pharmacy."
        actions={
          <Button onClick={() => setStaging(true)}>
            <Plus /> Stage a draft
          </Button>
        }
      />
      <PreviewBanner what="Scripts are sample drafts for your real patients; eScript tokens are simulated and nothing is sent." />

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
                canSign={s.prescriber_id === me?.id}
                onReview={() => setReviewing(s)}
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
            className="flex cursor-pointer items-center gap-2 text-[13px] text-stone"
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
          <EmptyState title="No signed scripts yet." />
        ) : (
          <div className="overflow-x-auto">
            <table className="data-table">
              <thead>
                <tr>
                  <th className="pl-5">Patient</th>
                  <th>Product</th>
                  <th className="max-md:hidden">Prescriber</th>
                  <th>Status</th>
                  <th className="max-lg:hidden">Token</th>
                  <th className="pr-5 max-md:hidden">Routed to</th>
                </tr>
              </thead>
              <tbody>
                {history.map((s) => (
                  <tr key={s.id}>
                    <td className="pl-5">
                      <div className="font-semibold">{s.patient_name}</div>
                      <div className="text-xs text-stone">
                        {formatDayMonth(s.sent_at ?? s.created_at)}
                      </div>
                    </td>
                    <td>{s.product_name}</td>
                    <td className="max-md:hidden">{s.prescriber_name}</td>
                    <td>
                      <ScriptStatePill state={s.state} />
                    </td>
                    <td className="max-lg:hidden">
                      {s.escript_token ? (
                        <span className="inline-flex items-center gap-2">
                          <Mono className="text-[11.5px]">
                            {s.escript_token}
                          </Mono>
                          <Pill tone="ok">RTPM clear</Pill>
                        </span>
                      ) : (
                        <span className="text-stone-faint">-</span>
                      )}
                    </td>
                    <td className="pr-5 max-md:hidden">
                      {s.pharmacy ?? (
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
        onOpenChange={(o) => !o && setReviewing(null)}
      />
    </>
  )
}
