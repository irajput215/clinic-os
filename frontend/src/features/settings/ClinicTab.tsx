import { zodResolver } from "@hookform/resolvers/zod"
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query"
import { Loader2 } from "lucide-react"
import { useEffect } from "react"
import { useForm } from "react-hook-form"
import { toast } from "sonner"
import { Button } from "@/components/ui/button"
import { clinicProfileQuery, renameClinic } from "@/data/tenant"
import { useClinicSlug } from "@/data/useClinic"
import { Card, ErrorState, Field, FormAlert, Mono } from "@/design/primitives"
import { focusFirstError } from "@/lib/form"
import { describeError } from "@/lib/http"
import { z } from "@/lib/zod"

// MIRROR: backend/app/modules/identity_tenancy/schemas.py `normalise_display_name` (1-120 printable
// characters once whitespace runs are collapsed). The server normalises and decides; this only
// explains a refusal before it is sent.
const DISPLAY_NAME_MAX = 120
const collapse = (value: string) => value.split(/\s+/).filter(Boolean).join(" ")
const PRINTABLE = /^[^\p{Cc}\p{Cf}\p{Zl}\p{Zp}]*$/u

const clinicSchema = z.object({
  display_name: z
    .string()
    .transform(collapse)
    .pipe(
      z
        .string()
        .min(1, "Enter your clinic's name.")
        .max(
          DISPLAY_NAME_MAX,
          `Keep the name to ${DISPLAY_NAME_MAX} characters or fewer.`,
        )
        .regex(PRINTABLE, "Use letters, numbers, spaces and punctuation only."),
    ),
})
type ClinicInput = z.input<typeof clinicSchema>
type ClinicValues = z.output<typeof clinicSchema>

/**
 * The clinic's settings, for whoever holds `tenant:configure` (Practice Owner). The tab is not
 * offered to anyone else; the server refuses them `403` regardless and records the attempt.
 */
export function ClinicTab() {
  const profile = useQuery(clinicProfileQuery)

  return (
    <div className="space-y-5">
      <Card title="Clinic name">
        {profile.isPending ? (
          <div aria-busy="true" aria-label="Loading" role="status">
            <div className="h-4 w-24 animate-pulse rounded bg-fill" />
            <div className="mt-2 h-10 animate-pulse rounded-btn bg-fill/70" />
            <div className="mt-4 h-9 w-32 animate-pulse rounded-btn bg-fill/70" />
          </div>
        ) : profile.isError ? (
          <ErrorState error={profile.error} onRetry={() => profile.refetch()} />
        ) : (
          <ClinicNameForm current={profile.data.display_name} />
        )}
      </Card>
    </div>
  )
}

function ClinicNameForm({ current }: { current: string }) {
  const queryClient = useQueryClient()
  const slug = useClinicSlug()
  const form = useForm<ClinicInput, unknown, ClinicValues>({
    shouldFocusError: false,
    resolver: zodResolver(clinicSchema),
    defaultValues: { display_name: current },
  })
  const { errors, isDirty } = form.formState

  // Another tab, or another owner, may rename the clinic; follow the cache when nothing is typed.
  useEffect(() => {
    if (!form.formState.isDirty) form.reset({ display_name: current })
  }, [current, form])

  const save = useMutation({
    mutationFn: (values: ClinicValues) => renameClinic(values.display_name),
    onSuccess: (saved) => {
      queryClient.setQueryData(clinicProfileQuery.queryKey, saved)
      form.reset({ display_name: saved.display_name })
      toast.success("Clinic name saved")
    },
  })

  return (
    <form
      onSubmit={form.handleSubmit((v) => save.mutate(v), focusFirstError)}
      noValidate
      className="grid gap-4"
    >
      <Field
        label="Display name"
        htmlFor="clinic-display_name"
        error={errors.display_name?.message}
        hint="Shown to your staff, on your public booking page and in the emails your clinic sends. Your legal entity name is never shown."
      >
        <input
          id="clinic-display_name"
          className="field-input"
          autoComplete="organization"
          maxLength={DISPLAY_NAME_MAX + 20}
          aria-invalid={errors.display_name ? "true" : undefined}
          {...form.register("display_name")}
        />
      </Field>
      {slug ? (
        <p className="text-xs text-stone">
          Your booking page stays at{" "}
          <Mono className="break-all">/book/{slug}</Mono>: renaming the clinic
          does not change its link.
        </p>
      ) : null}
      {save.isError ? <FormAlert>{describeError(save.error)}</FormAlert> : null}
      <div className="flex flex-wrap gap-2">
        <Button type="submit" disabled={!isDirty || save.isPending}>
          {save.isPending ? <Loader2 className="animate-spin" /> : null}
          Save clinic name
        </Button>
        {isDirty ? (
          <Button
            type="button"
            variant="outline"
            disabled={save.isPending}
            onClick={() => {
              save.reset()
              form.reset({ display_name: current })
            }}
          >
            Discard
          </Button>
        ) : null}
      </div>
    </form>
  )
}
