import { zodResolver } from "@hookform/resolvers/zod"
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query"
import { Check, ChevronLeft, Loader2 } from "lucide-react"
import { useMemo, useState } from "react"
import { useForm } from "react-hook-form"
import { Button } from "@/components/ui/button"
import { bookingRepo, clinicNameFromSlug } from "@/data/booking"
import {
  APPOINTMENT_TYPES,
  type AppointmentType,
  type PublicSlot,
} from "@/data/types"
import { Field, Mono } from "@/design/primitives"
import { clinicDateOf } from "@/lib/clinic-time"
import { focusFirstError } from "@/lib/form"
import {
  clinicToday,
  formatDate,
  formatLongDay,
  formatTime,
} from "@/lib/format"
import { describeError, httpStatus, refusalCode } from "@/lib/http"
import { cn } from "@/lib/utils"
import { z } from "@/lib/zod"
import { BrandMark } from "@/shell/BrandMark"

const VISITS: Array<{
  type: AppointmentType
  title: string
  body: string
  price: string
}> = [
  {
    type: "NURSE_TRIAGE",
    title: "Free nurse triage",
    body: "A 15-minute call with a registered nurse to check eligibility before you see a doctor.",
    price: "Free",
  },
  {
    type: "INITIAL_CONSULT",
    title: "Initial doctor consult",
    body: "A 30-minute telehealth consult. The doctor reviews your history and treatment options.",
    price: "$79",
  },
]

const details = z.object({
  condition: z
    .string()
    .trim()
    .min(3, "Tell us briefly what you'd like help with.")
    .max(300),
  tried_conventional: z.enum(["yes", "no"], { message: "Choose one." }),
  conventional_detail: z.string().trim().max(500),
  given_name: z.string().trim().min(1, "Enter your given name.").max(100),
  family_name: z.string().trim().min(1, "Enter your family name.").max(100),
  date_of_birth: z
    .string()
    .regex(/^\d{4}-\d{2}-\d{2}$/, "Enter your date of birth.")
    .refine(
      (v) =>
        v <=
        `${Number(clinicToday().slice(0, 4)) - 18}${clinicToday().slice(4)}`,
      "You need to be 18 or over to book online.",
    ),
  email: z.email("Enter a valid email."),
  phone: z
    .string()
    .trim()
    .regex(
      /^(\+?61|0)4\d{2}\s?\d{3}\s?\d{3}$/,
      "Enter an Australian mobile number.",
    ),
  consent: z.literal(true, {
    message: "Please agree so we can keep your information.",
  }),
})
type Details = z.infer<typeof details>

type Step = "visit" | "details" | "time" | "done"

const slotsQuery = (clinicSlug: string, visit: AppointmentType) => ({
  queryKey: ["public-slots", clinicSlug, visit],
  queryFn: () => bookingRepo.slots(clinicSlug, visit),
  staleTime: 30_000,
})

