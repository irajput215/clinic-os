/**
 * The patient fields, shared by the create dialog and the detail page's edit form.
 *
 * Must be rendered inside a react-hook-form `<Form {...form}>` provider: it reads the form
 * context rather than taking a `control` prop, so both callers get exactly the same fields,
 * labels and messages. Every input is labelled and every required field is marked in the
 * label as well as with `required`, which browsers and screen readers announce.
 *
 * Identifier fields (Medicare, IHI) are absent by design: the API neither exposes nor
 * accepts them in this slice.
 */

import { useFormContext } from "react-hook-form"

import {
  FormControl,
  FormDescription,
  FormField,
  FormItem,
  FormLabel,
  FormMessage,
} from "@/components/ui/form"
import { Input } from "@/components/ui/input"
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select"
import { SEX_AT_BIRTH_OPTIONS } from "@/lib/patients"
import type { PatientFormValues } from "./patientForm"

/**
 * Radix select items cannot carry an empty string value, so "no sex recorded" — which the
 * API stores as `null` — needs a sentinel that is mapped back to `""` on change.
 */
const NOT_RECORDED = "not-recorded"

const RequiredMark = () => (
  <span aria-hidden="true" className="text-destructive">
    *
  </span>
)

export function PatientFormFields() {
  const form = useFormContext<PatientFormValues>()

  return (
    <div className="grid gap-4 sm:grid-cols-2">
      <FormField
        control={form.control}
        name="given_name"
        render={({ field }) => (
          <FormItem>
            <FormLabel>
              Given name <RequiredMark />
            </FormLabel>
            <FormControl>
              <Input
                data-testid="patient-given-name-input"
                autoComplete="off"
                required
                {...field}
              />
            </FormControl>
            <FormMessage className="text-xs" />
          </FormItem>
        )}
      />

      <FormField
        control={form.control}
        name="family_name"
        render={({ field }) => (
          <FormItem>
            <FormLabel>
              Family name <RequiredMark />
            </FormLabel>
            <FormControl>
              <Input
                data-testid="patient-family-name-input"
                autoComplete="off"
                required
                {...field}
              />
            </FormControl>
            <FormMessage className="text-xs" />
          </FormItem>
        )}
      />

      <FormField
        control={form.control}
        name="preferred_name"
        render={({ field }) => (
          <FormItem>
            <FormLabel>Preferred name</FormLabel>
            <FormControl>
              <Input
                data-testid="patient-preferred-name-input"
                autoComplete="off"
                {...field}
              />
            </FormControl>
            <FormMessage className="text-xs" />
          </FormItem>
        )}
      />

      <FormField
        control={form.control}
        name="date_of_birth"
        render={({ field }) => (
          <FormItem>
            <FormLabel>
              Date of birth <RequiredMark />
            </FormLabel>
            <FormControl>
              <Input
                data-testid="patient-date-of-birth-input"
                type="date"
                required
                {...field}
              />
            </FormControl>
            <FormMessage className="text-xs" />
          </FormItem>
        )}
      />

      <FormField
        control={form.control}
        name="sex_at_birth"
        render={({ field }) => (
          <FormItem>
            <FormLabel>Sex at birth</FormLabel>
            <Select
              value={field.value === "" ? NOT_RECORDED : field.value}
              onValueChange={(value) =>
                field.onChange(value === NOT_RECORDED ? "" : value)
              }
            >
              <FormControl>
                <SelectTrigger
                  data-testid="patient-sex-at-birth-select"
                  className="w-full"
                >
                  <SelectValue placeholder="Not recorded" />
                </SelectTrigger>
              </FormControl>
              <SelectContent>
                <SelectItem value={NOT_RECORDED}>Not recorded</SelectItem>
                {SEX_AT_BIRTH_OPTIONS.map((option) => (
                  <SelectItem key={option.value} value={option.value}>
                    {option.label}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
            <FormMessage className="text-xs" />
          </FormItem>
        )}
      />

      <FormField
        control={form.control}
        name="gender_identity"
        render={({ field }) => (
          <FormItem>
            <FormLabel>Gender identity</FormLabel>
            <FormControl>
              <Input
                data-testid="patient-gender-identity-input"
                autoComplete="off"
                {...field}
              />
            </FormControl>
            <FormMessage className="text-xs" />
          </FormItem>
        )}
      />

      <FormField
        control={form.control}
        name="phone"
        render={({ field }) => (
          <FormItem>
            <FormLabel>Phone</FormLabel>
            <FormControl>
              <Input
                data-testid="patient-phone-input"
                type="tel"
                autoComplete="off"
                {...field}
              />
            </FormControl>
            <FormMessage className="text-xs" />
          </FormItem>
        )}
      />

      <FormField
        control={form.control}
        name="email"
        render={({ field }) => (
          <FormItem>
            <FormLabel>Email</FormLabel>
            <FormControl>
              <Input
                data-testid="patient-email-input"
                type="email"
                autoComplete="off"
                {...field}
              />
            </FormControl>
            <FormMessage className="text-xs" />
          </FormItem>
        )}
      />

      <FormField
        control={form.control}
        name="address_line"
        render={({ field }) => (
          <FormItem className="sm:col-span-2">
            <FormLabel>Address</FormLabel>
            <FormControl>
              <Input
                data-testid="patient-address-input"
                autoComplete="off"
                {...field}
              />
            </FormControl>
            <FormMessage className="text-xs" />
          </FormItem>
        )}
      />

      <FormField
        control={form.control}
        name="suburb"
        render={({ field }) => (
          <FormItem>
            <FormLabel>Suburb</FormLabel>
            <FormControl>
              <Input
                data-testid="patient-suburb-input"
                autoComplete="off"
                {...field}
              />
            </FormControl>
            <FormMessage className="text-xs" />
          </FormItem>
        )}
      />

      <FormField
        control={form.control}
        name="state"
        render={({ field }) => (
          <FormItem>
            <FormLabel>State</FormLabel>
            <FormControl>
              <Input
                data-testid="patient-state-input"
                autoComplete="off"
                {...field}
              />
            </FormControl>
            <FormMessage className="text-xs" />
          </FormItem>
        )}
      />

      <FormField
        control={form.control}
        name="postcode"
        render={({ field }) => (
          <FormItem>
            <FormLabel>Postcode</FormLabel>
            <FormControl>
              <Input
                data-testid="patient-postcode-input"
                autoComplete="off"
                {...field}
              />
            </FormControl>
            <FormMessage className="text-xs" />
          </FormItem>
        )}
      />

      <FormField
        control={form.control}
        name="deceased_at"
        render={({ field }) => (
          <FormItem className="sm:col-span-2">
            <FormLabel>Date of death</FormLabel>
            <FormControl>
              <Input
                data-testid="patient-deceased-at-input"
                type="date"
                {...field}
              />
            </FormControl>
            <FormDescription className="text-xs">
              Leave blank while the patient is living.
            </FormDescription>
            <FormMessage className="text-xs" />
          </FormItem>
        )}
      />
    </div>
  )
}

export default PatientFormFields
