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

/**
 * `401` is the only status that signs the user out.
 *
 * `get_current_user` answers `401` for every unusable session — a token that does not verify, an
 * account that no longer exists, a deactivated account — so `401` means exactly "sign in again".
 * Every other status stays in the page: a `403` means the session is valid and this identity is not
 * allowed to do this, and the screen that asked explains it. Signing out on `403` was what turned
 * "your account has no organisation" on the Patients tab into a login loop, with the real answer
 * discarded. A per-request opt-out (`meta: { skipAuthRedirect: true }`) used to carve a `403` out of
 * that rule; there is nothing left to carve out, so the rule is one line in one place and no screen
 * can forget it.
 */
const handleApiError = (error: Error) => {
  if (!(error instanceof AxiosError)) return
  if (error.response?.status !== 401) return
  localStorage.removeItem("access_token")
  window.location.href = "/login"
}
const queryClient = new QueryClient({
  queryCache: new QueryCache({ onError: handleApiError }),
  mutationCache: new MutationCache({ onError: handleApiError }),
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
