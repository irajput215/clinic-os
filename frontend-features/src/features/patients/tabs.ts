/** The patient record's tabs. Its own module so the route can validate `?tab=` without the page. */
export const PATIENT_TABS = {
  overview: "Overview",
  notes: "Consult notes",
  approvals: "TGA approvals",
  scripts: "Scripts",
  appointments: "Appointments",
  activity: "Activity",
} as const
export type PatientTab = keyof typeof PATIENT_TABS
export const PATIENT_TAB_KEYS = Object.keys(PATIENT_TABS) as PatientTab[]
