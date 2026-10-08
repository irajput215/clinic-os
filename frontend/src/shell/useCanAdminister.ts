import { useQuery } from "@tanstack/react-query"
import { MANAGE_USERS, myPermissionsQuery } from "@/data/permissions"
import { currentUserQuery } from "@/lib/session"

/**
 * Whether to offer the administration area: a platform superuser (accounts), or anyone whose known
 * set includes `users:manage`. An account with no organisation can hold no permission. When the set
 * is unknown or failed to load, the entry is shown and the server's `403` is the answer.
 */
export function useCanAdminister(): boolean {
  const me = useQuery(currentUserQuery)
  // Read only when the answer can change what is shown. The `_app` loader has already asked, in
  // parallel with `/users/me` (`routes/_app.tsx`), so this usually reads the cache.
  const permissions = useQuery({
    ...myPermissionsQuery,
    retry: false,
    enabled: Boolean(me.data?.tenant_id) && !me.data?.is_superuser,
  })
  if (me.data?.is_superuser) return true
  if (!me.data?.tenant_id) return false
  // Not shown until the answer is in, so the entry never appears and then vanishes.
  if (permissions.isPending) return false
  if (permissions.data?.known)
    return permissions.data.codes.includes(MANAGE_USERS)
  return true
}
