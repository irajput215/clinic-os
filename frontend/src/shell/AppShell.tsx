import * as DialogPrimitive from "@radix-ui/react-dialog"
import { useQuery, useQueryClient } from "@tanstack/react-query"
import {
  Link,
  Outlet,
  useMatches,
  useNavigate,
  useRouter,
} from "@tanstack/react-router"
import { ArrowLeft, ArrowRight, Menu, X } from "lucide-react"
import { useEffect, useState } from "react"
import { approvalCountsQuery } from "@/data/approvals"
import { isActionable, scriptsQuery } from "@/data/scripts"
import { useClinicSlug } from "@/data/tenant"
import { formatLongDay } from "@/lib/format"
import { currentUserQuery, displayName, signOut } from "@/lib/session"
import { cn } from "@/lib/utils"
import { BrandMark } from "./BrandMark"
import { GlobalSearch } from "./GlobalSearch"
import { type CountKey, NAV } from "./nav"
import { useCanAdminister } from "./useCanAdminister"

function useNavCounts(): Record<CountKey, number | undefined> {
  const scripts = useQuery({ ...scriptsQuery, retry: false })
  const approvals = useQuery({ ...approvalCountsQuery, retry: false })
  return {
    scripts: scripts.data?.filter((s) => isActionable(s.state)).length,
    approvals: approvals.data?.by_state.PENDING,
  }
}

function Sidebar({ onNavigate }: { onNavigate?: () => void }) {
  const counts = useNavCounts()
  const canAdminister = useCanAdminister()
  const clinicSlug = useClinicSlug()
  const { data: me } = useQuery(currentUserQuery)
  const queryClient = useQueryClient()
  const navigate = useNavigate()

  const handleSignOut = () => {
    signOut()
    queryClient.clear()
    navigate({ to: "/login" })
  }

  return (
    <div className="flex h-full flex-col">
      <Link
        to="/"
        onClick={onNavigate}
        // In the drawer, the brand stops short of the close button.
        className={cn(
          "flex items-center gap-2.5 px-[18px] pt-[18px] pb-3.5",
          onNavigate && "mr-14",
        )}
      >
        <BrandMark size={30} />
        <span className="min-w-0">
          <span className="block font-serif text-[19px] leading-tight font-semibold tracking-[-0.01em]">
            Clinic OS
          </span>
          {/* The line is always laid out, so the block does not shift when the slug arrives. */}
          <span
            className="block h-4 truncate text-xs text-stone"
            data-testid="sidebar-clinic"
          >
            {clinicSlug}
          </span>
        </span>
      </Link>

      <nav aria-label="Main" className="flex-1 overflow-y-auto px-2.5 pb-4">
        {NAV.map(({ group, items }) => (
          <div key={group} className="mt-2.5 first:mt-1">
            <div className="px-2.5 pt-2.5 pb-1 text-2xs font-semibold tracking-[0.09em] text-stone-faint uppercase">
              {group}
            </div>
            <ul className="space-y-px">
              {items.map((item) => {
                if (item.requiresAdmin && !canAdminister) return null
                if (item.bookingPage && !clinicSlug) return null
                const Icon = item.icon
                const count = item.count ? counts[item.count] : undefined
                const inner = (
                  <>
                    <Icon
                      className="size-[15px] shrink-0 opacity-80"
                      strokeWidth={1.9}
                    />
                    <span className="flex-1 truncate">{item.label}</span>
                    {count ? (
                      <span className="rounded-full bg-fill px-[7px] font-mono text-2xs font-medium text-stone group-data-[status=active]:bg-clay-soft/60 group-data-[status=active]:text-clay-deep">
                        {count}
                      </span>
                    ) : null}
                  </>
                )
                const base =
                  "group flex w-full items-center gap-2.5 rounded-btn px-2.5 py-[7px] text-sm font-medium transition-colors max-lg:min-h-11"
                if (item.to)
                  return (
                    <li key={item.label}>
                      <Link
                        to={item.to}
                        onClick={onNavigate}
                        activeOptions={{ exact: item.to === "/" }}
                        className={cn(
                          base,
                          "text-ink hover:bg-fill data-[status=active]:bg-clay-tint data-[status=active]:text-clay-deep",
                        )}
                      >
                        {inner}
                      </Link>
                    </li>
                  )
                if (item.bookingPage)
                  return (
                    <li key={item.label}>
                      <a
                        href={`/book/${clinicSlug}`}
                        target="_blank"
                        rel="noopener"
                        className={cn(base, "text-ink hover:bg-fill")}
                      >
                        {inner}
                      </a>
                    </li>
                  )
                return (
                  <li key={item.label}>
                    <span
                      aria-disabled="true"
                      title="Coming in a later phase"
                      className={cn(base, "cursor-default text-stone-faint")}
                    >
                      {inner}
                      <span className="text-[10px] font-semibold tracking-[0.06em] uppercase opacity-0 transition-opacity group-hover:opacity-100">
                        Soon
                      </span>
                    </span>
                  </li>
                )
              })}
            </ul>
          </div>
        ))}
      </nav>

      <div className="border-line border-t px-[18px] pt-3.5 pb-4 text-sm">
        {me ? (
          <Link
            to="/settings"
            onClick={onNavigate}
            title="Your settings"
            className="-mx-2 -my-1 block rounded-btn px-2 py-1 hover:bg-fill max-lg:min-h-11"
          >
            <div className="truncate font-semibold">{displayName(me)}</div>
            <div className="truncate text-xs text-stone">{me.email}</div>
          </Link>
        ) : (
          <div className="h-9 animate-pulse rounded bg-fill" />
        )}
        <div className="mt-3 flex items-center justify-between text-xs">
          <span className="inline-flex items-center gap-1.5 text-stone">
            <span className="size-1.5 rounded-full bg-ok" />
            AU data residency
          </span>
          <button
            type="button"
            onClick={handleSignOut}
            className="font-medium text-clay hover:text-clay-hover hover:underline max-lg:-my-3 max-lg:min-h-11 max-lg:px-2 max-lg:-mr-2"
          >
            Sign out
          </button>
        </div>
      </div>
    </div>
  )
}

