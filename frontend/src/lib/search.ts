/**
 * URL search-param parsers for route `validateSearch`.
 *
 * Deliberately not zod: a route's `validateSearch` is part of the entry bundle (it runs before any
 * code-split chunk loads), and these four shapes do not justify shipping a schema library on every
 * page. Each parser accepts anything and returns only values it recognises.
 */
const str = (v: unknown) => (typeof v === "string" ? v : undefined)

export const isoDate = (v: unknown) => {
  const s = str(v)
  return s && /^\d{4}-\d{2}-\d{2}$/.test(s) ? s : undefined
}

export const oneOf = <T extends string>(allowed: readonly T[], v: unknown) => {
  const s = str(v)
  return s && (allowed as readonly string[]).includes(s) ? (s as T) : undefined
}

/** Only same-origin absolute paths are honoured as a redirect target (no open redirect). */
export const safeRedirect = (v: unknown) => {
  const s = str(v)
  return s && /^\/(?!\/)/.test(s) && !s.includes("\\") ? s : undefined
}
