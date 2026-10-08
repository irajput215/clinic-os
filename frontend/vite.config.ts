import { readFile, writeFile } from "node:fs/promises"
import path from "node:path"
import {
  brotliCompressSync,
  gzipSync,
  constants as zlibConstants,
} from "node:zlib"
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
 * protection is sent by the host as HTTP headers (`Content-Security-Policy: frame-ancestors 'none'`
 * and `X-Frame-Options: DENY`), by `backend/app/core/security_headers.py`; see docs2/architecture.md.
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

/**
 * `<link rel="preload">` for the font files the first paint of every screen needs: the serif's and
 * the body face's latin upright (`src/styles/fonts.css`). Without it a font is requested only after
 * the stylesheet is parsed and the first layout finds text that uses it.
 *
 * The files are content-hashed at build, so the links are written from the bundle, never hard-coded.
 * A source file that no longer reaches the bundle fails the build instead of silently losing the
 * preload. Same-origin, so the policy's `font-src 'self'` covers it; `crossorigin` is required
 * because fonts are always fetched in CORS mode and a preload without it is fetched twice.
 */
const CRITICAL_FONTS = [
  "source-serif-4-latin-opsz-normal.woff2",
  "instrument-sans-latin-400-normal.woff2",
]

const preloadFonts = (): Plugin => ({
  name: "clinic-os-preload-fonts",
  apply: "build",
  transformIndexHtml: {
    order: "post",
    handler: (_html, ctx) => {
      const assets = Object.values(ctx.bundle ?? {}).filter(
        (output) => output.type === "asset",
      )
      return CRITICAL_FONTS.map((source) => {
        const asset = assets.find((a) =>
          a.originalFileNames.some((name) => name.endsWith(`/${source}`)),
        )
        if (!asset)
          throw new Error(
            `preloadFonts: ${source} is not in the bundle (src/styles/fonts.css)`,
          )
        return {
          tag: "link",
          attrs: {
            rel: "preload",
            href: `/${asset.fileName}`,
            as: "font",
            type: "font/woff2",
            crossorigin: "",
          },
          // After the CSP <meta>, which governs only what follows it.
          injectTo: "head" as const,
        }
      })
    },
  },
})

/**
 * A Brotli (`.br`) and a gzip (`.gz`) copy beside every compressible file under `assets/`, made
 * once at build with Node's own zlib (no dependency). The backend serves the copy the browser
 * accepts, with `Content-Encoding` and `Vary: Accept-Encoding`, and the original otherwise
 * (`backend/app/core/static_cache.py`), so nothing is compressed per request. Fonts and images are
 * already compressed and are left alone; a copy that saves too little is not written.
 */
const COMPRESSIBLE = /\.(js|css|svg|json|txt)$/
const MIN_BYTES = 1024
const MIN_SAVING = 0.9

const precompress = (): Plugin => {
  let outDir = ""
  return {
    name: "clinic-os-precompress",
    apply: "build",
    configResolved: (config) => {
      outDir = path.resolve(config.root, config.build.outDir)
    },
    writeBundle: async (_options, bundle) => {
      const files = Object.keys(bundle).filter(
        (name) => name.startsWith("assets/") && COMPRESSIBLE.test(name),
      )
      await Promise.all(
        files.map(async (name) => {
          const file = path.join(outDir, name)
          const source = await readFile(file)
          if (source.length < MIN_BYTES) return
          const variants: Array<[string, Buffer]> = [
            [
              ".br",
              brotliCompressSync(source, {
                params: {
                  [zlibConstants.BROTLI_PARAM_MODE]:
                    zlibConstants.BROTLI_MODE_TEXT,
                  [zlibConstants.BROTLI_PARAM_QUALITY]:
                    zlibConstants.BROTLI_MAX_QUALITY,
                  [zlibConstants.BROTLI_PARAM_SIZE_HINT]: source.length,
                },
              }),
            ],
            [
              ".gz",
              gzipSync(source, { level: zlibConstants.Z_BEST_COMPRESSION }),
            ],
          ]
          for (const [suffix, data] of variants)
            if (data.length < source.length * MIN_SAVING)
              await writeFile(file + suffix, data)
        }),
      )
    },
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
      // An explicit IPv4 host: "localhost" binds only ::1 on macOS, so http://127.0.0.1:5174 (the
      // documented URL and Playwright's default baseURL) would refuse connections.
      host: "127.0.0.1",
      port: 5174,
      strictPort: true,
      // Dev only: with VITE_API_URL unset, `/api` is same-origin and proxied to the backend, so
      // local development needs no CORS allowance. Production serves the SPA and the API from one
      // origin (the backend serves this build), so VITE_API_URL stays empty there too.
      proxy: apiProxy,
    },
    // `vite preview` serves the production build (with its CSP) behind the same proxy.
    preview: {
      host: "127.0.0.1",
      port: 5175,
      strictPort: true,
      proxy: apiProxy,
    },
    build: {
      target: "es2022",
      // The backend image serves this directory at `/` (backend/app/main.py, FRONTEND_DIR). It is
      // gitignored build output; `emptyOutDir` is needed because it sits outside this project.
      outDir: "../backend/app/frontend",
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
      preloadFonts(),
      precompress(),
    ],
  }
})
