import { zodResolver } from "@hookform/resolvers/zod"
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query"
import { Check, ChevronLeft, Loader2 } from "lucide-react"
import { useMemo, useState } from "react"
import { useForm } from "react-hook-form"
import type {
  IntakeApplicationIn,
  IntakeForm,
  OwnPharmacy,
  SafetyAnswers,
} from "@/client/types.gen"
import { Button } from "@/components/ui/button"
import { bookingRepo } from "@/data/booking"
import {
  CANNABIS_DURATIONS,
  CANNABIS_FORMS,
  CONDITIONS,
  intakeFormQuery,
} from "@/data/intake"
import {
  APPOINTMENT_TYPES,
  type AppointmentType,
  type PublicSlot,
} from "@/data/types"
import { Field, FormAlert, Mono } from "@/design/primitives"
import { clinicDateOf } from "@/lib/clinic-time"
import { focusFirstError } from "@/lib/form"
import {
  clinicToday,
  formatDate,
  formatLongDay,
  formatTime,
} from "@/lib/format"
import {
  describeError,
  httpStatus,
  refusalCode,
  retryTransient,
} from "@/lib/http"
import { cn } from "@/lib/utils"
import { z } from "@/lib/zod"
import { BrandMark } from "@/shell/BrandMark"

/**
 * The public application (docs3 feature 03; Platform Manual §5.1): about you, health screen, cannabis
 * history, consents, pharmacy and a signed declaration, then a time. Everything is sent in one request
 * with the booking, so the clinic reviews the application with its held booking (Patients > Online
 * applications). Answers stay in memory only: never in the URL, never in browser storage. No product
 * or brand name appears anywhere on this page.
 */
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

const STATES = ["ACT", "NSW", "NT", "QLD", "SA", "TAS", "VIC", "WA"] as const

const details = z.object({
  given_name: z.string().trim().min(1, "Enter your given name.").max(100),
  family_name: z.string().trim().min(1, "Enter your family name.").max(100),
  date_of_birth: z
    .string()
    .regex(/^\d{4}-\d{2}-\d{2}$/, "Enter your date of birth.")
    .refine(
      (v) =>
        v <=
        `${Number(clinicToday().slice(0, 4)) - 18}${clinicToday().slice(4)}`,
      "You need to be 18 or over to apply online.",
    ),
  sex_at_birth: z.enum(["FEMALE", "MALE", "INTERSEX"], {
    message: "Choose one.",
  }),
  email: z.email("Enter a valid email."),
  phone: z
    .string()
    .trim()
    .regex(
      /^(\+?61|0)4\d{2}\s?\d{3}\s?\d{3}$/,
      "Enter an Australian mobile number.",
    ),
  address_line: z.string().trim().min(1, "Enter your street address.").max(255),
  suburb: z.string().trim().min(1, "Enter your suburb.").max(255),
  state: z.enum(STATES, { message: "Choose a state." }),
  postcode: z.string().regex(/^\d{4}$/, "Use a 4-digit postcode."),
})
type Details = z.infer<typeof details>

type Step =
  | "visit"
  | "about"
  | "health"
  | "history"
  | "consents"
  | "pharmacy"
  | "declaration"
  | "time"
  | "done"

const STEPS: Array<[Step, string]> = [
  ["visit", "Visit"],
  ["about", "About you"],
  ["health", "Health"],
  ["history", "History"],
  ["consents", "Consents"],
  ["pharmacy", "Pharmacy"],
  ["declaration", "Declaration"],
  ["time", "Time"],
]

interface Health {
  primary_condition: keyof typeof CONDITIONS | ""
  other_conditions: string
  current_medicines: string
  safety: Partial<SafetyAnswers>
  tried_conventional: boolean | null
  conventional_detail: string
}

interface History {
  cannabis_used_before: boolean | null
  cannabis_forms: Array<keyof typeof CANNABIS_FORMS>
  cannabis_duration: keyof typeof CANNABIS_DURATIONS | ""
  side_effects: string
  what_helped: string
}

