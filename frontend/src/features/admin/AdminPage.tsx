import { useQuery } from "@tanstack/react-query"
import { useNavigate } from "@tanstack/react-router"
import { lazy, Suspense } from "react"
import {
  Card,
  PageHeader,
  PagePending,
  SkeletonRows,
  TabBar,
} from "@/design/primitives"
import { currentUserQuery } from "@/lib/session"
import { AccessPanel } from "./AccessPanel"
import { RolesMatrix } from "./RolesMatrix"
import { StaffPanel } from "./StaffPanel"
import { ADMIN_TAB_KEYS, ADMIN_TABS, type AdminTab } from "./tabs"

// Only a platform superuser ever opens Accounts, so its code loads on demand.
const AccountsPanel = lazy(() =>
  import("./AccountsPanel").then((m) => ({ default: m.AccountsPanel })),
)

export function AdminPage({
  tab,
  account,
}: {
  tab?: AdminTab
  /** The account User access opens on, when Staff sent the administrator there. */
  account?: string
}) {
  const navigate = useNavigate()
  const me = useQuery(currentUserQuery)
  if (!me.data) return <PagePending />

  // Accounts is the platform's superuser-only surface (the server refuses anyone else). Showing the
  // tab to an organisation's administrator would only lead to a refusal. Staff is an organisation's
  // directory, so an account with no organisation (the platform superuser) is not offered it.
  const isSuperuser = Boolean(me.data.is_superuser)
  const hasOrganisation = Boolean(me.data.tenant_id)
  const keys = ADMIN_TAB_KEYS.filter(
    (k) =>
      (k !== "accounts" || isSuperuser) && (k !== "staff" || hasOrganisation),
  )
  const fallback: AdminTab = isSuperuser
    ? "accounts"
    : hasOrganisation
      ? "staff"
      : "roles"
  const active: AdminTab = tab && keys.includes(tab) ? tab : fallback

  return (
    <>
      <PageHeader
        title="Administration"
        subtitle="Who can use Clinic OS, and what each role allows. Every change is checked and recorded by the server."
      />
      <TabBar
        label="Administration"
        tabs={keys.map((key) => ({ key, label: ADMIN_TABS[key] }))}
        value={active}
        onSelect={(key) =>
          navigate({ to: ".", search: { tab: key }, replace: true })
        }
      />
      {active === "staff" ? (
        <StaffPanel
          me={me.data}
          onManageAccess={(id) =>
            navigate({ to: ".", search: { tab: "access", account: id } })
          }
        />
      ) : null}
      {active === "roles" ? <RolesMatrix /> : null}
      {active === "access" ? (
        <AccessPanel
          key={account ?? me.data.id}
          me={me.data}
          initial={account}
        />
      ) : null}
      {active === "accounts" ? (
        <Suspense
          fallback={
            <Card>
              <SkeletonRows rows={5} />
            </Card>
          }
        >
          <AccountsPanel me={me.data} />
        </Suspense>
      ) : null}
    </>
  )
}
