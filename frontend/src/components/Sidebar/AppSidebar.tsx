import { Home, Stethoscope, Users } from "lucide-react"

import { SidebarAppearance } from "@/components/Common/Appearance"
import { Logo } from "@/components/Common/Logo"
import {
  Sidebar,
  SidebarContent,
  SidebarFooter,
  SidebarHeader,
} from "@/components/ui/sidebar"
import useAuth from "@/hooks/useAuth"
import { type Item, Main } from "./Main"
import { User } from "./User"

const baseItems: Item[] = [
  { icon: Home, title: "Dashboard", path: "/" },
  { icon: Stethoscope, title: "Patients", path: "/patients" },
]

export function AppSidebar() {
  const { user: currentUser } = useAuth()

  // The administration API is authorised by `users:manage`, which the frontend cannot read
  // before it calls an administration endpoint (there is no `/auth/capabilities` yet), so
  // the entry is shown to a superuser and to any account that belongs to an organisation.
  // The screen itself renders the API's `403` for an account that holds no `users:manage`.
  const canSeeAdmin = Boolean(
    currentUser?.is_superuser || currentUser?.tenant_id,
  )

  const items = canSeeAdmin
    ? [...baseItems, { icon: Users, title: "Admin", path: "/admin" }]
    : baseItems

  return (
    <Sidebar collapsible="icon">
      <SidebarHeader className="px-4 py-6 group-data-[collapsible=icon]:px-0 group-data-[collapsible=icon]:items-center">
        <Logo variant="responsive" />
      </SidebarHeader>
      <SidebarContent>
        <Main items={items} />
      </SidebarContent>
      <SidebarFooter>
        <SidebarAppearance />
        <User user={currentUser} />
      </SidebarFooter>
    </Sidebar>
  )
}

export default AppSidebar
