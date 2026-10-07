# frontend-features

The ClinicOS app, and the only frontend in this repository: Today, Calendar, Patients, Script queue,
TGA approvals, public booking, sign in, organisation signup, password recovery, Administration and
Settings, following the Banksia reference design. The backend image builds it and serves it at `/`
([ADR-F005](../docs2/adr/ADR-F005-one-app-served-by-the-backend.md)).

All documentation is in [`../docs2/`](../docs2/README.md): architecture, design system, which
screens use the real API, ADRs, and per-feature requirements, design, API contract, test plan and DoD.

```bash
cp .env.example .env.local   # /api is proxied to VITE_API_PROXY_TARGET in dev
bun install
bun run dev                  # http://127.0.0.1:5174

bun run lint                 # biome (writes fixes)
bun run typecheck
bun run build                # ../backend/app/frontend (served at /), with a strict CSP injected
bun run test                 # Playwright via the dev server, against the running backend
PLAYWRIGHT_BASE_URL=http://127.0.0.1:8000 bun run test   # against the backend serving the build
bun run generate-client      # regenerate src/client from openapi.json
```

`src/client/` and `src/routeTree.gen.ts` are generated. Don't edit them.