const SAFETY_QUESTIONS: Array<[keyof SafetyAnswers, string]> = [
  [
    "psychosis_history",
    "Have you or a close family member had psychosis or schizophrenia?",
  ],
  [
    "pregnant_or_breastfeeding",
    "Are you pregnant, planning pregnancy or breastfeeding?",
  ],
  ["heart_condition", "Do you have a heart condition?"],
  [
    "substance_dependence",
    "Have you had a dependence on alcohol or other substances?",
  ],
]

const slotsQuery = (clinicSlug: string, visit: AppointmentType) => ({
  queryKey: ["public-slots", clinicSlug, visit],
  queryFn: () => bookingRepo.slots(clinicSlug, visit),
  staleTime: 30_000,
})

const heading = (text: string) => (
  <h1 className="font-serif text-[26px] font-medium">{text}</h1>
)

function YesNo({
  name,
  legend,
  value,
  onChange,
  error,
}: {
  name: string
  legend: string
  value: boolean | null | undefined
  onChange: (v: boolean) => void
  error?: string
}) {
  return (
    <fieldset>
      <legend className="field-label">{legend}</legend>
      <div className="flex gap-2">
        {([true, false] as const).map((v) => (
          <label
            key={String(v)}
            className={cn(
              "flex min-h-11 cursor-pointer items-center gap-2 rounded-btn border px-5 py-2 text-sm",
              value === v
                ? "border-clay bg-clay-tint text-clay-deep"
                : "border-line bg-paper",
            )}
          >
            <input
              type="radio"
              name={name}
              className="sr-only"
              checked={value === v}
              onChange={() => onChange(v)}
            />
            {v ? "Yes" : "No"}
          </label>
        ))}
      </div>
      {error ? (
        <p className="mt-1 text-xs text-danger" role="alert">
          {error}
        </p>
      ) : null}
    </fieldset>
  )
}

function StepButtons({
  onBack,
  next = "Continue",
  disabled,
}: {
  onBack: () => void
  next?: string
  disabled?: boolean
}) {
  return (
    <div className="mt-6 flex gap-2">
      <Button type="button" variant="outline" size="lg" onClick={onBack}>
        <ChevronLeft /> Back
      </Button>
      <Button type="submit" size="lg" className="flex-1" disabled={disabled}>
        {next}
      </Button>
    </div>
  )
}