function TopBar() {
  const router = useRouter()
  const matches = useMatches()
  const title =
    [...matches].reverse().find((m) => m.staticData?.title)?.staticData
      ?.title ?? "Clinic OS"

  return (
    <header className="sticky top-0 z-20 flex items-center gap-3 border-line border-b bg-oat/90 px-4 py-3.5 backdrop-blur-md max-lg:py-2 md:px-8">
      {/* The drawer's trigger, so closing the drawer returns focus here. */}
      <DialogPrimitive.Trigger asChild>
        <button
          type="button"
          className="-ml-2.5 grid size-11 shrink-0 place-items-center rounded-btn text-stone hover:bg-fill lg:hidden"
          aria-label="Open navigation"
        >
          <Menu className="size-5" />
        </button>
      </DialogPrimitive.Trigger>
      {/* History buttons are a desktop convenience; a touch screen has the system's own back. */}
      <div className="hidden items-center gap-1 lg:flex">
        <button
          type="button"
          onClick={() => router.history.back()}
          className="grid size-[30px] place-items-center rounded-btn border border-line bg-paper text-stone hover:text-ink"
          aria-label="Back"
        >
          <ArrowLeft className="size-3.5" />
        </button>
        <button
          type="button"
          onClick={() => router.history.forward()}
          className="grid size-[30px] place-items-center rounded-btn border border-line bg-paper text-stone hover:text-ink"
          aria-label="Forward"
        >
          <ArrowRight className="size-3.5" />
        </button>
      </div>
      <div className="min-w-0 truncate font-serif text-[19px] font-medium max-sm:hidden lg:ml-2">
        {title}
      </div>
      <div className="ml-auto flex items-center gap-3 max-sm:min-w-0 max-sm:flex-1">
        <GlobalSearch />
        <span className="hidden rounded-chip bg-fill px-2.5 py-1 font-mono text-[11.5px] text-stone xl:inline">
          {formatLongDay(new Date())}
        </span>
      </div>
    </header>
  )
}

/** The sidebar's breakpoint (Tailwind `lg`); below it the sidebar is a drawer. */
const SIDEBAR_QUERY = "(min-width: 1024px)"

export function AppShell() {
  const [drawer, setDrawer] = useState(false)
  const matches = useMatches()
  const leaf = matches[matches.length - 1]?.pathname

  // Close the drawer whenever the route changes.
  useEffect(() => {
    if (leaf) setDrawer(false)
  }, [leaf])

  // And when the screen grows past the breakpoint (a rotated tablet), so a drawer that is no
  // longer shown never keeps the page behind it inert.
  useEffect(() => {
    const wide = window.matchMedia(SIDEBAR_QUERY)
    const close = () => {
      if (wide.matches) setDrawer(false)
    }
    wide.addEventListener("change", close)
    return () => wide.removeEventListener("change", close)
  }, [])

  return (
    <DialogPrimitive.Root open={drawer} onOpenChange={setDrawer}>
      <div className="min-h-dvh lg:grid lg:grid-cols-[232px_minmax(0,1fr)]">
        <aside className="sticky top-0 hidden h-dvh border-line border-r bg-paper lg:block">
          <Sidebar />
        </aside>

        {/* Below 1024 px the sidebar is a modal drawer: focus stays inside it, Escape or a tap
            outside closes it, and focus returns to the menu button (its trigger). */}
        <DialogPrimitive.Portal>
          <DialogPrimitive.Overlay className="fixed inset-0 z-40 bg-ink/30 backdrop-blur-[2px] data-[state=closed]:animate-out data-[state=closed]:fade-out-0 data-[state=open]:animate-in data-[state=open]:fade-in-0 lg:hidden" />
          <DialogPrimitive.Content
            aria-describedby={undefined}
            className="fixed inset-y-0 left-0 z-40 w-[min(280px,calc(100vw-3rem))] border-line border-r bg-paper shadow-pop outline-none duration-200 data-[state=closed]:animate-out data-[state=closed]:slide-out-to-left data-[state=open]:animate-in data-[state=open]:slide-in-from-left lg:hidden"
          >
            <DialogPrimitive.Title className="sr-only">
              Navigation
            </DialogPrimitive.Title>
            <DialogPrimitive.Close
              className="absolute top-3 right-2 grid size-11 place-items-center rounded-btn text-stone hover:bg-fill"
              aria-label="Close navigation"
            >
              <X className="size-5" />
            </DialogPrimitive.Close>
            <Sidebar onNavigate={() => setDrawer(false)} />
          </DialogPrimitive.Content>
        </DialogPrimitive.Portal>

        <div className="min-w-0">
          <TopBar />
          <main className="mx-auto w-full max-w-[1240px] px-4 pt-7 pb-16 md:px-8">
            <Outlet />
          </main>
        </div>
      </div>
    </DialogPrimitive.Root>
  )
}
