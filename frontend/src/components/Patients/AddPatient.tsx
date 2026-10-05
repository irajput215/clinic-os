import { zodResolver } from "@hookform/resolvers/zod"
import { useMutation, useQueryClient } from "@tanstack/react-query"
import { Plus } from "lucide-react"
import { useState } from "react"
import { useForm } from "react-hook-form"

import { type PatientCreate, PatientsService } from "@/client"
import { Button } from "@/components/ui/button"
import {
  Dialog,
  DialogClose,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
  DialogTrigger,
} from "@/components/ui/dialog"
import { Form } from "@/components/ui/form"
import { LoadingButton } from "@/components/ui/loading-button"
import useCustomToast from "@/hooks/useCustomToast"
import { handleError } from "@/utils"
import PatientFormFields from "./PatientFormFields"
import {
  emptyPatientFormValues,
  formValuesToCreate,
  type PatientFormValues,
  patientFormSchema,
} from "./patientForm"

interface AddPatientProps {
  /**
   * The trigger label. The list header and the empty state both offer a way in, and giving
   * them the same name would be ambiguous to a screen reader — and to a test.
   */
  label?: string
}

/**
 * Create a patient, in a dialog, from anywhere that offers the action.
 *
 * `noValidate` plus `mode: "onSubmit"` is deliberate: zod owns validation, not the browser.
 * Nothing about a patient is written to the console — errors go to a toast whose text is
 * the API's own message or a generic one.
 */
export function AddPatient({ label = "Add patient" }: AddPatientProps) {
  const [isOpen, setIsOpen] = useState(false)
  const queryClient = useQueryClient()
  const { showSuccessToast, showErrorToast } = useCustomToast()

  const form = useForm<PatientFormValues>({
    resolver: zodResolver(patientFormSchema),
    mode: "onSubmit",
    criteriaMode: "all",
    defaultValues: emptyPatientFormValues,
  })

  const mutation = useMutation({
    mutationFn: (patient: PatientCreate) =>
      PatientsService.createPatient({ body: patient }),
    onSuccess: () => {
      showSuccessToast("Patient created successfully")
      form.reset(emptyPatientFormValues)
      setIsOpen(false)
    },
    onError: handleError.bind(showErrorToast),
    onSettled: () => {
      queryClient.invalidateQueries({ queryKey: ["patients"] })
    },
  })

  const onSubmit = (values: PatientFormValues) => {
    if (mutation.isPending) return
    mutation.mutate(formValuesToCreate(values))
  }

  const onOpenChange = (open: boolean) => {
    if (mutation.isPending) return
    setIsOpen(open)
    if (!open) {
      // Reopening shows an empty form, not the abandoned half of the last one.
      form.reset(emptyPatientFormValues)
    }
  }

  return (
    <Dialog open={isOpen} onOpenChange={onOpenChange}>
      <DialogTrigger asChild>
        <Button>
          <Plus className="mr-2" />
          {label}
        </Button>
      </DialogTrigger>
      <DialogContent className="max-h-[90vh] overflow-y-auto sm:max-w-2xl">
        <DialogHeader>
          <DialogTitle>Add patient</DialogTitle>
          <DialogDescription>
            Record a patient in your organisation. Given name, family name and
            date of birth are required; the rest can be filled in later.
          </DialogDescription>
        </DialogHeader>
        <Form {...form}>
          <form
            noValidate
            onSubmit={form.handleSubmit(onSubmit)}
            className="flex flex-col gap-4"
          >
            <PatientFormFields />

            <DialogFooter>
              <DialogClose asChild>
                <Button
                  type="button"
                  variant="outline"
                  disabled={mutation.isPending}
                >
                  Cancel
                </Button>
              </DialogClose>
              <LoadingButton type="submit" loading={mutation.isPending}>
                Save
              </LoadingButton>
            </DialogFooter>
          </form>
        </Form>
      </DialogContent>
    </Dialog>
  )
}

export default AddPatient
