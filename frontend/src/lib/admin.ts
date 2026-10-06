/**
 * The administration screen's reference data and the one place it reads an API refusal.
 *
 * Two things live here, and nothing else:
 *
 * 1. How the global permission catalogue is grouped for reading. `GET /permissions` returns
 *    a flat list in the catalogue's declared order; the groups below are presentation only.
 *    A code the API returns that no group names is never dropped — it lands in "Other".
 * 2. How the screen reads grantability (R3) from data the API already returned. This is a
 *    *derived, advisory* reading of the caller's own effective permissions against a role's
 *    bundle, so the screen can explain a refusal before it happens. It is never a control:
 *    the backend recomputes the decision on every request and answers `403
 *    GRANT_EXCEEDS_ACTOR`, and {@link isGrantExceedsActor} is how the screen recognises that
 *    answer. The frontend hides, disables and warns; it never decides (INV-3).
 */

import { AxiosError } from "axios"

import type { PermissionRead, RoleRead } from "@/client"

export type PermissionGroup = {
  /** Stable id, used for React keys and test ids. */
  id: string
  title: string
  description: string
  /** The catalogue codes that belong to this group, in reading order. */
  codes: readonly string[]
}

/**
 * The 19 permission codes of `docs/features/03-users-and-roles/01-requirements.md`,
 * grouped by the part of the product they govern. The titles are the screen's own words;
 * the descriptions the API returns are what each code means.
 */
export const PERMISSION_GROUPS: readonly PermissionGroup[] = [
  {
    id: "patients",
    title: "Patients",
    description: "The patient register of your organisation.",
    codes: [
      "patient:read",
      "patient:create",
      "patient:update",
      "patient:export",
    ],
  },
  {
    id: "clinical-records",
    title: "Clinical records",
    description: "The clinical notes attached to a patient.",
    codes: ["clinical_record:read", "clinical_record:write"],
  },
  {
    id: "prescriptions",
    title: "Prescriptions",
    description: "Creating, changing, signing and dispatching a prescription.",
    codes: [
      "prescription:create",
      "prescription:modify",
      "prescription:sign",
      "prescription:dispatch",
    ],
  },
  {
    id: "tga",
    title: "TGA approvals and inbox",
    description: "The TGA approval workflow and its incoming correspondence.",
    codes: [
      "tga_approval:read",
      "tga_approval:create",
      "tga_approval:verify",
      "tga_inbox:process",
    ],
  },
  {
    id: "pharmacy",
    title: "Pharmacy dispatch",
    description: "Receiving and confirming a pharmacy dispatch.",
    codes: ["pharmacy:dispatch"],
  },
  {
    id: "oversight",
    title: "Oversight",
    description: "Reading the audit trail and exporting reports.",
    codes: ["audit:read", "reports:export"],
  },
  {
    id: "administration",
    title: "Organisation administration",
    description: "Managing people and the organisation's security settings.",
    codes: ["users:manage", "tenant:configure"],
  },
]

export type CatalogueGroup = {
  id: string
  title: string
  description: string
  permissions: PermissionRead[]
}

/**
 * Group the catalogue the API returned, preserving the API's order inside each group.
 * Every permission appears exactly once; an unrecognised code is kept in "Other".
 */
export function groupPermissions(
  permissions: readonly PermissionRead[],
): CatalogueGroup[] {
  const byCode = new Map(
    permissions.map((permission) => [permission.code, permission]),
  )
  const grouped = new Set<string>()

  const groups: CatalogueGroup[] = PERMISSION_GROUPS.map((group) => {
    const items: PermissionRead[] = []
    for (const code of group.codes) {
      const permission = byCode.get(code)
      if (permission) {
        items.push(permission)
        grouped.add(permission.code)
      }
    }
    return {
      id: group.id,
      title: group.title,
      description: group.description,
      permissions: items,
    }
  }).filter((group) => group.permissions.length > 0)

  const other = permissions.filter(
    (permission) => !grouped.has(permission.code),
  )
  if (other.length > 0) {
    groups.push({
      id: "other",
      title: "Other permissions",
      description: "Codes this screen does not recognise yet.",
      permissions: other,
    })
  }

  return groups
}

export type Grantability = {
  grantable: boolean
  /** The codes in the role's bundle that the caller does not hold. Empty when grantable. */
  missing: string[]
}

/**
 * Whether the signed-in user can grant this role, read from the caller's own effective
 * permissions and the role's bundle.
 *
 * `undefined` means "not determinable": the caller's effective set has not loaded, so the
 * screen says so rather than guessing. An empty bundle is grantable — it carries nothing to
 * escalate, which is the rule the policy layer applies.
 */