export function BookingPage({ clinicSlug }: { clinicSlug: string }) {
  const [step, setStep] = useState<Step>("visit")
  const [visit, setVisit] = useState<AppointmentType>("NURSE_TRIAGE")
  // The clinic's PUBLIC display name, as its owner set it (never its legal name). Asked with the
  // slots, in parallel.
  const clinic = useQuery({
    queryKey: ["public-clinic", clinicSlug],
    queryFn: () => bookingRepo.clinic(clinicSlug),
    staleTime: 5 * 60_000,
    retry: retryTransient,
  })
  // Asked on arrival, so an unknown or closed clinic says so before anyone fills in the form, and
  // the first visit type's times are ready by the time the patient reaches them.
  const opening = useQuery(slotsQuery(clinicSlug, visit))
  const form = useQuery({
    ...intakeFormQuery(clinicSlug),
    retry: retryTransient,
  })
  const unavailable =
    httpStatus(opening.error) === 404 || httpStatus(clinic.error) === 404
  const [info, setInfo] = useState<Details | null>(null)
  const [health, setHealth] = useState<Health>({
    primary_condition: "",
    other_conditions: "",
    current_medicines: "",
    safety: {},
    tried_conventional: null,
    conventional_detail: "",
  })
  const [history, setHistory] = useState<History>({
    cannabis_used_before: null,
    cannabis_forms: [],
    cannabis_duration: "",
    side_effects: "",
    what_helped: "",
  })
  const [agreed, setAgreed] = useState<Record<string, boolean>>({})
  const [pharmacyId, setPharmacyId] = useState<string | "own" | "">("")
  const [own, setOwn] = useState<OwnPharmacy>({
    name: "",
    suburb: "",
    address: "",
    email: "",
    phone: "",
  })
  const [declaration, setDeclaration] = useState("")
  const [slot, setSlot] = useState<PublicSlot | null>(null)
  const [reference, setReference] = useState<string | null>(null)

  const index = STEPS.findIndex(([s]) => s === step)
  const application: IntakeApplicationIn | null =
    info && form.data
      ? {
          sex_at_birth: info.sex_at_birth,
          address_line: info.address_line,
          suburb: info.suburb,
          state: info.state,
          postcode: info.postcode,
          primary_condition: health.primary_condition || "OTHER",
          other_conditions: health.other_conditions
            .split(",")
            .map((c) => c.trim())
            .filter(Boolean)
            .slice(0, 8),
          current_medicines: health.current_medicines.trim(),
          safety: health.safety as SafetyAnswers,
          tried_conventional: health.tried_conventional === true,
          conventional_detail: health.conventional_detail.trim(),
          cannabis_used_before: history.cannabis_used_before === true,
          cannabis_forms: history.cannabis_used_before
            ? history.cannabis_forms
            : [],
          cannabis_duration:
            history.cannabis_used_before && history.cannabis_duration
              ? history.cannabis_duration
              : null,
          side_effects: history.side_effects.trim(),
          what_helped: history.what_helped.trim(),
          consents: form.data.consents.map((c) => ({
            kind: c.kind as "PRIVACY" | "TELEHEALTH" | "TREATMENT",
            version: c.version,
          })),
          pharmacy_id: pharmacyId && pharmacyId !== "own" ? pharmacyId : null,
          own_pharmacy: pharmacyId === "own" ? own : null,
          declaration_name: declaration.trim(),
        }
      : null

  return (
    <div className="backdrop-pattern min-h-dvh px-4 py-8 sm:py-14">
      <div className="mx-auto w-full max-w-[640px]">
        <div className="mb-6 flex items-center gap-3">
          <BrandMark size={36} />
          <div>
            <div
              className="font-serif text-xl font-semibold"
              data-testid="booking-clinic"
            >
              {unavailable ? (
                "Online booking"
              ) : clinic.data ? (
                clinic.data.display_name
              ) : clinic.isPending ? (
                <span
                  className="block h-7 w-48 max-w-full animate-pulse rounded bg-fill"
                  aria-hidden="true"
                />
              ) : (
                "Online booking"
              )}
            </div>
            <div className="text-xs tracking-[0.04em] text-stone uppercase">
              Apply and book
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
              className="mb-6 flex flex-wrap items-center gap-x-1.5 gap-y-2 text-xs font-semibold tracking-[0.04em] uppercase"
              aria-label="Progress"
            >
              {STEPS.map(([key, label], i) => (
                <li key={key} className="flex items-center gap-1.5">
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
                    // Only the current step is named, so the row fits the card on a phone.
                    className={cn(
                      "whitespace-nowrap",
                      i === index ? "text-ink" : "sr-only",
                    )}
                  >
                    {label}
                  </span>
                </li>
              ))}
            </ol>
          ) : null}

          {!unavailable && step === "visit" ? (
            <section>
              {heading("What kind of visit?")}
              <p className="mt-1 text-sm text-stone">
                Most new patients start with a free nurse triage. The
                application takes about two minutes.
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
                onClick={() => setStep("about")}
              >
                Continue
              </Button>
            </section>
          ) : null}

          {step === "about" ? (
            <AboutStep
              initial={info}
              onBack={() => setStep("visit")}
              onNext={(d) => {
                setInfo(d)
                setStep("health")
              }}
            />
          ) : null}

          {step === "health" ? (
            <HealthStep
              value={health}
              onChange={setHealth}
              onBack={() => setStep("about")}
              onNext={() => setStep("history")}
            />
          ) : null}

          {step === "history" ? (
            <HistoryStep
              value={history}
              onChange={setHistory}
              onBack={() => setStep("health")}
              onNext={() => setStep("consents")}
            />
          ) : null}

          {step === "consents" ? (
            <ConsentsStep
              form={form.data}
              error={form.error}
              agreed={agreed}
              onChange={setAgreed}
              onBack={() => setStep("history")}
              onNext={() => setStep("pharmacy")}
            />
          ) : null}

          {step === "pharmacy" ? (
            <PharmacyStep
              partners={form.data?.partner_pharmacies ?? []}
              choice={pharmacyId}
              onChoice={setPharmacyId}
              own={own}
              onOwn={setOwn}
              onBack={() => setStep("consents")}
              onNext={() => setStep("declaration")}
            />
          ) : null}

          {step === "declaration" && info ? (
            <DeclarationStep
              fullName={`${info.given_name} ${info.family_name}`}
              value={declaration}
              onChange={setDeclaration}
              onBack={() => setStep("pharmacy")}
              onNext={() => setStep("time")}
            />
          ) : null}

          {step === "time" && info && application ? (
            <TimeStep
              clinicSlug={clinicSlug}
              visit={visit}
              selected={slot}
              onSelect={setSlot}
              onBack={() => setStep("declaration")}
              onBooked={(ref) => {
                setReference(ref)
                setStep("done")
              }}
              info={info}
              application={application}
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
                The clinic reviews your application before the appointment and
                will contact you at {info.email} if anything changes.
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

function AboutStep({
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
      given_name: "",
      family_name: "",
      date_of_birth: "",
      email: "",
      phone: "",
      address_line: "",
      suburb: "",
      postcode: "",
    },
  })
  const { errors } = form.formState
  const input = (
    name: keyof Details,
    id: string,
    props: React.InputHTMLAttributes<HTMLInputElement> = {},
  ) => (
    <input
      id={id}
      className="field-input"
      aria-invalid={errors[name] ? "true" : undefined}
      {...props}
      {...form.register(name)}
    />
  )
  return (
    <form onSubmit={form.handleSubmit(onNext, focusFirstError)} noValidate>
      {heading("A little about you")}
      <p className="mt-1 text-sm text-stone">
        As it appears on your Medicare card. Your details are stored in
        Australia. You need to be 18 or over to apply online.
      </p>
      <div className="mt-5 grid gap-4 sm:grid-cols-2">
        <Field
          label="Given name"
          htmlFor="bk-given"
          error={errors.given_name?.message}
        >
          {input("given_name", "bk-given", { autoComplete: "given-name" })}
        </Field>
        <Field
          label="Family name"
          htmlFor="bk-family"
          error={errors.family_name?.message}
        >
          {input("family_name", "bk-family", { autoComplete: "family-name" })}
        </Field>
        <Field
          label="Date of birth"
          htmlFor="bk-dob"
          error={errors.date_of_birth?.message}
        >
          {input("date_of_birth", "bk-dob", {
            type: "date",
            autoComplete: "bday",
          })}
        </Field>
        <Field
          label="Sex"
          htmlFor="bk-sex"
          error={errors.sex_at_birth?.message}
        >
          <select
            id="bk-sex"
            className="field-input"
            {...form.register("sex_at_birth")}
          >
            <option value="">Choose…</option>
            <option value="FEMALE">Female</option>
            <option value="MALE">Male</option>
            <option value="INTERSEX">Intersex</option>
          </select>
        </Field>
        <Field label="Mobile" htmlFor="bk-phone" error={errors.phone?.message}>
          {input("phone", "bk-phone", {
            type: "tel",
            autoComplete: "tel",
            placeholder: "04xx xxx xxx",
          })}
        </Field>
        <Field label="Email" htmlFor="bk-email" error={errors.email?.message}>
          {input("email", "bk-email", { type: "email", autoComplete: "email" })}
        </Field>
        <Field
          label="Street address"
          htmlFor="bk-address"
          error={errors.address_line?.message}
          className="sm:col-span-2"
        >
          {input("address_line", "bk-address", {
            autoComplete: "address-line1",
            placeholder: "14 Vulture St",
          })}
        </Field>
        <Field
          label="Suburb"
          htmlFor="bk-suburb"
          error={errors.suburb?.message}
        >
          {input("suburb", "bk-suburb", { autoComplete: "address-level2" })}
        </Field>
        <div className="grid grid-cols-2 gap-4">
          <Field label="State" htmlFor="bk-state" error={errors.state?.message}>
            <select
              id="bk-state"
              className="field-input"
              {...form.register("state")}
            >
              <option value="">-</option>
              {STATES.map((s) => (
                <option key={s} value={s}>
                  {s}
                </option>
              ))}
            </select>
          </Field>
          <Field
            label="Postcode"
            htmlFor="bk-postcode"
            error={errors.postcode?.message}
          >
            {input("postcode", "bk-postcode", {
              inputMode: "numeric",
              autoComplete: "postal-code",
            })}
          </Field>
        </div>
      </div>
      <StepButtons onBack={onBack} />
    </form>
  )
}

