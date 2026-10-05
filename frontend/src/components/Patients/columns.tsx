import { Link as RouterLink } from "@tanstack/react-router"
import type { ColumnDef } from "@tanstack/react-table"
import { ChevronRight } from "lucide-react"

import type { PatientRead } from "@/client"
import { Badge } from "@/components/ui/badge"
import { formatDateOnly } from "@/lib/date"
import {
  patientFullName,
  patientListName,
  sexAtBirthLabel,
} from "@/lib/patients"

/**
 * The patient list's columns.
 *
 * The name is the link into the record; the actions column repeats it so a keyboard user
 * can reach the detail view from the end of the row too, with an accessible name that says
 * which patient it opens rather than a column of identical "View" links.
 */
export const columns: ColumnDef<PatientRead>[] = [
  {
    accessorKey: "family_name",
    header: "Patient",
    cell: ({ row }) => {
      const patient = row.original
      return (
        <div className="flex flex-col gap-1">
          <RouterLink
            to="/patients/$patientId"
            params={{ patientId: patient.id }}
            className="font-medium underline-offset-4 hover:underline"
          >
            {patientListName(patient)}
          </RouterLink>
          <span className="flex items-center gap-2">
            {patient.preferred_name ? (
              <span className="text-xs text-muted-foreground">
                Known as {patient.preferred_name}
              </span>
            ) : null}
            {patient.deceased_at ? (
              <Badge variant="secondary" className="text-xs">
                Deceased
              </Badge>
            ) : null}
          </span>
        </div>
      )
    },
  },
  {
    accessorKey: "date_of_birth",
    header: "Date of birth",
    cell: ({ row }) =>
      formatDateOnly(row.original.date_of_birth) ?? (
        <span className="text-muted-foreground">—</span>
      ),
  },
  {
    accessorKey: "sex_at_birth",
    header: "Sex at birth",
    cell: ({ row }) =>
      row.original.sex_at_birth ? (
        sexAtBirthLabel(row.original.sex_at_birth)
      ) : (
        <span className="text-muted-foreground">—</span>
      ),
  },
  {
    accessorKey: "suburb",
    header: "Suburb",
    cell: ({ row }) =>
      row.original.suburb ? (
        row.original.suburb
      ) : (
        <span className="text-muted-foreground">—</span>
      ),
  },
  {
    accessorKey: "phone",
    header: "Phone",
    cell: ({ row }) =>
      row.original.phone ? (
        row.original.phone
      ) : (
        <span className="text-muted-foreground">—</span>
      ),
  },
  {
    id: "actions",
    header: () => <span className="sr-only">Actions</span>,
    cell: ({ row }) => (
      <div className="flex justify-end">
        <RouterLink
          to="/patients/$patientId"
          params={{ patientId: row.original.id }}
          aria-label={`View ${patientFullName(row.original)}`}
          className="inline-flex items-center gap-1 text-sm text-muted-foreground underline-offset-4 hover:text-foreground hover:underline"
        >
          View
          <ChevronRight className="size-4" aria-hidden="true" />
        </RouterLink>
      </div>
    ),
  },
]
