# Decisions for the `frontend/` app

| ADR | Decision | Status |
|---|---|---|
| [ADR-F001](ADR-F001-separate-spa.md) | A separate SPA beside `frontend/`, not a rewrite of it | Superseded by ADR-F005 |
| [ADR-F002](ADR-F002-token-storage.md) | Access token in `sessionStorage`; password re-entry as interim step-up | Accepted (interim, until D-003) |
| [ADR-F003](ADR-F003-validity-boundary-in-the-ui.md) | The UI sends the letter's end date unchanged and labels it "not covered" | Accepted (follows D-006 interim) |
| [ADR-F004](ADR-F004-preview-store.md) | Features without a backend run on a labelled in-browser preview store | Accepted |
| [ADR-F005](ADR-F005-one-app-served-by-the-backend.md) | One app, built from `frontend-features/` (renamed to `frontend/` on 2026-10-07) and served by the backend at `/`; the template `frontend/` deleted | Accepted |

Platform-wide decisions (D-001 … D-006) live in [`docs/reference/decisions/`](../../docs/reference/decisions/).
