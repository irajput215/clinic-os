import { createFileRoute } from "@tanstack/react-router"
import { scriptsQuery } from "@/data/scripts"
import { PageError, PagePending } from "@/design/primitives"
import { ScriptsPage } from "@/features/scripts/ScriptsPage"

export const Route = createFileRoute("/_app/scripts")({
  staticData: { title: "Script queue" },
  loader: ({ context: { queryClient } }) =>
    queryClient.ensureQueryData(scriptsQuery),
  pendingComponent: PagePending,
  errorComponent: PageError,
  component: ScriptsPage,
})
