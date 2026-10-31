import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query"
import { Loader2 } from "lucide-react"
import { useEffect, useId, useState } from "react"
import { toast } from "sonner"
import { Button } from "@/components/ui/button"
import { practiceSettingsQuery, savePracticeSettings } from "@/data/practice"
import {
  Card,
  ErrorState,
  Field,
  FormAlert,
  SkeletonRows,
} from "@/design/primitives"
import { describeError } from "@/lib/http"

/**
 * Settings → Practice (manual §15.5): how long adult records are kept. Saved and audited; enforced in
 * a later phase, and nothing is ever hard-deleted. Who writes scripts is not a setting: only doctors
 * and authorised prescribers do.
 */
export function PracticeTab() {
  const settings = useQuery(practiceSettingsQuery)
  const queryClient = useQueryClient()
  const [years, setYears] = useState("7")
  const ids = { years: useId() }
  useEffect(() => {
    if (settings.data) setYears(String(settings.data.adult_retention_years))
  }, [settings.data])
  const yearsNumber = Number(years)
  const yearsError =
    !Number.isInteger(yearsNumber) || yearsNumber < 7
      ? "Keep adult records for at least 7 years."
      : yearsNumber > 100
        ? "Use 100 years or fewer."
        : undefined
  const save = useMutation({
    mutationFn: () =>
      savePracticeSettings({ adult_retention_years: yearsNumber }),
    onSuccess: (saved) => {
      queryClient.setQueryData(practiceSettingsQuery.queryKey, saved)
      void queryClient.invalidateQueries({ queryKey: ["practice", "setup"] })
      toast.success("Practice settings saved")
    },
  })

  if (settings.isPending)
    return (
      <Card>
        <SkeletonRows rows={3} />
      </Card>
    )
  if (settings.isError)
    return (
      <Card>
        <ErrorState error={settings.error} onRetry={() => settings.refetch()} />
      </Card>
    )

  return (
    <form
      noValidate
      className="space-y-4"
      onSubmit={(e) => {
        e.preventDefault()
        if (!yearsError) save.mutate()
      }}
    >
      <Card title="Record retention">
        <Field
          label="Adult records (years)"
          htmlFor={ids.years}
          error={yearsError}
          hint="At least 7 years."
        >
          <input
            id={ids.years}
            type="number"
            inputMode="numeric"
            min={7}
            max={100}
            className="field-input max-w-40"
            aria-invalid={yearsError ? true : undefined}
            value={years}
            onChange={(e) => setYears(e.target.value)}
          />
        </Field>
        <p className="mt-3 text-sm text-stone">
          Records of minors: kept until the patient turns 25. Nothing is ever
          deleted outright.
        </p>
      </Card>
      <Card title="Prescribing">
        <p className="text-sm text-stone">
          Only doctors and authorised prescribers write, sign and send scripts.
          Nurses can read the script queue.
        </p>
      </Card>
      {save.isError ? <FormAlert>{describeError(save.error)}</FormAlert> : null}
      <div className="flex justify-end">
        <Button type="submit" disabled={save.isPending || Boolean(yearsError)}>
          {save.isPending ? <Loader2 className="animate-spin" /> : null}
          Save practice settings
        </Button>
      </div>
    </form>
  )
}
