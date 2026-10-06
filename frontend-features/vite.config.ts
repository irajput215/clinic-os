import path from "node:path"
import tailwindcss from "@tailwindcss/vite"
import { tanstackRouter } from "@tanstack/router-plugin/vite"
import react from "@vitejs/plugin-react"
import { defineConfig, loadEnv, type Plugin } from "vite"

/**
 * A strict Content-Security-Policy for the production bundle.
 *
 * Injected at build time only: the dev server's React Fast Refresh preamble is an inline script, so a
 * strict policy in dev would break HMR rather than protect anything. The built bundle has no inline
 * script and no inline event handler, so `script-src 'self'` holds. `connect-src` names the API origin
 * the bundle was built for and nothing else.
 *
 * `frame-ancestors` is deliberately absent: browsers ignore it in a <meta> policy. Clickjacking
 * protection must be sent by the host as HTTP headers (`Content-Security-Policy: frame-ancestors
 * 'none'` and `X-Frame-Options: DENY`); see docs2/architecture.md.
 */
const contentSecurityPolicy = (apiUrl: string): Plugin => {
  const connect = ["'self'", apiUrl].filter(Boolean).join(" ")
  const policy = [
    "default-src 'self'",
    "script-src 'self'",
    "style-src 'self' 'unsafe-inline'",
    "img-src 'self' data:",
    "font-src 'self'",
    `connect-src ${connect}`,
    "base-uri 'none'",
    "form-action 'self'",
    "object-src 'none'",
  ].join("; ")
  return {
    name: "clinic-os-csp",
    apply: "build",
    transformIndexHtml: (html) =>
      html.replace(
        "<head>",
        `<head>\n    <meta http-equiv="Content-Security-Policy" content="${policy}" />`,
      ),
  }
}

export default defineConfig(({ mode }) => {
  const env = loadEnv(mode, process.cwd(), "VITE_")
  const apiProxy = {
    "/api": {
      target: env.VITE_API_PROXY_TARGET || "http://127.0.0.1:8000",
      changeOrigin: false,
    },
  }
  return {
    server: {
      port: 5174,
      strictPort: true,
      // Dev only: with VITE_API_URL unset, `/api` is same-origin and proxied to the backend, so
      // local development needs no CORS allowance. Production serves the SPA and API together or
      // sets VITE_API_URL at build time.
      proxy: apiProxy,
    },
    // `vite preview` serves the production build (with its CSP) behind the same proxy.
    preview: { port: 5175, strictPort: true, proxy: apiProxy },
    build: {
      target: "es2022",
      outDir: "dist",
      emptyOutDir: true,
      sourcemap: false,
    },
    resolve: {
      alias: {
        "@": path.resolve(import.meta.dirname, "./src"),
      },
    },
    plugins: [
      tanstackRouter({
        target: "react",
        autoCodeSplitting: true,
      }),
      react(),
      tailwindcss(),
      contentSecurityPolicy(env.VITE_API_URL ?? ""),
    ],
  }
})