function HealthStep({
  value,
  onChange,
  onBack,
  onNext,
}: {
  value: Health
  onChange: (v: Health) => void
  onBack: () => void
  onNext: () => void
}) {
  const [tried, setTried] = useState(false)
  const set = (patch: Partial<Health>) => onChange({ ...value, ...patch })
  const missing = {
    condition: !value.primary_condition,
    safety: SAFETY_QUESTIONS.some(([k]) => value.safety[k] === undefined),
    conventional: value.tried_conventional === null,
  }
  return (
    <form
      noValidate
      onSubmit={(e) => {
        e.preventDefault()
        setTried(true)
        if (!Object.values(missing).some(Boolean)) onNext()
      }}
    >
      {heading("Your health")}
      <p className="mt-1 text-sm text-stone">
        For the doctor. A "yes" below doesn't stop you applying; it tells the
        doctor what to talk about.
      </p>
      <div className="mt-5 grid gap-4">
        <Field
          label="What would you like help with?"
          htmlFor="bk-condition"
          error={tried && missing.condition ? "Choose one." : undefined}
        >
          <select
            id="bk-condition"
            className="field-input"
            value={value.primary_condition}
            onChange={(e) =>
              set({
                primary_condition: e.target
                  .value as Health["primary_condition"],
              })
            }
          >
            <option value="">Choose…</option>
            {Object.entries(CONDITIONS).map(([k, label]) => (
              <option key={k} value={k}>
                {label}
              </option>
            ))}
          </select>
        </Field>
        <Field
          label="Any other conditions?"
          htmlFor="bk-other"
          hint="Optional. Separate them with commas."
        >
          <input
            id="bk-other"
            className="field-input"
            value={value.other_conditions}
            onChange={(e) => set({ other_conditions: e.target.value })}
          />
        </Field>
        <Field label="Medicines you take now" htmlFor="bk-meds" hint="Optional">
          <textarea
            id="bk-meds"
            className="field-input min-h-16"
            maxLength={500}
            value={value.current_medicines}
            onChange={(e) => set({ current_medicines: e.target.value })}
          />
        </Field>
        {SAFETY_QUESTIONS.map(([key, question]) => (
          <YesNo
            key={key}
            name={`bk-${key}`}
            legend={question}
            value={value.safety[key]}
            onChange={(v) => set({ safety: { ...value.safety, [key]: v } })}
            error={
              tried && value.safety[key] === undefined
                ? "Choose one."
                : undefined
            }
          />
        ))}
        <YesNo
          name="bk-tried"
          legend="Have you tried standard treatments for this?"
          value={value.tried_conventional}
          onChange={(v) => set({ tried_conventional: v })}
          error={tried && missing.conventional ? "Choose one." : undefined}
        />
        {value.tried_conventional ? (
          <Field label="What did you try, and for how long?" htmlFor="bk-conv">
            <input
              id="bk-conv"
              className="field-input"
              maxLength={500}
              value={value.conventional_detail}
              onChange={(e) => set({ conventional_detail: e.target.value })}
            />
          </Field>
        ) : value.tried_conventional === false ? (
          <p className="rounded-btn bg-info-tint px-3 py-2.5 text-[13px] text-info-deep">
            That's fine. The clinician will usually discuss standard options
            with you first.
          </p>
        ) : null}
      </div>
      <StepButtons onBack={onBack} />
    </form>
  )
}

