import {
  MutationCache,
  QueryCache,
  QueryClient,
  QueryClientProvider,
} from "@tanstack/react-query"
import { createRouter, RouterProvider } from "@tanstack/react-router"
import { AxiosError } from "axios"
import { lazy, StrictMode, Suspense } from "react"
import ReactDOM from "react-dom/client"
import { client } from "./client/client.gen"
import { retryTransient } from "./lib/http"
import { readToken, signOut } from "./lib/session"
import { routeTree } from "./routeTree.gen"
import "./styles/app.css"

/**
 * Toasts only ever follow something the person did (a save, a sign, a refusal), so the toast
 * library is not part of the first load: it arrives in its own chunk right after the first render,
 * long before anything can raise one.
 */
const Toaster = lazy(() =>
  import("./components/ui/sonner").then((m) => ({ default: m.Toaster })),
)

client.setConfig({
  baseURL: import.meta.env.VITE_API_URL ?? "",
  auth: () => readToken() ?? "",
  timeout: 15_000,
})

/**
 * `401` is the only status that signs the user out: it means "this session is unusable". A `403`
 * means the session is fine and this identity may not do this, so it stays on the page and the
 * screen explains it.
 */
const handleApiError = (error: Error) => {
  if (!(error instanceof AxiosError) || error.response?.status !== 401) return
  if (window.location.pathname.startsWith("/login")) return
  signOut()
  queryClient.clear()
  const redirect = window.location.pathname + window.location.search
  router.navigate({ to: "/login", search: { redirect } })
}

const queryClient = new QueryClient({
  queryCache: new QueryCache({ onError: handleApiError }),
  mutationCache: new MutationCache({ onError: handleApiError }),
  defaultOptions: {
    queries: { retry: retryTransient, refetchOnWindowFocus: true },
    mutations: { retry: false },
  },
})

const router = createRouter({
  routeTree,
  context: { queryClient },
  defaultPreload: "intent",
  // Route loaders read through the query cache, which owns freshness.
  defaultPreloadStaleTime: 0,
  scrollRestoration: true,
})

declare module "@tanstack/react-router" {
  interface Register {
    router: typeof router
  }
  interface StaticDataRouteOption {
    title?: string
  }
}

ReactDOM.createRoot(document.getElementById("root")!).render(
  <StrictMode>
    <QueryClientProvider client={queryClient}>
      <RouterProvider router={router} />
      <Suspense fallback={null}>
        <Toaster position="bottom-right" closeButton />
      </Suspense>
    </QueryClientProvider>
  </StrictMode>,
)
