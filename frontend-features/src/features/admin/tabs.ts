/** The administration tabs. Its own module so the route can validate `?tab=` without the page. */
export const ADMIN_TABS = {
  roles: "Roles and permissions",
  access: "User access",
  accounts: "Accounts",
} as const
export type AdminTab = keyof typeof ADMIN_TABS
export const ADMIN_TAB_KEYS = Object.keys(ADMIN_TABS) as AdminTab[]
