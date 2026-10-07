import { existsSync, mkdirSync, readFileSync, writeFileSync } from "node:fs"
import { dirname } from "node:path"

/**
 * Back-to-back runs against one backend. The sign-in (20/min) and recovery (5/min) limits are
 * sliding one-minute windows per client address, held by the backend process
 * (`backend/app/core/rate_limit.py`). One run stays inside both, but a second run started straight
 * after it would share the first one's window. So the run records when it ended, and the next run
 * against the same origin waits until that minute has passed before it spends anything.
 */
const MARKER = "playwright/.auth/last-run.json"
const WINDOW_MS = 61_000

interface LastRun {
  origin: string
  endedAt: number
}

export function recordRunEnd(origin: string) {
  mkdirSync(dirname(MARKER), { recursive: true })
  writeFileSync(
    MARKER,
    JSON.stringify({ origin, endedAt: Date.now() } satisfies LastRun),
  )
}

/** How long to wait before this run may spend the previous run's window, in milliseconds. */
export function previousRunWindowLeft(origin: string): number {
  if (!existsSync(MARKER)) return 0
  try {
    const last = JSON.parse(readFileSync(MARKER, "utf8")) as LastRun
    if (last.origin !== origin) return 0
    return Math.max(0, last.endedAt + WINDOW_MS - Date.now())
  } catch {
    return 0
  }
}
