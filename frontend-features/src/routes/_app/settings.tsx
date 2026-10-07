import { createFileRoute } from "@tanstack/react-router"
import { PageError, PagePending } from "@/design/primitives"
import { SettingsPage } from "@/features/settings/SettingsPage"
import { SETTINGS_TAB_KEYS, type SettingsTab } from "@/features/settings/tabs"
import { oneOf } from "@/lib/search"

export const Route = createFileRoute("/_app/settings")({
  staticData: { title: "Settings" },
  validateSearch: (search: Record<string, unknown>): { tab?: SettingsTab } => ({
    tab: oneOf(SETTINGS_TAB_KEYS, search.tab),
  }),
  pendingComponent: PagePending,
  errorComponent: PageError,
  component: SettingsRoute,
})

function SettingsRoute() {
  const { tab } = Route.useSearch()
  return <SettingsPage tab={tab ?? "profile"} />
}
