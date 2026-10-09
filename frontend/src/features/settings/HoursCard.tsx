import { zodResolver } from "@hookform/resolvers/zod"
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query"
import { Loader2 } from "lucide-react"
import { useEffect } from "react"
import { useForm, useWatch } from "react-hook-form"
import { toast } from "sonner"
import { Button } from "@/components/ui/button"
import {
  type ClinicHours,
  clinicHoursQuery,
  minutesOf,
  SLOT_MINUTES,
  saveClinicHours,
  WEEKDAY_NAMES,
} from "@/data/clinic-hours"
import { Card, ErrorState, Field, FormAlert } from "@/design/primitives"
import { focusFirstError } from "@/lib/form"
import { describeError } from "@/lib/http"
import { z } from "@/lib/zod"

// MIRROR: backend/app/modules/appointments/schemas.py `AppointmentSettingsUpdate`. The server
// decides; this explains a refusal before anything is sent, on the day it is about.
const TIME = /^([01]\d|2[0-3]):[0-5]\d$/

const daySchema = z.object({
  open: z.boolean(),
  opens_at: z.string(),
  closes_at: z.string(),
})

const hoursSchema = z
  .object({
    slot_minutes: z.enum(SLOT_MINUTES.map(String) as [string, ...string[]]),
    days: z.array(daySchema).length(7),
  })
  .superRefine((value, ctx) => {
    const slot = Number(value.slot_minutes)
    value.days.forEach((day, index) => {
      if (!day.open) return
      for (const key of ["opens_at", "closes_at"] as const) {
        if (!TIME.test(day[key])) {
          ctx.addIssue({
            code: "custom",
            path: ["days", index, key],
            message: "Enter a time.",
          })
          return
        }
        if (minutesOf(day[key]) % 5) {
          ctx.addIssue({
            code: "custom",
            path: ["days", index, key],
            message: "Use a time on a 5-minute mark.",
          })
          return
        }
      }
      const span = minutesOf(day.closes_at) - minutesOf(day.opens_at)
      if (span <= 0)
        ctx.addIssue({
          code: "custom",
          path: ["days", index, "closes_at"],
          message: "Closing must be after opening.",
        })
      else if (span < slot)
        ctx.addIssue({
          code: "custom",
          path: ["days", index, "closes_at"],
          message: `Open for at least one ${slot}-minute slot.`,
        })
    })
    if (!value.days.some((day) => day.open))
      ctx.addIssue({
        code: "custom",
        path: ["days"],
        message: "Open the clinic on at least one day.",
      })
  })
type HoursValues = z.infer<typeof hoursSchema>

const toForm = (hours: ClinicHours): HoursValues => ({
  slot_minutes: String(hours.slot_minutes),
  days: hours.hours.map((day) => ({
    open: Boolean(day.opens_at && day.closes_at),
    opens_at: day.opens_at ?? "09:00",
    closes_at: day.closes_at ?? "17:00",
  })),
})

/** Opening hours per weekday and the slot length: they drive the booking page and the calendar. */
export function HoursCard() {
  const hours = useQuery(clinicHoursQuery)
  return (
    <Card title="Opening hours">
      {hours.isPending ? (
        <div aria-busy="true" aria-label="Loading" role="status">
          {Array.from({ length: 8 }, (_, i) => (
            <div
              key={i}
              className="mt-2 h-10 animate-pulse rounded-btn bg-fill/70 first:mt-0"
            />
          ))}
        </div>
      ) : hours.isError ? (
        <ErrorState error={hours.error} onRetry={() => hours.refetch()} />
      ) : (
        <HoursForm current={hours.data} />
      )}
    </Card>
  )
}