export function BookingPage({ clinicSlug }: { clinicSlug: string }) {
  const clinic = clinicNameFromSlug(clinicSlug)
  const [step, setStep] = useState<Step>("visit")
  const [visit, setVisit] = useState<AppointmentType>("NURSE_TRIAGE")
  // Asked on arrival, so an unknown or closed clinic says so before anyone fills in the form, and
  // the first visit type's times are ready by the time the patient reaches them.
  const opening = useQuery(slotsQuery(clinicSlug, visit))
  const unavailable = httpStatus(opening.error) === 404
  const [info, setInfo] = useState<Details | null>(null)
  const [slot, setSlot] = useState<PublicSlot | null>(null)
  const [reference, setReference] = useState<string | null>(null)

  const steps: Array<[Step, string]> = [
    ["visit", "Visit"],
    ["details", "About you"],
    ["time", "Time"],
  ]
  const index = steps.findIndex(([s]) => s === step)

  return (
    <div className="backdrop-pattern min-h-dvh px-4 py-8 sm:py-14">
      <div className="mx-auto w-full max-w-[640px]">
        <div className="mb-6 flex items-center gap-3">
          <BrandMark size={36} />
          <div>
            <div className="font-serif text-xl font-semibold">
              {unavailable ? "Online booking" : clinic}
            </div>
            <div className="text-xs tracking-[0.04em] text-stone uppercase">
              Book an appointment
            </div>
          </div>
        </div>

        <div className="animate-rise rounded-[18px] border border-line bg-paper/95 p-6 shadow-[0_24px_70px_rgba(38,34,27,0.12)] sm:p-8">
          {unavailable ? (
            <section className="py-4 text-center" role="alert">
              <h1 className="font-serif text-[26px] font-medium">
                This booking page isn't available
              </h1>
              <p className="mt-2 text-sm text-stone">
                Check the link you were given, or contact the clinic directly.
              </p>
            </section>
          ) : null}

          {!unavailable && step !== "done" ? (
            <ol
              className="mb-6 flex items-center gap-2 text-xs font-semibold tracking-[0.04em] uppercase"
              aria-label="Progress"
            >
              {steps.map(([key, label], i) => (
                <li key={key} className="flex items-center gap-2">
                  <span
                    className={cn(
                      "grid size-6 place-items-center rounded-full font-mono text-[11px]",
                      i < index && "bg-ok text-white",
                      i === index && "bg-clay text-white",
                      i > index && "bg-fill text-stone",
                    )}
                    aria-current={i === index ? "step" : undefined}
                  >
                    {i < index ? <Check className="size-3.5" /> : i + 1}
                  </span>
                  <span
                    className={cn(
                      "whitespace-nowrap",
                      i === index ? "text-ink" : "text-stone-faint",
                    )}
                  >
                    {label}
                  </span>
                  {i < steps.length - 1 ? (
                    <span className="mx-1 h-px w-3 shrink-0 bg-line sm:w-6" />
                  ) : null}
                </li>
              ))}
            </ol>
          ) : null}

          {!unavailable && step === "visit" ? (
            <section>
              <h1 className="font-serif text-[26px] font-medium">
                What kind of visit?
              </h1>
              <p className="mt-1 text-sm text-stone">
                Most new patients start with a free nurse triage.
              </p>
              <div className="mt-5 grid gap-3">
                {VISITS.map((v) => (
                  <button
                    key={v.type}
                    type="button"
                    onClick={() => setVisit(v.type)}
                    aria-pressed={visit === v.type}
                    className={cn(
                      "rounded-inner border bg-paper p-4 text-left transition-[border-color,box-shadow]",
                      visit === v.type
                        ? "border-clay ring-3 ring-clay/15"
                        : "border-line hover:border-stone-faint",
                    )}
                  >
                    <div className="flex items-baseline justify-between gap-3">
                      <span className="text-[15px] font-semibold">
                        {v.title}
                      </span>
                      <Mono className="text-stone">{v.price}</Mono>
                    </div>
                    <p className="mt-1 text-sm text-stone">{v.body}</p>
                  </button>
                ))}
              </div>
              <Button
                size="lg"
                className="mt-6 w-full"
                onClick={() => setStep("details")}
              >
                Continue
              </Button>
            </section>
          ) : null}

          {step === "details" ? (
            <DetailsStep
              initial={info}
              onBack={() => setStep("visit")}
              onNext={(d) => {
                setInfo(d)
                setStep("time")
              }}
            />
          ) : null}

          {step === "time" && info ? (
            <TimeStep
              clinicSlug={clinicSlug}
              visit={visit}
              selected={slot}
              onSelect={setSlot}
              onBack={() => setStep("details")}
              onBooked={(ref) => {
                setReference(ref)
                setStep("done")
              }}
              info={info}
            />
          ) : null}

          {step === "done" && slot && info ? (
            <section className="py-4 text-center">
              <div className="mx-auto mb-4 grid size-12 place-items-center rounded-full bg-ok-tint text-ok">
                <Check className="size-6" />
              </div>
              <h1 className="font-serif text-[26px] font-medium">
                You're booked, {info.given_name}.
              </h1>
              <p className="mt-2 text-sm text-stone">
                {APPOINTMENT_TYPES[visit].label} with {slot.practitioner_name}
                <br />
                {formatLongDay(new Date(slot.starts_at))} at{" "}
                <Mono>{formatTime(slot.starts_at)}</Mono>
              </p>
              <p className="mt-4 text-sm">
                Reference{" "}
                <Mono className="rounded-chip bg-fill px-2 py-0.5">
                  {reference}
                </Mono>
              </p>
              <p className="mt-4 text-xs text-stone">
                Keep this reference. The clinic has your booking and will
                contact you at {info.email} if anything changes.
              </p>
            </section>
          ) : null}
        </div>

        <p className="mt-5 text-center text-balance font-mono text-[10.5px] tracking-[0.04em] text-stone-faint uppercase">
          AU data residency · Your information is handled under the Privacy
          Act&nbsp;1988
        </p>
      </div>
    </div>
  )
}