function HistoryStep({
  value,
  onChange,
  onBack,
  onNext,
}: {
  value: History
  onChange: (v: History) => void
  onBack: () => void
  onNext: () => void
}) {
  const [tried, setTried] = useState(false)
  const set = (patch: Partial<History>) => onChange({ ...value, ...patch })
  return (
    <form
      noValidate
      onSubmit={(e) => {
        e.preventDefault()
        setTried(true)
        if (value.cannabis_used_before !== null) onNext()
      }}
    >
      {heading("Medicinal cannabis history")}
      <p className="mt-1 text-sm text-stone">
        Honest answers help the doctor. None of this is shared outside the
        clinic.
      </p>
      <div className="mt-5 grid gap-4">
        <YesNo
          name="bk-used"
          legend="Have you used medicinal cannabis before?"
          value={value.cannabis_used_before}
          onChange={(v) => set({ cannabis_used_before: v })}
          error={
            tried && value.cannabis_used_before === null
              ? "Choose one."
              : undefined
          }
        />
        {value.cannabis_used_before ? (
          <>
            <fieldset>
              <legend className="field-label">Which forms?</legend>
              <div className="flex flex-wrap gap-2">
                {Object.entries(CANNABIS_FORMS).map(([k, label]) => {
                  const on = value.cannabis_forms.includes(
                    k as keyof typeof CANNABIS_FORMS,
                  )
                  return (
                    <label
                      key={k}
                      className={cn(
                        "flex min-h-11 cursor-pointer items-center gap-2 rounded-btn border px-4 py-2 text-sm",
                        on
                          ? "border-clay bg-clay-tint text-clay-deep"
                          : "border-line bg-paper",
                      )}
                    >
                      <input
                        type="checkbox"
                        className="sr-only"
                        checked={on}
                        onChange={() =>
                          set({
                            cannabis_forms: on
                              ? value.cannabis_forms.filter((f) => f !== k)
                              : [
                                  ...value.cannabis_forms,
                                  k as keyof typeof CANNABIS_FORMS,
                                ],
                          })
                        }
                      />
                      {label}
                    </label>
                  )
                })}
              </div>
            </fieldset>
            <Field label="For how long?" htmlFor="bk-duration">
              <select
                id="bk-duration"
                className="field-input"
                value={value.cannabis_duration}
                onChange={(e) =>
                  set({
                    cannabis_duration: e.target
                      .value as History["cannabis_duration"],
                  })
                }
              >
                <option value="">Choose…</option>
                {Object.entries(CANNABIS_DURATIONS).map(([k, label]) => (
                  <option key={k} value={k}>
                    {label}
                  </option>
                ))}
              </select>
            </Field>
            <Field label="Any side effects?" htmlFor="bk-side" hint="Optional">
              <input
                id="bk-side"
                className="field-input"
                maxLength={300}
                value={value.side_effects}
                onChange={(e) => set({ side_effects: e.target.value })}
              />
            </Field>
            <Field
              label="What felt effective?"
              htmlFor="bk-helped"
              hint="Optional"
            >
              <input
                id="bk-helped"
                className="field-input"
                maxLength={300}
                value={value.what_helped}
                onChange={(e) => set({ what_helped: e.target.value })}
              />
            </Field>
          </>
        ) : null}
      </div>
      <StepButtons onBack={onBack} />
    </form>
  )
}