function HoursForm({ current }: { current: ClinicHours }) {
  const queryClient = useQueryClient()
  const form = useForm<HoursValues>({
    shouldFocusError: false,
    resolver: zodResolver(hoursSchema),
    defaultValues: toForm(current),
  })
  const { errors, isDirty } = form.formState
  const days = useWatch({ control: form.control, name: "days" })

  // Follow a save made elsewhere while nothing is being edited here.
  useEffect(() => {
    if (!form.formState.isDirty) form.reset(toForm(current))
  }, [current, form])

  const save = useMutation({
    mutationFn: (values: HoursValues) =>
      saveClinicHours({
        slot_minutes: Number(values.slot_minutes) as 10 | 15 | 20 | 30 | 60,
        hours: values.days.map((day, index) => ({
          weekday: index + 1,
          opens_at: day.open ? day.opens_at : null,
          closes_at: day.open ? day.closes_at : null,
        })) as Parameters<typeof saveClinicHours>[0]["hours"],
      }),
    onSuccess: (saved) => {
      const { bookings_outside_hours, ...settings } = saved
      queryClient.setQueryData(clinicHoursQuery.queryKey, settings)
      void queryClient.invalidateQueries({ queryKey: ["public-slots"] })
      form.reset(toForm(settings))
      toast.success(
        bookings_outside_hours > 0
          ? `Opening hours saved. ${bookings_outside_hours} upcoming booking${bookings_outside_hours === 1 ? " is" : "s are"} outside the new hours and ${bookings_outside_hours === 1 ? "has" : "have"} been kept.`
          : "Opening hours saved",
      )
    },
  })

  const daysError = (errors.days as { message?: string } | undefined)?.message

  return (
    <form
      onSubmit={form.handleSubmit((v) => save.mutate(v), focusFirstError)}
      noValidate
      className="grid gap-4"
    >
      <Field
        label="Slot length"
        htmlFor="hours-slot_minutes"
        hint="Your booking page offers a start time every slot, from opening. Longer visits take more than one slot."
        className="max-w-[240px]"
      >
        <select
          id="hours-slot_minutes"
          className="field-input"
          {...form.register("slot_minutes")}
        >
          {SLOT_MINUTES.map((minutes) => (
            <option key={minutes} value={String(minutes)}>
              {minutes} minutes
            </option>
          ))}
        </select>
      </Field>

      <fieldset className="grid gap-1">
        <legend className="field-label">Hours (Sydney time)</legend>
        {WEEKDAY_NAMES.map((name, index) => {
          const open = days?.[index]?.open
          const dayErrors = errors.days?.[index]
          const message =
            dayErrors?.opens_at?.message ?? dayErrors?.closes_at?.message
          return (
            <div
              key={name}
              data-testid={`hours-${name.toLowerCase()}`}
              className="grid grid-cols-[minmax(0,1fr)_auto] items-center gap-x-3 gap-y-1 border-line-faint border-t py-2 first-of-type:border-t-0 sm:grid-cols-[150px_minmax(0,1fr)]"
            >
              <label className="flex min-h-11 items-center gap-2.5 text-sm font-medium lg:min-h-9">
                <input
                  type="checkbox"
                  className="size-4 accent-[var(--color-clay)]"
                  aria-label={`Open on ${name}`}
                  {...form.register(`days.${index}.open`)}
                />
                {name}
              </label>
              {open ? (
                <div className="col-span-2 flex flex-wrap items-center gap-2 sm:col-span-1">
                  <input
                    type="time"
                    step={300}
                    className="field-input w-[124px]"
                    aria-label={`${name} opens`}
                    aria-invalid={dayErrors?.opens_at ? "true" : undefined}
                    {...form.register(`days.${index}.opens_at`)}
                  />
                  <span className="text-sm text-stone">to</span>
                  <input
                    type="time"
                    step={300}
                    className="field-input w-[124px]"
                    aria-label={`${name} closes`}
                    aria-invalid={dayErrors?.closes_at ? "true" : undefined}
                    {...form.register(`days.${index}.closes_at`)}
                  />
                </div>
              ) : (
                <span className="text-sm text-stone-faint">Closed</span>
              )}
              {message ? (
                <p
                  className="col-span-2 text-xs text-danger sm:col-start-2"
                  role="alert"
                >
                  {message}
                </p>
              ) : null}
            </div>
          )
        })}
        {daysError ? (
          <p className="text-xs text-danger" role="alert">
            {daysError}
          </p>
        ) : null}
      </fieldset>

      <p className="text-xs text-stone">
        Existing bookings are never moved or cancelled when the hours change.
        Staff can still book outside them from the calendar.
      </p>
      {save.isError ? <FormAlert>{describeError(save.error)}</FormAlert> : null}
      <div className="flex flex-wrap gap-2">
        <Button type="submit" disabled={!isDirty || save.isPending}>
          {save.isPending ? <Loader2 className="animate-spin" /> : null}
          Save opening hours
        </Button>
        {isDirty ? (
          <Button
            type="button"
            variant="outline"
            disabled={save.isPending}
            onClick={() => {
              save.reset()
              form.reset(toForm(current))
            }}
          >
            Discard
          </Button>
        ) : null}
      </div>
    </form>
  )
}
