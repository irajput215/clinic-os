/// <reference types="vite/client" />

interface ImportMetaEnv {
  /** The API origin, e.g. `http://localhost:8000`. Empty means same origin. */
  readonly VITE_API_URL?: string
  /** Dev server only: where `/api` is proxied (default http://127.0.0.1:8000). */
  readonly VITE_API_PROXY_TARGET?: string
}

interface ImportMeta {
  readonly env: ImportMetaEnv
}
