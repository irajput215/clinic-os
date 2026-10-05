import { zodResolver } from "@hookform/resolvers/zod"
import { useMutation, useQueryClient } from "@tanstack/react-query"
import type { ReactNode } from "react"
import { useState } from "react"
import { useForm } from "react-hook-form"

import { type PatientRead, PatientsService, type PatientUpdate } from "@/client"
import { Button } from "@/components/ui/button"
import {
  Card,
  CardAction,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card"
import { Form } from "@/components/ui/form"
import { LoadingButton } from "@/components/ui/loading-button"
import useCustomToast from "@/hooks/useCustomToast"
import { formatDateOnly, formatTimestamp } from "@/lib/date"
import { displayOrEmpty, EMPTY_VALUE, sexAtBirthLabel } from "@/lib/patients"
import { cn } from "@/lib/utils"
import { handleError } from "@/utils"
import PatientFormFields from "./PatientFormFields"
import {
  formValuesToUpdate,
  type PatientFormValues,
  patientFormSchema,
  patientToFormValues,
} from "./patientForm"

const DetailItem = ({
  label,
  value,
  className,
}: {
  label: string
  value: ReactNode
  className?: string
}) => (
  <div className={cn("flex flex-col gap-1", className)}>
    <dt className="text-xs font-medium text-muted-foreground">{label}</dt>
    <dd className="text-sm break-words">{value}</dd>
  </div>
)

const dateOrEmpty = (value: string | null | undefined) =>
  formatDateOnly(value) ?? EMPTY_VALUE

/**
 * One patient, and the form that edits it.
 *
 * Read and edit share the same card, so entering edit mode does not move the page. `PATCH`
 * receives only the fields the user actually changed (`formValuesToUpdate`); a form with no
 * changes sends nothing and the button stays disabled.
 *
 * Nothing about the patient is logged: a failed save goes to a toast carrying the API's
 * message or a generic one.
 */
export function PatientDetails({ patient }: { patient: PatientRead }) {
  const [editMode, setEditMode] = useState(false)
  const queryClient = useQueryClient()
  const { showSuccessToast, showErrorToast } = useCustomToast()

  const form = useForm<PatientFormValues>({
    resolver: zodResolver(patientFormSchema),
    mode: "onSubmit",
    criteriaMode: "all",
    defaultValues: patientToFormValues(patient),
  })

  const mutation = useMutation({
    mutationFn: (patientUpdate: PatientUpdate) =>
      PatientsService.updatePatient({
        path: { patient_id: patient.id },
        body: patientUpdate,
      }),
    onSuccess: (response) => {
      const updated = response.data
      queryClient.setQueryData(["patients", patient.id], updated)
      queryClient.invalidateQueries({ queryKey: ["patients"] })
      form.reset(patientToFormValues(updated))
      setEditMode(false)
      showSuccessToast("Patient updated successfully")
    },
    onError: handleError.bind(showErrorToast),
  })

  const onSubmit = (values: PatientFormValues) => {
    if (mutation.isPending) return
    const patientUpdate = formValuesToUpdate(values, patient)
    if (patientUpdate === null) {
      setEditMode(false)
      return
    }
    mutation.mutate(patientUpdate)
  }

  const onCancel = () => {
    form.reset(patientToFormValues(patient))
    setEditMode(false)
  }

  if (editMode) {
    return (
      <Card>
        <CardHeader>
          <CardTitle>Edit patient</CardTitle>
          <CardDescription>
            Change what needs correcting. Fields you leave alone are not sent.
          </CardDescription>
        </CardHeader>
        <CardContent>
          <Form {...form}>
            <form
              noValidate
              onSubmit={form.handleSubmit(onSubmit)}
              className="flex flex-col gap-6"
            >
              <PatientFormFields />
              <div className="flex flex-wrap gap-3">
                <LoadingButton
                  type="submit"
                  loading={mutation.isPending}
                  disabled={!form.formState.isDirty}
                >
                  Save changes
                </LoadingButton>
                <Button
                  type="button"
                  variant="outline"
                  onClick={onCancel}
                  disabled={mutation.isPending}
                >
                  Cancel
                </Button>
              </div>
            </form>
          </Form>
        </CardContent>
      </Card>
    )
  }

  return (
    <Card>
      <CardHeader>
        <CardTitle>Patient record</CardTitle>
        <CardDescription>
          Details held for this patient in your organisation.
        </CardDescription>
        <CardAction>
          <Button
            type="button"
            variant="outline"
            size="sm"
            onClick={() => setEditMode(true)}
            data-testid="edit-patient-button"
          >
            Edit
          </Button>
        </CardAction>
      </CardHeader>
      <CardContent>
        <dl className="grid gap-4 sm:grid-cols-2">
          <DetailItem
            label="Given name"
            value={displayOrEmpty(patient.given_name)}
          />
          <DetailItem
            label="Family name"
            value={displayOrEmpty(patient.family_name)}
          />
          <DetailItem
            label="Preferred name"
            value={displayOrEmpty(patient.preferred_name)}
          />
          <DetailItem
            label="Date of birth"
            value={dateOrEmpty(patient.date_of_birth)}
          />
          <DetailItem
            label="Sex at birth"
            value={sexAtBirthLabel(patient.sex_at_birth)}
          />
          <DetailItem
            label="Gender identity"
            value={displayOrEmpty(patient.gender_identity)}
          />
          <DetailItem label="Phone" value={displayOrEmpty(patient.phone)} />
          <DetailItem label="Email" value={displayOrEmpty(patient.email)} />
          <DetailItem
            label="Address"
            value={displayOrEmpty(patient.address_line)}
            className="sm:col-span-2"
          />
          <DetailItem label="Suburb" value={displayOrEmpty(patient.suburb)} />
          <DetailItem label="State" value={displayOrEmpty(patient.state)} />
          <DetailItem
            label="Postcode"
            value={displayOrEmpty(patient.postcode)}
          />
          <DetailItem
            label="Date of death"
            value={dateOrEmpty(patient.deceased_at)}
          />
          <DetailItem
            label="Last updated"
            value={formatTimestamp(patient.updated_at) ?? EMPTY_VALUE}
          />
          <DetailItem
            label="Record created"
            value={formatTimestamp(patient.created_at) ?? EMPTY_VALUE}
          />
        </dl>
      </CardContent>
    </Card>
  )
}

export default PatientDetails