function DetailsStep({
  initial,
  onBack,
  onNext,
}: {
  initial: Details | null
  onBack: () => void
  onNext: (d: Details) => void
}) {
  const form = useForm<Details>({
    shouldFocusError: false,
    resolver: zodResolver(details),
    defaultValues: initial ?? {
      condition: "",
      conventional_detail: "",
      given_name: "",
      family_name: "",
      date_of_birth: "",
      email: "",
      phone: "",
    },
  })
  const { errors } = form.formState
  const tried = form.watch("tried_conventional")
  return (
    <form
      onSubmit={form.handleSubmit(onNext, focusFirstError(form.setFocus))}
      noValidate
    >
      <h1 className="font-serif text-[26px] font-medium">A little about you</h1>
      <p className="mt-1 text-sm text-stone">
        The first two questions only check that booking online suits you; your
        answers aren't sent. Your name and contact details are stored in
        Australia.
      </p>
      <div className="mt-5 grid gap-4 sm:grid-cols-2">
        <Field
          label="What would you like help with?"
          htmlFor="bk-cond"
          error={errors.condition?.message}
          className="sm:col-span-2"
        >
          <input
            id="bk-cond"
            className="field-input"
            placeholder="e.g. chronic back pain, sleep"
            {...form.register("condition")}
          />
        </Field>
        <fieldset className="sm:col-span-2">
          <legend className="field-label">
            Have you tried standard treatments for this?
          </legend>
          <div className="flex gap-2">
            {(["yes", "no"] as const).map((v) => (
              <label
                key={v}
                className={cn(
                  "flex cursor-pointer items-center gap-2 rounded-btn border px-4 py-2 text-sm capitalize",
                  tried === v
                    ? "border-clay bg-clay-tint text-clay-deep"
                    : "border-line bg-paper",
                )}
              >
                <input
                  type="radio"
                  value={v}
                  className="sr-only"
                  {...form.register("tried_conventional")}
                />
                {v}
              </label>
            ))}
          </div>
          {errors.tried_conventional ? (
            <p className="mt-1 text-xs text-danger" role="alert">
              {errors.tried_conventional.message}
            </p>
          ) : null}
        </fieldset>
        {tried === "yes" ? (
          <Field
            label="What did you try, and for how long?"
            htmlFor="bk-conv"
            className="sm:col-span-2"
          >
            <input
              id="bk-conv"
              className="field-input"
              {...form.register("conventional_detail")}
            />
          </Field>
        ) : tried === "no" ? (
          <p className="rounded-btn bg-info-tint px-3 py-2.5 text-[13px] text-info-deep sm:col-span-2">
            That's fine. The clinician will usually discuss standard options
            with you first.
          </p>
        ) : null}
        <Field
          label="Given name"
          htmlFor="bk-given"
          error={errors.given_name?.message}
        >
          <input
            id="bk-given"
            className="field-input"
            autoComplete="given-name"
            {...form.register("given_name")}
          />
        </Field>
        <Field
          label="Family name"
          htmlFor="bk-family"
          error={errors.family_name?.message}
        >
          <input
            id="bk-family"
            className="field-input"
            autoComplete="family-name"
            {...form.register("family_name")}
          />
        </Field>
        <Field
          label="Date of birth"
          htmlFor="bk-dob"
          error={errors.date_of_birth?.message}
        >
          <input
            id="bk-dob"
            type="date"
            className="field-input"
            autoComplete="bday"
            {...form.register("date_of_birth")}
          />
        </Field>
        <Field label="Mobile" htmlFor="bk-phone" error={errors.phone?.message}>
          <input
            id="bk-phone"
            type="tel"
            className="field-input"
            autoComplete="tel"
            placeholder="04xx xxx xxx"
            {...form.register("phone")}
          />
        </Field>
        <Field
          label="Email"
          htmlFor="bk-email"
          error={errors.email?.message}
          className="sm:col-span-2"
        >
          <input
            id="bk-email"
            type="email"
            className="field-input"
            autoComplete="email"
            {...form.register("email")}
          />
        </Field>
        <label className="flex items-start gap-2.5 text-[13px] text-stone sm:col-span-2">
          <input
            type="checkbox"
            className="mt-0.5 size-4 accent-[var(--color-clay)]"
            {...form.register("consent")}
          />
          <span>
            I agree to the clinic collecting and storing my health information
            to provide care, as described in the privacy collection notice (APP
            5).
            {errors.consent ? (
              <span className="block text-danger" role="alert">
                {errors.consent.message}
              </span>
            ) : null}
          </span>
        </label>
      </div>
      <div className="mt-6 flex gap-2">
        <Button type="button" variant="outline" size="lg" onClick={onBack}>
          <ChevronLeft /> Back
        </Button>
        <Button type="submit" size="lg" className="flex-1">
          Choose a time
        </Button>
      </div>
    </form>
  )
}

