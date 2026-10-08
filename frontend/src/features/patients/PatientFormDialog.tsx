import { zodResolver } from "@hookform/resolvers/zod"
import { useMutation, useQueryClient } from "@tanstack/react-query"
import { useNavigate } from "@tanstack/react-router"
import { Loader2 } from "lucide-react"
import { useEffect } from "react"
import { useForm } from "react-hook-form"
import { toast } from "sonner"
import type { PatientRead } from "@/client/types.gen"
import { Button } from "@/components/ui/button"
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog"
import { createPatient, patientName, updatePatient } from "@/data/patients"
import { Field } from "@/design/primitives"
import { focusFirstError } from "@/lib/form"
import { clinicToday } from "@/lib/format"
import { describeError } from "@/lib/http"
import { z } from "@/lib/zod"

// MIRROR: patients/models.py SEX_AT_BIRTH_VOCABULARY
const SEX_AT_BIRTH = {
  FEMALE: "Female",
  MALE: "Male",
  INTERSEX: "Intersex",
  UNKNOWN: "Not stated",
}
const STATES = ["ACT", "NSW", "NT", "QLD", "SA", "TAS", "VIC", "WA"]

const optional = (max: number) =>
  z
    .string()
    .trim()
    .max(max)
    .transform((v) => (v === "" ? null : v))

const schema = z.object({
  given_name: z.string().trim().min(1, "Enter a given name.").max(255),
  family_name: z.string().trim().min(1, "Enter a family name.").max(255),
  preferred_name: optional(255),
  date_of_birth: z
    .string()
    .regex(/^\d{4}-\d{2}-\d{2}$/, "Enter a date of birth.")
    .refine((v) => v <= clinicToday(), "Date of birth can't be in the future."),
  sex_at_birth: z
    .enum(["", ...Object.keys(SEX_AT_BIRTH)] as [string, ...string[]])
    .transform((v) => (v === "" ? null : v)),
  phone: optional(64).refine(
    (v) => v === null || /^[+\d][\d\s()-]{5,}$/.test(v),
    "Enter a valid phone number.",
  ),
  email: optional(255).refine(
    (v) => v === null || z.email().safeParse(v).success,
    "Enter a valid email.",
  ),
  address_line: optional(255),
  suburb: optional(255),
  state: optional(64),
  postcode: optional(32).refine(
    (v) => v === null || /^\d{4}$/.test(v),
    "Use a 4-digit postcode.",
  ),
})
type FormIn = z.input<typeof schema>
type FormOut = z.output<typeof schema>

const toForm = (p?: PatientRead): FormIn => ({
  given_name: p?.given_name ?? "",
  family_name: p?.family_name ?? "",
  preferred_name: p?.preferred_name ?? "",
  date_of_birth: p?.date_of_birth ?? "",
  sex_at_birth: p?.sex_at_birth ?? "",
  phone: p?.phone ?? "",
  email: p?.email ?? "",
  address_line: p?.address_line ?? "",
  suburb: p?.suburb ?? "",
  state: p?.state ?? "",
  postcode: p?.postcode ?? "",
})

