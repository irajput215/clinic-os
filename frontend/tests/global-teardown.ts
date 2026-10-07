import type { FullConfig } from "@playwright/test"
import { recordRunEnd } from "./pacing"

/** Record when this run ended, so a run straight after it waits out its rate-limit windows. */
export default function globalTeardown(config: FullConfig) {
  const origin = config.projects[0]?.use.baseURL
  if (origin) recordRunEnd(new URL(origin).origin)
}
