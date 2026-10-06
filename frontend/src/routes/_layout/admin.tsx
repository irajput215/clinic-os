import { createFileRoute } from "@tanstack/react-router"

import { AdminPageLoading } from "@/components/Admin/AdminStates"
import PermissionsPanel from "@/components/Admin/PermissionsPanel"
import RolesPanel from "@/components/Admin/RolesPanel"
import UserAccessPanel from "@/components/Admin/UserAccessPanel"
import UsersPanel from "@/components/Admin/UsersPanel"
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs"
import useAuth from "@/hooks/useAuth"

/**
 * The administration area.
 *
 * There is no `beforeLoad` permission gate. The template gated `/admin` on `is_superuser`,
 * but the administration API is authorised by `users:manage`, and the frontend has no
 * capability endpoint (`GET /auth/capabilities` is feature 02, not built), so any gate here
 * would be a guess. The API is the only security boundary (INV-3): the route renders, the
 * request goes out, and a `403` renders as the "you do not have permission" state rather
 * than a redirect. The legacy superuser-only Users tab stays superuser-only because its
 * route is the unscoped template one.
 *
 * The active tab lives in the URL (`/admin?tab=permissions`) so a view can be linked and a
 * refresh does not lose it.
 */

const ADMIN_TABS = ["roles", "permissions", "access", "users"] as const

type AdminTab = (typeof ADMIN_TABS)[number]

export const Route = createFileRoute("/_layout/admin")({
  component: Admin,
  validateSearch: (search: Record<string, unknown>): { tab?: AdminTab } => {
    const tab = search.tab
    return typeof tab === "string" &&
      (ADMIN_TABS as readonly string[]).includes(tab)
      ? { tab: tab as AdminTab }
      : {}
  },
  head: () => ({
    meta: [
      {
        title: "Administration - ClinicOS",
      },
    ],
  }),
})

function Admin() {
  const { user: currentUser } = useAuth()
  const search = Route.useSearch()
  const navigate = Route.useNavigate()

  if (!currentUser) {
    return <AdminPageLoading />
  }

  const isSuperuser = Boolean(currentUser.is_superuser)
  const fallbackTab: AdminTab = isSuperuser ? "users" : "roles"
  const activeTab: AdminTab =
    search.tab === "users" && !isSuperuser
      ? fallbackTab
      : (search.tab ?? fallbackTab)

  return (
    <div className="flex flex-col gap-6">
      <div>
        <h1 className="text-2xl font-bold tracking-tight">Administration</h1>
        <p className="text-muted-foreground">
          The roles and permissions of your organisation, and who holds them.
        </p>
      </div>

      <Tabs
        value={activeTab}
        onValueChange={(value) =>
          navigate({ search: { tab: value as AdminTab } })
        }
        className="gap-6"
      >
        <TabsList className="h-auto flex-wrap">
          <TabsTrigger value="roles">Roles</TabsTrigger>
          <TabsTrigger value="permissions">Permission catalogue</TabsTrigger>
          <TabsTrigger value="access">User access</TabsTrigger>
          {isSuperuser ? <TabsTrigger value="users">Users</TabsTrigger> : null}
        </TabsList>

        <TabsContent value="roles">
          <RolesPanel currentUserId={currentUser.id} />
        </TabsContent>
        <TabsContent value="permissions">
          <PermissionsPanel />
        </TabsContent>
        <TabsContent value="access">
          <UserAccessPanel currentUserId={currentUser.id} />
        </TabsContent>
        {isSuperuser ? (
          <TabsContent value="users">
            <UsersPanel />
          </TabsContent>
        ) : null}
      </Tabs>
    </div>
  )
}
