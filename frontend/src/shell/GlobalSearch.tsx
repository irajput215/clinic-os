import { keepPreviousData, useQuery } from "@tanstack/react-query"
import { useNavigate } from "@tanstack/react-router"
import { Search } from "lucide-react"
import { useId, useRef, useState } from "react"
import {
  patientName,
  patientQuickFindQuery,
  useSearchTerm,
} from "@/data/patients"
import { formatDate } from "@/lib/format"
import { isForbidden } from "@/lib/http"
import { cn } from "@/lib/utils"

/**
 * Patient quick-find. Asks the server (`POST /patients/search`) once typing pauses, so every patient
 * is findable, not just the first page. The term goes in the request body, never in a URL, so it
 * stays out of browser history and access logs.
 */
export function GlobalSearch() {
  const [term, setTerm] = useState("")
  const [open, setOpen] = useState(false)
  const [active, setActive] = useState(0)
  const listId = useId()
  const navigate = useNavigate()
  const inputRef = useRef<HTMLInputElement>(null)
  const q = useSearchTerm(term)
  const search = useQuery({
    ...patientQuickFindQuery(q),
    enabled: q !== "",
    retry: false,
    placeholderData: keepPreviousData,
  })
  const settled = q === term.trim() && !search.isFetching
  const results = q && search.data ? search.data.data : []

  const go = (id: string) => {
    setOpen(false)
    setTerm("")
    inputRef.current?.blur()
    navigate({ to: "/patients/$patientId", params: { patientId: id } })
  }

  return (
    <div className="relative w-full sm:w-auto">
      <Search className="pointer-events-none absolute top-1/2 left-3 size-3.5 -translate-y-1/2 text-stone-faint" />
      <input
        ref={inputRef}
        id="patient-quick-find"
        name="patient-quick-find"
        type="search"
        role="combobox"
        aria-expanded={open && results.length > 0}
        aria-controls={listId}
        aria-label="Find a patient"
        placeholder="Find a patient"
        autoComplete="off"
        value={term}
        onChange={(e) => {
          setTerm(e.target.value)
          setActive(0)
          setOpen(true)
        }}
        onFocus={() => setOpen(true)}
        onBlur={() => setTimeout(() => setOpen(false), 120)}
        onKeyDown={(e) => {
          if (e.key === "ArrowDown") {
            e.preventDefault()
            setActive((i) => Math.min(i + 1, results.length - 1))
          } else if (e.key === "ArrowUp") {
            e.preventDefault()
            setActive((i) => Math.max(i - 1, 0))
          } else if (e.key === "Enter" && results[active]) {
            e.preventDefault()
            go(results[active].id)
          } else if (e.key === "Escape") {
            setOpen(false)
          }
        }}
        className="h-[38px] w-full rounded-full border border-line bg-paper pr-3 pl-[34px] text-[14px] outline-none transition-[width,border-color] placeholder:text-stone-faint focus:border-clay max-lg:h-11 max-lg:text-[16px] sm:w-[214px] sm:focus:w-[280px]"
      />
      {open && term.trim() ? (
        <div
          id={listId}
          role="listbox"
          className="absolute top-[calc(100%+6px)] right-0 z-30 w-[300px] max-w-[calc(100vw-2rem)] overflow-hidden rounded-inner border border-line bg-paper shadow-pop"
        >
          {search.isError && settled ? (
            <p className="px-3.5 py-3 text-sm text-stone" role="status">
              {isForbidden(search.error)
                ? "Patient search is not available to your role."
                : "Search is unavailable right now. Try again in a moment."}
            </p>
          ) : results.length === 0 ? (
            <p className="px-3.5 py-3 text-sm text-stone" role="status">
              {settled ? `No patient matches “${term.trim()}”.` : "Searching…"}
            </p>
          ) : (
            results.map((p, i) => (
              <button
                type="button"
                role="option"
                aria-selected={i === active}
                key={p.id}
                onMouseDown={(e) => e.preventDefault()}
                onClick={() => go(p.id)}
                onMouseEnter={() => setActive(i)}
                className={cn(
                  "flex w-full items-baseline justify-between gap-3 px-3.5 py-2.5 text-left text-sm max-lg:min-h-11 max-lg:items-center",
                  i === active && "bg-oat",
                )}
              >
                <span className="font-medium">{patientName(p)}</span>
                <span className="font-mono text-[11.5px] text-stone">
                  {formatDate(p.date_of_birth)}
                </span>
              </button>
            ))
          )}
        </div>
      ) : null}
    </div>
  )
}
