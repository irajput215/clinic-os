import { createFileRoute, Outlet } from "@tanstack/react-router"

/**
 * The `/patients` subtree: the list at `/patients` and one record at
 * `/patients/$patientId`. The route itself is only an outlet — each page owns its own
 * heading, and the session guard lives on `_layout`.
 */
export const Route = createFileRoute("/_layout/patients")({
  component: PatientsLayout,
})

function PatientsLayout() {
  return <Outlet />
}
