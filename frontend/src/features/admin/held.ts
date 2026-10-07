import { useQuery } from "@tanstack/react-query"
import { useMemo } from "react"
import { userPermissionsQuery } from "@/data/admin"
import { myPermissionsQuery } from "@/data/permissions"

/**
 * The signed-in account's own permission codes, for the advisory grantability reading (R3).
 * Prefers `GET /users/me/permissions`; until that route is merged, reads the same set through
 * `GET /users/{id}/permissions`, which an administrator may call. `undefined` while unknown.
 */
export function useHeldCodes(meId: string): readonly string[] | undefined {
  const mine = useQuery(myPermissionsQuery)
  const fallback = useQuery({
    ...userPermissionsQuery(meId),
    enabled: mine.data?.known === false || mine.isError,
  })
  const fallbackCodes = useMemo(
    () => fallback.data?.permissions.map((p) => p.code),
    [fallback.data],
  )
  if (mine.data?.known) return mine.data.codes
  return fallbackCodes
}
