/** The settings tabs. Its own module so the route can validate `?tab=` without the page. */
export const SETTINGS_TABS = {
  profile: "Profile",
  password: "Password",
  account: "Account",
  // Offered only to whoever may change the clinic's settings (`tenant:configure`).
  clinic: "Clinic",
  // Practice workflow and record retention (docs3 feature 01); `tenant:configure` too.
  practice: "Practice",
} as const
export type SettingsTab = keyof typeof SETTINGS_TABS
export const SETTINGS_TAB_KEYS = Object.keys(SETTINGS_TABS) as SettingsTab[]