function TimeStep({
  clinicSlug,
  visit,
  selected,
  onSelect,
  onBack,
  onBooked,
  info,
}: {
  clinicSlug: string
  visit: AppointmentType
  selected: PublicSlot | null
  onSelect: (s: PublicSlot) => void
  onBack: () => void
  onBooked: (reference: string) => void
  info: Details
}) {
  const queryClient = useQueryClient()
  const slots = useQuery(slotsQuery(clinicSlug, visit))
  const days = useMemo(() => {
    const byDay = new Map<string, PublicSlot[]>()
    for (const s of slots.data ?? []) {
      const d = clinicDateOf(s.starts_at)
      byDay.set(d, [...(byDay.get(d) ?? []), s])
    }
    return [...byDay.entries()]
  }, [slots.data])
  const [day, setDay] = useState<string | null>(null)
  const activeDay = day ?? days[0]?.[0] ?? null
  const book = useMutation({
    mutationFn: () =>
      bookingRepo.book(clinicSlug, {
        type: visit,
        practitioner_id: selected!.practitioner_id,
        starts_at: selected!.starts_at,
        given_name: info.given_name,
        family_name: info.family_name,
        date_of_birth: info.date_of_birth,
        email: info.email,
        phone: info.phone,
        consent: info.consent,
      }),
    onSuccess: (r) => onBooked(r.reference),
    onError: (error) => {
      // Someone else took the time: show the times that are still free.
      if (refusalCode(error) === "SLOT_TAKEN")
        void queryClient.invalidateQueries({
          queryKey: ["public-slots", clinicSlug, visit],
        })
    },
  })

  return (
    <section>
      <h1 className="font-serif text-[26px] font-medium">Choose a time</h1>
      <p className="mt-1 text-sm text-stone">
        {APPOINTMENT_TYPES[visit].label} · {APPOINTMENT_TYPES[visit].minutes}{" "}
        minutes · times are Sydney time
      </p>
      {slots.isError ? (
        <div
          role="alert"
          className="mt-5 rounded-btn bg-danger-tint px-3 py-2.5 text-[13px] text-danger-deep"
        >
          {describeError(slots.error)}{" "}
          <button
            type="button"
            className="font-semibold underline"
            onClick={() => void slots.refetch()}
          >
            Try again
          </button>
        </div>
      ) : slots.isPending ? (
        <div
          className="mt-6 flex justify-center text-stone"
          role="status"
          aria-label="Loading times"
        >
          <Loader2 className="animate-spin" />
        </div>
      ) : days.length === 0 ? (
        <p className="mt-5 rounded-btn bg-oat px-3 py-2.5 text-[13px] text-stone">
          No online times are free in the next two weeks for this visit. Please
          contact the clinic directly.
        </p>
      ) : (
        <>
          <div className="mt-5 flex gap-2 overflow-x-auto pb-1">
            {days.map(([d]) => (
              <button
                key={d}
                type="button"
                onClick={() => setDay(d)}
                aria-pressed={activeDay === d}
                className={cn(
                  "shrink-0 rounded-inner border px-3 py-2 text-center",
                  activeDay === d
                    ? "border-clay bg-clay-tint text-clay-deep"
                    : "border-line bg-paper hover:border-stone-faint",
                )}
              >
                <div className="text-[11px] font-semibold tracking-[0.06em] uppercase">
                  {new Intl.DateTimeFormat("en-AU", {
                    weekday: "short",
                    timeZone: "UTC",
                  }).format(new Date(`${d}T12:00:00Z`))}
                </div>
                <div className="font-serif text-lg leading-tight">
                  {Number(d.slice(8))}
                </div>
              </button>
            ))}
          </div>
          <div className="mt-4 grid grid-cols-3 gap-2 sm:grid-cols-4">
            {(days.find(([d]) => d === activeDay)?.[1] ?? []).map((s) => {
              const on =
                selected?.starts_at === s.starts_at &&
                selected.practitioner_id === s.practitioner_id
              return (
                <button
                  key={`${s.practitioner_id}${s.starts_at}`}
                  type="button"
                  onClick={() => onSelect(s)}
                  aria-pressed={on}
                  title={s.practitioner_name}
                  className={cn(
                    "rounded-btn border px-2 py-2 text-center transition-colors",
                    on
                      ? "border-clay bg-clay text-white"
                      : "border-line bg-paper hover:border-clay/50",
                  )}
                >
                  <div className="font-mono text-[13px]">
                    {formatTime(s.starts_at)}
                  </div>
                  <div
                    className={cn(
                      "truncate text-[11px]",
                      on ? "text-white/85" : "text-stone",
                    )}
                  >
                    {s.practitioner_name.replace(/^Dr /, "Dr ").split(",")[0]}
                  </div>
                </button>
              )
            })}
          </div>
          {selected ? (
            <p className="mt-4 text-sm">
              {formatDate(selected.starts_at)} at{" "}
              <Mono>{formatTime(selected.starts_at)}</Mono> with{" "}
              {selected.practitioner_name}
            </p>
          ) : null}
        </>
      )}
      {book.isError ? (
        <p
          role="alert"
          className="mt-4 rounded-btn bg-danger-tint px-3 py-2.5 text-[13px] text-danger-deep"
        >
          {describeError(book.error)}
        </p>
      ) : null}
      <div className="mt-6 flex gap-2">
        <Button type="button" variant="outline" size="lg" onClick={onBack}>
          <ChevronLeft /> Back
        </Button>
        <Button
          size="lg"
          className="flex-1"
          disabled={!selected || book.isPending}
          onClick={() => book.mutate()}
        >
          {book.isPending ? <Loader2 className="animate-spin" /> : null}
          Confirm booking
        </Button>
      </div>
    </section>
  )
}
