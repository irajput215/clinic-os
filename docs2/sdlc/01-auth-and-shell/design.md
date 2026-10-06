# Auth and app shell: design

## Screens

### Sign in (`/login`)

Centred card on the tiled-mark backdrop: brand mark, serif title, italic tagline, email, password, clay Sign in button, link to the public booking page, and an `AU data residency · AES-256 at rest` footer.

### Signup, recovery and reset (`/signup`, `/recover-password`, `/reset-password`)

The same card as sign in (`features/auth/AuthLayout.tsx`): serif title, italic lead, fields, one clay action, a link back to sign in. Each has a confirmation state (green, `role=status`, focus moves to the title) and one `role=alert` refusal carrying the API's `request_id` as a Reference. Sign in links to "Forgot password?" and "Create an organisation".

### App shell (`_app` layout)

A 232 px paper sidebar with brand, grouped nav and the signed-in user with sign-out. A sticky top bar with back/forward, serif page title, patient quick-find and a mono date chip. Content runs up to 1240 px.

## States

Sign-in: field errors inline, a single `role=alert` for bad credentials or rate limiting (`429`). Shell: user block skeleton while `/users/me` loads.

## Data flow

`_app.beforeLoad` checks for a token, then `loader` ensures `GET /users/me`. Counts come from `scriptsQuery` and `approvalsQuery`, which the pages also use, so badges and pages always agree.

Tokens and components: [design-system.md](../../design-system.md).