export function roleGrantability(
  role: Pick<RoleRead, "permissions">,
  held: ReadonlySet<string> | undefined,
): Grantability | undefined {
  if (!held) return undefined

  const missing = role.permissions
    .map((permission) => permission.code)
    .filter((code) => !held.has(code))
  missing.sort()

  return { grantable: missing.length === 0, missing }
}

/** The single sentence every refusal surfaces, whatever path produced it. */
export const GRANTABILITY_EXPLANATION =
  "You can grant only roles whose permissions you hold. Your role does not include the permissions in this role."

/** The human list of missing codes, e.g. "a, b and c". */
export function formatCodeList(codes: readonly string[]): string {
  if (codes.length === 0) return ""
  if (codes.length === 1) return codes[0]
  return `${codes.slice(0, -1).join(", ")} and ${codes[codes.length - 1]}`
}

/**
 * The machine-readable reason code from the API's standard denial envelope
 * (`{ detail: { code, message } }`). `undefined` for a string detail or a network failure.
 */
export function apiErrorCode(error: unknown): string | undefined {
  if (!(error instanceof AxiosError)) return undefined
  const detail: unknown = error.response?.data?.detail
  if (typeof detail !== "object" || detail === null) return undefined
  const code = (detail as { code?: unknown }).code
  return typeof code === "string" ? code : undefined
}

/** The API's own message for a denial, or `undefined` when it sent none. */
export function apiErrorMessage(error: unknown): string | undefined {
  if (!(error instanceof AxiosError)) return undefined
  const detail: unknown = error.response?.data?.detail
  if (typeof detail === "string") return detail
  if (typeof detail === "object" && detail !== null) {
    const message = (detail as { message?: unknown }).message
    if (typeof message === "string") return message
  }
  return undefined
}

/**
 * `true` for any `403`. The API uses `403` both for "this account holds no
 * `users:manage`" and for "this account has no organisation"; the screen explains both
 * without trying to tell them apart, because the backend deliberately does not.
 */
export function isForbidden(error: unknown): boolean {
  return error instanceof AxiosError && error.response?.status === 403
}

/** `true` when the API refused a grant because the bundle exceeds the actor (R3). */
export function isGrantExceedsActor(error: unknown): boolean {
  return apiErrorCode(error) === "GRANT_EXCEEDS_ACTOR"
}

/**
 * `true` for the administration rate limit (`429`, 20 requests a minute per client
 * address). The screen issues several requests per view, so a few quick reloads can reach
 * it; the queries retry instead of showing a hard failure.
 */
export function isRateLimited(error: unknown): boolean {
  return error instanceof AxiosError && error.response?.status === 429
}

/** `Retry-After` in milliseconds when the browser was allowed to read it. */
function retryAfterHeaderMs(error: unknown): number | undefined {
  if (!(error instanceof AxiosError)) return undefined
  const headers = error.response?.headers as Record<string, unknown> | undefined
  const header = headers?.["retry-after"]
  const seconds =
    typeof header === "string" ? Number.parseInt(header, 10) : Number.NaN
  if (!Number.isFinite(seconds) || seconds <= 0) return undefined
  return Math.min(seconds, 65) * 1000
}

/**
 * How long to wait before retrying a `429`.
 *
 * The API sends `Retry-After`, but the browser can only read a CORS-exposed response
 * header and the API does not expose this one, so the header is usually invisible here.
 * The fallback is an escalating wait long enough for the 20-per-minute window to move;
 * 5 + 20 + 40 seconds comfortably clears it.
 *
 * TanStack Query calls this with the failure count *before* it increments it (query-core
 * `retryer.js`: `retryDelay(failureCount, error)`, then `failureCount++`), so the first
 * retry arrives as `0`. Clamp rather than subtract one: `Math.min(0, 2) - 1` is `-1`, and
 * the indexed read is then `undefined`, which silently handed the first retry the 40s step
 * and never reached the 5s one.
 */
export function retryDelayMs(failureCount: number, error: unknown): number {
  const fromHeader = retryAfterHeaderMs(error)
  if (fromHeader !== undefined) return fromHeader
  const backoff = [5_000, 20_000, 40_000]
  return backoff[Math.min(failureCount, backoff.length - 1)]
}

/** Retry only a `429`, and only three times. Every other refusal is final. */
export function retryOnRateLimit(
  failureCount: number,
  error: unknown,
): boolean {
  return isRateLimited(error) && failureCount < 3
}

/**
 * The sentence an administration failure shows, told apart from a rate limit.
 *
 * This state is only reached once the retries above are exhausted, so a `429` here must
 * ask for a manual retry rather than promise one the screen will not make.
 */
export function describeAdminError(error: unknown): string {
  if (isRateLimited(error)) {
    return "The administration API is rate limiting this screen (20 requests a minute). Wait a moment, then try again."
  }
  return "The API could not answer. Check your connection and try again."
}
