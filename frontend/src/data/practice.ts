import { queryOptions } from "@tanstack/react-query"
import { TenantsService } from "@/client"
import type {
  PracticeSettingsRead,
  PracticeSettingsUpdate,
  SetupRead,
} from "@/client/types.gen"

/**
 * Clinic setup (docs3 feature 01): the setup checklist, derived on the server from live data, and the
 * practice settings.
 *
 *   GET   /tenants/current/setup      tenant:configure
 *   GET   /tenants/current/settings   tenant:read (defaults when never saved)
 *   PATCH /tenants/current/settings   tenant:configure, audited
 */
export const setupQuery = queryOptions({
  queryKey: ["practice", "setup"],
  queryFn: async (): Promise<SetupRead> =>
    (await TenantsService.readSetup()).data,
  staleTime: 30_000,
})

export const practiceSettingsQuery = queryOptions({
  queryKey: ["practice", "settings"],
  queryFn: async (): Promise<PracticeSettingsRead> =>
    (await TenantsService.readSettings()).data,
})

export const savePracticeSettings = async (body: PracticeSettingsUpdate) =>
  (await TenantsService.updateSettings({ body })).data
