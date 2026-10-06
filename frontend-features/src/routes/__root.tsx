import type { QueryClient } from "@tanstack/react-query"
import {
  createRootRouteWithContext,
  Link,
  Outlet,
  useMatches,
} from "@tanstack/react-router"
import { useEffect } from "react"
import { BrandMark } from "@/shell/BrandMark"

export const Route = createRootRouteWithContext<{ queryClient: QueryClient }>()(
  {
    component: Root,
    notFoundComponent: NotFound,
  },
)

function Root() {
  const matches = useMatches()
  const title = [...matches].reverse().find((m) => m.staticData?.title)
    ?.staticData?.title
  useEffect(() => {
    document.title = title ? `${title} · Clinic OS` : "Clinic OS"
  }, [title])
  return <Outlet />
}

function NotFound() {
  return (
    <div className="backdrop-pattern grid min-h-dvh place-items-center p-6">
      <div className="max-w-[400px] rounded-[18px] border border-line bg-paper/95 p-10 text-center shadow-pop">
        <BrandMark size={40} className="mx-auto mb-4" />
        <h1 className="font-serif text-2xl font-semibold">Page not found</h1>
        <p className="mt-2 text-sm text-stone">
          That address doesn't match anything in Clinic OS.
        </p>
        <Link
          to="/"
          className="mt-5 inline-block text-sm font-medium text-clay hover:underline"
        >
          Back to today's clinic
        </Link>
      </div>
    </div>
  )
}
