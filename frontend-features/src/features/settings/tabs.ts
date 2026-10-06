/** The settings tabs. Its own module so the route can validate `?tab=` without the page. */
export const SETTINGS_TABS = {
  profile: "Profile",
  password: "Password",
  account: "Account",
} as const
export type SettingsTab = keyof typeof SETTINGS_TABS
export const SETTINGS_TAB_KEYS = Object.keys(SETTINGS_TABS) as SettingsTab[]
