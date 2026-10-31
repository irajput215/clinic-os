import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query"
import { Loader2 } from "lucide-react"
import { useEffect, useId, useState } from "react"
import { toast } from "sonner"
import type { PracticeSettingsRead } from "@/client/types.gen"
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

type StagingRole = PracticeSettingsRead["draft_staging_roles"][number]

const STAGING_CHOICES: Array<{ label: string; roles: StagingRole[] }> = [
  { label: "Nurses", roles: ["NURSE"] },
  { label: "Nurses and doctors", roles: ["NURSE", "DOCTOR"] },
  {
    label: "Nurses, doctors and reception",
    roles: ["NURSE", "DOCTOR", "ADMINISTRATOR"],
  },
]

const choiceOf = (roles: readonly string[]) =>
  STAGING_CHOICES.findIndex(
    (c) =>
      c.roles.length === roles.length &&
      c.roles.every((r) => roles.includes(r)),
  )

/**
 * Settings → Practice (manual §15.5): who may stage script drafts, and how long adult records are
 * kept. Both are saved together and audited. Retention is recorded now and enforced in a later phase;
 * nothing is ever hard-deleted.
 */
export function PracticeTab() {
  const settings = useQuery(practiceSettingsQuery)
  const queryClient = useQueryClient()
  const [choice, setChoice] = useState(0)
  const [years, setYears] = useState("7")
  const ids = { years: useId(), group: useId() }
  useEffect(() => {
    if (!settings.data) return
    setChoice(Math.max(0, choiceOf(settings.data.draft_staging_roles)))
    setYears(String(settings.data.adult_retention_years))
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
      savePracticeSettings({
        draft_staging_roles: STAGING_CHOICES[choice].roles,
        adult_retention_years: yearsNumber,
      }),
    onSuccess: (saved) => {
      queryClient.setQueryData(practiceSettingsQuery.queryKey, saved)
      void queryClient.invalidateQueries({ queryKey: ["practice", "setup"] })
      toast.success("Practice settings saved")
    },
  })

  if (settings.isPending)
    return (
      <Card>
        <SkeletonRows rows={4} />
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
      <Card title="Practice workflow">
        <fieldset aria-describedby={ids.group}>
          <legend className="field-label">Who may stage script drafts</legend>
          <div className="space-y-1">
            {STAGING_CHOICES.map((c, i) => (
              <label
                key={c.label}
                className="flex min-h-11 items-center gap-2 text-sm"
              >
                <input
                  type="radio"
                  name="staging"
                  className="size-4"
                  checked={choice === i}
                  onChange={() => setChoice(i)}
                />
                {c.label}
              </label>
            ))}
          </div>
          <p id={ids.group} className="mt-1 text-xs text-stone">
            Reception can suggest a product only as a note, never as a
            selection. A doctor always reviews and signs.
          </p>
        </fieldset>
      </Card>
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
