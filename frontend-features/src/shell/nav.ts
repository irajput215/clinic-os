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
  Users,
} from "lucide-react"

export type CountKey = "scripts" | "approvals"

export interface NavItem {
  label: string
  icon: LucideIcon
  /** Absent: not built in this phase; shown disabled with a "coming" hint. */
  to?: "/" | "/calendar" | "/patients" | "/scripts" | "/approvals"
  /** Opens outside the app shell (the public booking page). */
  href?: string
  count?: CountKey
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
      { label: "Admin & settings", icon: Settings },
      {
        label: "Booking page",
        icon: ExternalLink,
        href: "/book/banksia-family-medical",
      },
    ],
  },
]
