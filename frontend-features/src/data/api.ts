import { client } from "@/client/client.gen"

/**
 * A typed call for API routes that exist on a backend branch but are not in the generated client yet.
 * It goes through the same configured client (base URL, bearer auth, error handling) as the
 * generated SDK. Once a route is in openapi.json, call its generated `XService` method instead.
 */
const SECURITY = [{ scheme: "bearer", type: "http" }] as const

export const apiCall = async <T>(
  method: "GET" | "POST" | "PATCH",
  url: string,
  options: {
    path?: Record<string, string>
    query?: Record<string, string | number | undefined>
    body?: unknown
  } = {},
): Promise<T> => {
  const result = await client.request({
    method,
    url,
    security: [...SECURITY],
    throwOnError: true,
    ...options,
  })
  return result.data as T
}
