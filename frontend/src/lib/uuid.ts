/**
 * A UUID v4, from the platform's CSPRNG. Built from `getRandomValues`, not `crypto.randomUUID`:
 * the latter exists only in a secure context, so on a plain-HTTP origin other than localhost (CI's
 * `http://backend:8000`, an internal host) it is undefined and the screen that called it failed to
 * load.
 */
export const uuid = () => {
  const b = crypto.getRandomValues(new Uint8Array(16))
  b[6] = (b[6] & 0x0f) | 0x40
  b[8] = (b[8] & 0x3f) | 0x80
  const h = Array.from(b, (x) => x.toString(16).padStart(2, "0")).join("")
  return `${h.slice(0, 8)}-${h.slice(8, 12)}-${h.slice(12, 16)}-${h.slice(16, 20)}-${h.slice(20)}`
}
