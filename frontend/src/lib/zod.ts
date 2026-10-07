import { z } from "zod"

/**
 * zod, configured for a strict Content-Security-Policy. Without `jitless`, zod probes `new Function`
 * to decide whether it may compile fast paths, and the CSP (no `unsafe-eval`) reports that probe as a
 * violation. Import `z` from here, never from "zod" directly.
 */
z.config({ jitless: true })

export { z }
