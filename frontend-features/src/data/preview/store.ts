import { PatientsService, UsersService } from "@/client"
import type { PatientRead } from "@/client/types.gen"
import { takePendingPublicBookings } from "@/data/booking"
import { clinicToday } from "@/lib/format"
import { type PreviewState, seedPreview } from "./seed"

/**
 * The in-browser preview store: the stand-in backend for features whose module is not merged.
 *
 * It lives in this tab's `sessionStorage`, keyed to the signed-in user, so it never leaks across
 * accounts or tabs, and it is re-seeded each clinic day so "today" stays today. All access is
 * async and goes through `read`/`write`, so the repositories that use it have the same shape as the
 * API-backed ones they will be swapped for.
 */
const KEY = "clinic-os.preview.v2"
let cache: PreviewState | null = null
let loading: Promise<PreviewState> | null = null

const persist = (state: PreviewState) => {
  try {
    window.sessionStorage.setItem(KEY, JSON.stringify(state))
  } catch {
    // Storage blocked: the preview still works for the life of the page.
  }
}

const restore = (userId: string): PreviewState | null => {
  try {
    const raw = window.sessionStorage.getItem(KEY)
    if (!raw) return null
    const state = JSON.parse(raw) as PreviewState
    if (
      state.version !== 2 ||
      state.seededFor !== userId ||
      state.seededOn !== clinicToday()
    )
      return null
    return state
  } catch {
    return null
  }
}

const load = async (): Promise<PreviewState> => {
  const me = (await UsersService.readUserMe()).data
  const restored = restore(me.id)
  if (restored) return restored
  let patients: PatientRead[] = []
  try {
    patients = (await PatientsService.listPatients({ query: { limit: 25 } }))
      .data.data
  } catch {
    // No `patient:read` (or no organisation): nothing patient-linked is seeded.
  }
  const state = seedPreview(me, patients)
  persist(state)
  return state
}

const ensureLoaded = async (): Promise<PreviewState> => {
  if (!cache) {
    loading ??= load().finally(() => {
      loading = null
    })
    cache = await loading
  }
  // Bookings made on the public page in this tab arrive here, the way the API would surface them.
  const arrivals = takePendingPublicBookings()
  if (arrivals.length) {
    cache.appointments.push(...arrivals)
    persist(cache)
  }
  return cache
}

/**
 * A copy of the preview state. Callers never hold a live reference: React Query compares old and new
 * results structurally, and an object mutated in place would compare equal to itself and never
 * re-render (exactly the behaviour of a real API, which always returns fresh objects).
 */
export const readPreview = async (): Promise<PreviewState> =>
  structuredClone(await ensureLoaded())

/** Apply a change to the private state and persist it. Returns a copy of what the mutator returns. */
export const writePreview = async <T>(
  mutate: (state: PreviewState) => T,
): Promise<T> => {
  const state = await ensureLoaded()
  const result = mutate(state)
  persist(state)
  return structuredClone(result)
}

/** Forget the preview (on sign-out), so the next account starts clean. */
export const resetPreview = () => {
  cache = null
  try {
    window.sessionStorage.removeItem(KEY)
  } catch {
    // nothing to clear
  }
}