function ConsentsStep({
  form,
  error,
  agreed,
  onChange,
  onBack,
  onNext,
}: {
  form: IntakeForm | undefined
  error: unknown
  agreed: Record<string, boolean>
  onChange: (v: Record<string, boolean>) => void
  onBack: () => void
  onNext: () => void
}) {
  const [tried, setTried] = useState(false)
  const all = form ? form.consents.every((c) => agreed[c.kind]) : false
  return (
    <form
      noValidate
      onSubmit={(e) => {
        e.preventDefault()
        setTried(true)
        if (all) onNext()
      }}
    >
      {heading("Consents")}
      <p className="mt-1 text-sm text-stone">
        Please read each one. You agree to this exact version, and the clinic
        keeps a record of it.
      </p>
      {error ? <FormAlert>{describeError(error)}</FormAlert> : null}
      <div className="mt-5 grid gap-4">
        {(form?.consents ?? []).map((c) => (
          <section
            key={c.kind}
            className="rounded-inner border border-line p-4"
          >
            <h2 className="text-[15px] font-semibold">{c.title}</h2>
            <p className="mt-1 max-h-40 overflow-y-auto text-[13px] text-stone">
              {c.body}
            </p>
            <label className="mt-3 flex min-h-11 items-start gap-2.5 py-1 text-[13px]">
              <input
                type="checkbox"
                className="mt-0.5 size-4 accent-[var(--color-clay)]"
                checked={Boolean(agreed[c.kind])}
                onChange={(e) =>
                  onChange({ ...agreed, [c.kind]: e.target.checked })
                }
              />
              <span>
                I have read and agree to the {c.title.toLowerCase()} (version{" "}
                {c.version}).
              </span>
            </label>
          </section>
        ))}
        {tried && !all ? (
          <p className="text-xs text-danger" role="alert">
            Please agree to each consent to continue.
          </p>
        ) : null}
      </div>
      <StepButtons onBack={onBack} disabled={!form} />
    </form>
  )
}

