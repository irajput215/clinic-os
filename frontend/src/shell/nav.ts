import {
  BookOpen,
  CalendarDays,
  ChartColumn,
  CircleDollarSign,
  ClipboardCheck,
  ClipboardList,
  ExternalLink,
  FileSignature,
  Hourglass,
  Inbox,
  LayoutDashboard,
  type LucideIcon,
  Mail,
  Pill,
  RefreshCcw,
  Settings,
  Store,
  UserCog,
  Users,
} from "lucide-react"

export type CountKey = "scripts" | "approvals"

export interface NavItem {
  label: string
  icon: LucideIcon
  /** Absent: not built in this phase; shown disabled with a "coming" hint. */
  to?:
    | "/"
    | "/calendar"
    | "/patients"
    | "/scripts"
    | "/approvals"
    | "/admin"
    | "/settings"
  /**
   * The clinic's public booking page, opened outside the app shell at `/book/<slug>`. Shown only
   * once the signed-in clinic's slug is known.
   */
  bookingPage?: true
  count?: CountKey
  /** Shown only to someone who may administer (see `useCanAdminister`); the server still decides. */
  requiresAdmin?: boolean
}

export const NAV: Array<{ group: string; items: NavItem[] }> = [
  {
    group: "Care",
    items: [
      { label: "Today", icon: LayoutDashboard, to: "/" },
      { label: "Calendar", icon: CalendarDays, to: "/calendar" },
      { label: "Patients", icon: Users, to: "/patients" },
      { label: "Waitlist", icon: Hourglass },
    ],
  },
  {
    group: "Prescribing",
    items: [
      {
        label: "Script queue",
        icon: FileSignature,
        to: "/scripts",
        count: "scripts",
      },
      { label: "Drug catalogue", icon: Pill },
      {
        label: "Approvals",
        icon: ClipboardCheck,
        to: "/approvals",
        count: "approvals",
      },
      { label: "Pharmacy network", icon: Store },
    ],
  },
  {
    group: "Business",
    items: [
      { label: "Billing & payouts", icon: CircleDollarSign },
      { label: "Automations", icon: RefreshCcw },
      { label: "Forms & consent", icon: ClipboardList },
      { label: "Reports", icon: ChartColumn },
    ],
  },
  {
    group: "Practice",
    items: [
      { label: "Patient mail", icon: Mail },
      { label: "Inbox", icon: Inbox },
      { label: "SOPs & policies", icon: BookOpen },
      {
        label: "Administration",
        icon: UserCog,
        to: "/admin",
        requiresAdmin: true,
      },
      { label: "Settings", icon: Settings, to: "/settings" },
      {
        label: "Booking page",
        icon: ExternalLink,
        bookingPage: true,
      },
    ],
  },
]
