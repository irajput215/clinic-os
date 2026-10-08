#!/usr/bin/env node
/**
 * The bundle budget (docs2/architecture.md, "Speed measures"). Run after `bun run build`:
 *
 *   bun run --filter frontend check:budget      (or: node frontend/scripts/check-bundle-budget.mjs)
 *
 * It reads the build the backend serves (backend/app/frontend, or the directory given as the first
 * argument) and fails when a budget is exceeded.
 * Sizes are gzip at zlib's default level, which is close to what a CDN edge sends; the build also
 * writes Brotli copies, which are smaller still.
 *
 * - Entry: the one `<script type="module">` in index.html: the app's bootstrap and route table.
 *   React is split into its own long-cached chunk (vite.config.ts), so this alone says little.
 * - Initial: the entry plus every `<link rel="modulepreload">`, i.e. all the JavaScript a cold load
 *   of any screen fetches before it can render. Splitting the entry differently cannot hide bytes
 *   from this number.
 * - Any other chunk: loaded per route or on demand.
 * - CSS: the one stylesheet.
 */
import { readdirSync, readFileSync } from "node:fs"
import path from "node:path"
import { fileURLToPath } from "node:url"
import { gzipSync } from "node:zlib"

// Measured 2026-10-08 (m3/frontend-speed): entry 44.5 (React is its own cached chunk), initial
// 145.6, largest lazy chunk 28.6 (zod with react-hook-form, loaded with the first form), CSS 10.8.
// Before that branch: entry 98.3, initial 145.2, CSS 11.3. `initial` is the number that binds.
// The toaster (~8.5 KB) is on the first load on purpose: deferred, it dropped every toast raised
// before it mounted ("Profile saved" on a slow first load, caught by CI).
const BUDGET_KB = {
  entry: 90,
  initial: 150,
  chunk: 35,
  css: 15,
}

const here = path.dirname(fileURLToPath(import.meta.url))
const dist = path.resolve(
  process.argv[2] ?? path.join(here, "../../backend/app/frontend"),
)
const kb = (bytes) => bytes / 1024
const gzipKb = (file) =>
  kb(gzipSync(readFileSync(path.join(dist, file))).length)

let html
try {
  html = readFileSync(path.join(dist, "index.html"), "utf8")
} catch {
  console.error(`No build at ${dist}: run \`bun run build\` first.`)
  process.exit(2)
}

const attr = (pattern) =>
  [...html.matchAll(pattern)].map((m) => m[1].replace(/^\//, ""))
const [entry] = attr(/<script type="module"[^>]*\ssrc="([^"]+)"/g)
const preloaded = attr(/<link rel="modulepreload"[^>]*\shref="([^"]+)"/g)
const stylesheets = attr(/<link rel="stylesheet"[^>]*\shref="([^"]+)"/g)
if (!entry) {
  console.error("index.html has no entry script.")
  process.exit(2)
}

const initialFiles = new Set([entry, ...preloaded])
const chunks = readdirSync(path.join(dist, "assets"))
  .filter((name) => name.endsWith(".js"))
  .map((name) => `assets/${name}`)
  .filter((file) => !initialFiles.has(file))

const failures = []
const row = (label, value, budget) => {
  const over = budget !== undefined && value > budget
  if (over) failures.push(`${label}: ${value.toFixed(1)} KB > ${budget} KB`)
  const limit = budget === undefined ? "" : ` / ${budget} KB`
  console.log(
    `${over ? "OVER" : "  ok"}  ${value.toFixed(1).padStart(6)} KB${limit.padEnd(9)}  ${label}`,
  )
}

const entryKb = gzipKb(entry)
const initialKb = [...initialFiles].reduce((sum, f) => sum + gzipKb(f), 0)
console.log("Bundle budget (gzip):")
row(`entry ${entry}`, entryKb, BUDGET_KB.entry)
row(
  `initial JS (entry + ${preloaded.length} preloaded chunks)`,
  initialKb,
  BUDGET_KB.initial,
)
for (const file of stylesheets) row(file, gzipKb(file), BUDGET_KB.css)
const largest = chunks
  .map((file) => [file, gzipKb(file)])
  .sort((a, b) => b[1] - a[1])
for (const [file, size] of largest) {
  if (size > BUDGET_KB.chunk) row(file, size, BUDGET_KB.chunk)
}
const [top] = largest
if (top) row(`largest lazy chunk ${top[0]}`, top[1], BUDGET_KB.chunk)

if (failures.length) {
  console.error(`\nOver budget:\n  ${failures.join("\n  ")}`)
  console.error(
    "Move what only some screens need out of the entry (route code splitting, a lazy import), or raise the budget in a reviewed change with the reason.",
  )
  process.exit(1)
}