function PharmacyStep({
  partners,
  choice,
  onChoice,
  own,
  onOwn,
  onBack,
  onNext,
}: {
  partners: Array<{ id: string; name: string; suburb: string }>
  choice: string
  onChoice: (v: string) => void
  own: OwnPharmacy
  onOwn: (v: OwnPharmacy) => void
  onBack: () => void
  onNext: () => void
}) {
  const [tried, setTried] = useState(false)
  const ownComplete =
    own.name.trim() &&
    own.suburb.trim() &&
    own.address.trim() &&
    /^\S+@\S+\.\S+$/.test(own.email) &&
    own.phone.trim().length >= 6
  const ok = choice !== "" && (choice !== "own" || ownComplete)
  const setOwnField = (key: keyof OwnPharmacy, v: string) =>
    onOwn({ ...own, [key]: v })
  const option = (value: string, label: React.ReactNode) => (
    <label
      key={value}
      className={cn(
        "flex min-h-11 cursor-pointer items-center gap-3 rounded-inner border px-4 py-3 text-sm",
        choice === value ? "border-clay bg-clay-tint" : "border-line bg-paper",
      )}
    >
      <input
        type="radio"
        name="bk-pharmacy"
        className="size-4 accent-[var(--color-clay)]"
        checked={choice === value}
        onChange={() => onChoice(value)}
      />
      {label}
    </label>
  )
  return (
    <form
      noValidate
      onSubmit={(e) => {
        e.preventDefault()
        setTried(true)
        if (ok) onNext()
      }}
    >
      {heading("Your pharmacy")}
      <p className="mt-1 text-sm text-stone">
        Where your scripts are sent. The clinic's partner pharmacies are listed
        first.
      </p>
      <fieldset className="mt-5 grid gap-2">
        <legend className="sr-only">Choose a pharmacy</legend>
        {partners.map((p) =>
          option(
            p.id,
            <span>
              <span className="font-medium">{p.name}</span>{" "}
              <span className="text-stone">· {p.suburb}</span>
            </span>,
          ),
        )}
        {option("own", <span className="font-medium">My own pharmacy</span>)}
      </fieldset>
      {choice === "own" ? (
        <div className="mt-4 grid gap-4 sm:grid-cols-2">
          <p className="rounded-btn bg-warn-tint px-3 py-2.5 text-[13px] text-warn-deep sm:col-span-2">
            Your own pharmacy may not stock what the doctor prescribes. Give its
            details in full so scripts reach it.
          </p>
          {(
            [
              ["name", "Pharmacy name"],
              ["suburb", "Suburb"],
              ["address", "Address"],
              ["email", "Email"],
              ["phone", "Phone"],
              ["provider_number", "Provider number (optional)"],
            ] as Array<[keyof OwnPharmacy, string]>
          ).map(([key, label]) => (
            <Field key={key} label={label} htmlFor={`bk-own-${key}`}>
              <input
                id={`bk-own-${key}`}
                className="field-input"
                type={
                  key === "email" ? "email" : key === "phone" ? "tel" : "text"
                }
                value={own[key] ?? ""}
                onChange={(e) => setOwnField(key, e.target.value)}
              />
            </Field>
          ))}
        </div>
      ) : null}
      {tried && !ok ? (
        <p className="mt-3 text-xs text-danger" role="alert">
          {choice === "own"
            ? "Fill in your pharmacy's name, suburb, address, email and phone."
            : "Choose a pharmacy."}
        </p>
      ) : null}
      <StepButtons onBack={onBack} />
    </form>
  )
}

