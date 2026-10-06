# frontend-features

The ClinicOS clinic app: Today, Calendar, Patients, Script queue, TGA approvals and public booking,
following the Banksia reference design and running against this repository's FastAPI backend.

All documentation is in [`../docs2/`](../docs2/README.md): architecture, design system, which
screens use the real API, ADRs, and per-feature requirements, design, API contract, test plan and DoD.

```bash
cp .env.example .env.local   # /api is proxied to VITE_API_PROXY_TARGET in dev
bun install
bun run dev                  # http://127.0.0.1:5174

bun run lint                 # biome (writes fixes)
bun run typecheck
bun run build                # dist/, with a strict CSP injected
bun run test                 # Playwright against the running backend
bun run generate-client      # regenerate src/client from openapi.json
```

`src/client/` and `src/routeTree.gen.ts` are generated. Don't edit them.