export function PatientFormDialog({
  open,
  onOpenChange,
  patient,
}: {
  open: boolean
  onOpenChange: (open: boolean) => void
  /** Present: edit this patient. Absent: create a new one. */
  patient?: PatientRead
}) {
  const queryClient = useQueryClient()
  const navigate = useNavigate()
  const form = useForm<FormIn, unknown, FormOut>({
    shouldFocusError: false,
    resolver: zodResolver(schema),
    defaultValues: toForm(patient),
  })
  const { errors } = form.formState

  useEffect(() => {
    if (open) form.reset(toForm(patient))
  }, [open, patient, form])

  const save = useMutation({
    mutationFn: (values: FormOut) =>
      patient ? updatePatient(patient.id, values) : createPatient(values),
    onSuccess: async (saved) => {
      queryClient.setQueryData(["patients", "detail", saved.id], saved)
      await queryClient.invalidateQueries({ queryKey: ["patients", "list"] })
      toast.success(
        patient ? "Patient details saved" : `${patientName(saved)} added`,
      )
      onOpenChange(false)
      if (!patient)
        navigate({
          to: "/patients/$patientId",
          params: { patientId: saved.id },
        })
    },
  })

  const input = (
    name: keyof FormIn,
    props: React.InputHTMLAttributes<HTMLInputElement> = {},
  ) => (
    <input
      id={`pt-${name}`}
      className="field-input"
      aria-invalid={errors[name] ? "true" : undefined}
      {...props}
      {...form.register(name)}
    />
  )

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="sm:max-w-[620px]">
        <form
          onSubmit={form.handleSubmit((v) => save.mutate(v), focusFirstError)}
          noValidate
          className="grid gap-4"
        >
          <DialogHeader>
            <DialogTitle>
              {patient ? "Edit patient details" : "Add a patient"}
            </DialogTitle>
            <DialogDescription>
              Identity and contact details. Clinical information is recorded in
              the consult.
            </DialogDescription>
          </DialogHeader>

          <div className="grid gap-4 sm:grid-cols-2">
            <Field
              label="Given name"
              htmlFor="pt-given_name"
              error={errors.given_name?.message}
            >
              {input("given_name", { autoComplete: "off", autoFocus: true })}
            </Field>
            <Field
              label="Family name"
              htmlFor="pt-family_name"
              error={errors.family_name?.message}
            >
              {input("family_name", { autoComplete: "off" })}
            </Field>
            <Field
              label="Preferred name"
              htmlFor="pt-preferred_name"
              hint="Optional"
            >
              {input("preferred_name", { autoComplete: "off" })}
            </Field>
            <Field
              label="Date of birth"
              htmlFor="pt-date_of_birth"
              error={errors.date_of_birth?.message}
            >
              {input("date_of_birth", { type: "date", max: clinicToday() })}
            </Field>
            <Field label="Sex at birth" htmlFor="pt-sex_at_birth">
              <select
                id="pt-sex_at_birth"
                className="field-input"
                {...form.register("sex_at_birth")}
              >
                <option value="">Not recorded</option>
                {Object.entries(SEX_AT_BIRTH).map(([v, label]) => (
                  <option key={v} value={v}>
                    {label}
                  </option>
                ))}
              </select>
            </Field>
            <Field
              label="Mobile"
              htmlFor="pt-phone"
              error={errors.phone?.message}
            >
              {input("phone", { type: "tel", autoComplete: "off" })}
            </Field>
            <Field
              label="Email"
              htmlFor="pt-email"
              error={errors.email?.message}
              className="sm:col-span-2"
            >
              {input("email", { type: "email", autoComplete: "off" })}
            </Field>
            <Field
              label="Street address"
              htmlFor="pt-address_line"
              className="sm:col-span-2"
            >
              {input("address_line", { autoComplete: "off" })}
            </Field>
            <Field label="Suburb" htmlFor="pt-suburb">
              {input("suburb", { autoComplete: "off" })}
            </Field>
            <div className="grid grid-cols-2 gap-4">
              <Field label="State" htmlFor="pt-state">
                <select
                  id="pt-state"
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
                htmlFor="pt-postcode"
                error={errors.postcode?.message}
              >
                {input("postcode", {
                  inputMode: "numeric",
                  autoComplete: "off",
                })}
              </Field>
            </div>
          </div>

          {save.isError ? (
            <p
              role="alert"
              className="rounded-btn bg-danger-tint px-3 py-2.5 text-[13px] text-danger-deep"
            >
              {describeError(save.error)}
            </p>
          ) : null}

          <DialogFooter>
            <Button
              type="button"
              variant="outline"
              onClick={() => onOpenChange(false)}
            >
              Cancel
            </Button>
            <Button type="submit" disabled={save.isPending}>
              {save.isPending ? <Loader2 className="animate-spin" /> : null}
              {patient ? "Save changes" : "Add patient"}
            </Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  )
}