function DeclarationStep({
  fullName,
  value,
  onChange,
  onBack,
  onNext,
}: {
  fullName: string
  value: string
  onChange: (v: string) => void
  onBack: () => void
  onNext: () => void
}) {
  const [tried, setTried] = useState(false)
  const norm = (s: string) =>
    s.toLowerCase().split(/\s+/).filter(Boolean).join(" ")
  const matches = norm(value) === norm(fullName)
  return (
    <form
      noValidate
      onSubmit={(e) => {
        e.preventDefault()
        setTried(true)
        if (matches) onNext()
      }}
    >
      {heading("Declaration")}
      <p className="mt-1 text-sm text-stone">
        I declare that the information I have given is true and complete, and
        that I am applying for myself.
      </p>
      <div className="mt-5">
        <Field
          label="Type your full name to sign"
          htmlFor="bk-declaration"
          error={
            tried && !matches
              ? "Type your full name exactly as you entered it."
              : undefined
          }
        >
          <input
            id="bk-declaration"
            className="field-input"
            autoComplete="off"
            value={value}
            onChange={(e) => onChange(e.target.value)}
          />
        </Field>
      </div>
      <StepButtons onBack={onBack} next="Choose a time" />
    </form>
  )
}

/** The day strip and time grid's own shape while the times load, so nothing jumps when they arrive. */
function SlotsPending() {
  return (
    <div role="status" aria-busy="true" aria-label="Loading times">
      <div className="mt-5 flex gap-2 overflow-hidden pb-1">
        {Array.from({ length: 6 }, (_, i) => (
          <div
            key={i}
            className="h-[57px] w-[52px] shrink-0 animate-pulse rounded-inner bg-fill/70"
            style={{ animationDelay: `${i * 80}ms` }}
          />
        ))}
      </div>
      <div className="mt-4 grid grid-cols-3 gap-2 sm:grid-cols-4">
        {Array.from({ length: 8 }, (_, i) => (
          <div
            key={i}
            className="h-[54px] animate-pulse rounded-btn bg-fill/70"
            style={{ animationDelay: `${i * 60}ms` }}
          />
        ))}
      </div>
    </div>
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
  application,
}: {
  clinicSlug: string
  visit: AppointmentType
  selected: PublicSlot | null
  onSelect: (s: PublicSlot) => void
  onBack: () => void
  onBooked: (reference: string) => void
  info: Details
  application: IntakeApplicationIn
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
        consent: true,
        application,
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
        <SlotsPending />
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
                    "min-h-11 rounded-btn border px-2 py-2 text-center transition-colors",
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
