import { Skeleton } from "@/components/ui/skeleton"
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table"

/**
 * The list while it loads. It renders the real table's header and column count so the
 * content replaces it without the page jumping.
 */
const PendingPatients = () => (
  <Table data-testid="patients-loading">
    <TableHeader>
      <TableRow>
        {[
          "Patient",
          "Date of birth",
          "Sex at birth",
          "Suburb",
          "Phone",
          "Actions",
        ].map((heading) => (
          <TableHead key={heading}>
            {heading === "Actions" ? (
              <span className="sr-only">{heading}</span>
            ) : (
              heading
            )}
          </TableHead>
        ))}
      </TableRow>
    </TableHeader>
    <TableBody>
      {Array.from({ length: 5 }).map((_, index) => (
        <TableRow key={index}>
          <TableCell>
            <Skeleton className="h-4 w-40" />
          </TableCell>
          <TableCell>
            <Skeleton className="h-4 w-24" />
          </TableCell>
          <TableCell>
            <Skeleton className="h-4 w-20" />
          </TableCell>
          <TableCell>
            <Skeleton className="h-4 w-28" />
          </TableCell>
          <TableCell>
            <Skeleton className="h-4 w-28" />
          </TableCell>
          <TableCell>
            <div className="flex justify-end">
              <Skeleton className="h-4 w-12" />
            </div>
          </TableCell>
        </TableRow>
      ))}
    </TableBody>
  </Table>
)

export default PendingPatients
