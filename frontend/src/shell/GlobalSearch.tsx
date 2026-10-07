import { useQuery } from "@tanstack/react-query"
import { useNavigate } from "@tanstack/react-router"
import { Search } from "lucide-react"
import { useId, useMemo, useRef, useState } from "react"
import { patientName, patientsQuery } from "@/data/patients"
import { formatDate, patientRef } from "@/lib/format"
import { cn } from "@/lib/utils"

/**
 * Patient quick-find. The patients API has no search parameter yet, so this filters the loaded page
 * (up to 25) in memory; nothing typed here is sent anywhere, which also keeps names out of URLs and
 * access logs.
 */
export function GlobalSearch() {
  const [term, setTerm] = useState("")
  const [open, setOpen] = useState(false)
  const [active, setActive] = useState(0)
  const listId = useId()
  const navigate = useNavigate()
  const inputRef = useRef<HTMLInputElement>(null)
  const { data } = useQuery({ ...patientsQuery, enabled: open, retry: false })

  const results = useMemo(() => {
    const q = term.trim().toLowerCase()
    if (!q || !data) return []
    return data.data
      .filter((p) =>
        `${patientName(p)} ${p.given_name} ${patientRef(p.id)}`
          .toLowerCase()
          .includes(q),
      )
      .slice(0, 6)
  }, [term, data])

  const go = (id: string) => {
    setOpen(false)
    setTerm("")
    inputRef.current?.blur()
    navigate({ to: "/patients/$patientId", params: { patientId: id } })
  }

  return (
    <div className="relative">
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
        className="h-[38px] w-[150px] rounded-full border border-line bg-paper pr-3 pl-[34px] text-[14px] outline-none transition-[width,border-color] placeholder:text-stone-faint focus:w-[240px] focus:border-clay sm:w-[214px] sm:focus:w-[280px]"
      />
      {open && term.trim() ? (
        <div
          id={listId}
          role="listbox"
          className="absolute top-[calc(100%+6px)] right-0 z-30 w-[300px] overflow-hidden rounded-inner border border-line bg-paper shadow-pop"
        >
          {results.length === 0 ? (
            <p className="px-3.5 py-3 text-sm text-stone">
              No patient matches “{term.trim()}”.
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
                  "flex w-full items-baseline justify-between gap-3 px-3.5 py-2.5 text-left text-sm",
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
