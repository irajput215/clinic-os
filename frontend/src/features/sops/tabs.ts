/** The SOP tabs. Its own module so the route can validate `?tab=` without the page. */
export const SOP_TABS = {
  procedures: "Procedures",
  // Offered to `tenant:configure` and `audit:read` holders only; the server decides.
  matrix: "Acknowledgements",
} as const
export type SopTab = keyof typeof SOP_TABS
export const SOP_TAB_KEYS = Object.keys(SOP_TABS) as SopTab[]
