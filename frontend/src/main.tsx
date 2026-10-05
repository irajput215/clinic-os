import {
  MutationCache,
  QueryCache,
  QueryClient,
  QueryClientProvider,
} from "@tanstack/react-query"
import { createRouter, RouterProvider } from "@tanstack/react-router"
import { AxiosError } from "axios"
import { StrictMode } from "react"
import ReactDOM from "react-dom/client"
import { client } from "./client/client.gen"
import { ThemeProvider } from "./components/theme-provider"
import { Toaster } from "./components/ui/sonner"
import "./index.css"
import { routeTree } from "./routeTree.gen"

client.setConfig({
  baseURL: import.meta.env.VITE_API_URL ?? "",
  auth: () => localStorage.getItem("access_token") || "",
})

/** Opt a request out of the `403` sign-out below. See `Admin/adminQueries.ts`. */
type AuthRedirectMeta = {
  skipAuthRedirect?: boolean
}

declare module "@tanstack/react-query" {
  interface Register {
    queryMeta: AuthRedirectMeta
    mutationMeta: AuthRedirectMeta
  }
}

/**
 * A `401` means the session is gone, so it always signs out. A `403` usually means the same
 * thing to this app — an account with no organisation — but the administration API uses it
 * for a signed-in caller who simply lacks `users:manage`, and that screen must show the
 * refusal. A request carrying `meta: { skipAuthRedirect: true }` keeps its `403` in the page.
 */
const handleApiError = (error: Error, meta: AuthRedirectMeta | undefined) => {
  if (!(error instanceof AxiosError)) return
  const status = error.response?.status ?? 0
  if (meta?.skipAuthRedirect && status === 403) return
  if ([401, 403].includes(status)) {
    localStorage.removeItem("access_token")
    window.location.href = "/login"
  }
}
const queryClient = new QueryClient({
  queryCache: new QueryCache({
    onError: (error, query) => handleApiError(error, query.meta),
  }),
  mutationCache: new MutationCache({
    onError: (error, _variables, _context, mutation) =>
      handleApiError(error, mutation.meta),
  }),
})

const router = createRouter({ routeTree })
declare module "@tanstack/react-router" {
  interface Register {
    router: typeof router
  }
}

ReactDOM.createRoot(document.getElementById("root")!).render(
  <StrictMode>
    <ThemeProvider defaultTheme="dark" storageKey="vite-ui-theme">
      <QueryClientProvider client={queryClient}>
        <RouterProvider router={router} />
        <Toaster richColors closeButton />
      </QueryClientProvider>
    </ThemeProvider>
  </StrictMode>,
)
