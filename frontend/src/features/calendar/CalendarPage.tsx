import { useQuery, useSuspenseQuery } from "@tanstack/react-query"
import { useNavigate } from "@tanstack/react-router"
import { ChevronLeft, ChevronRight, Plus } from "lucide-react"
import { useMemo, useState } from "react"
import { Button } from "@/components/ui/button"
import {
  appointmentsForDatesQuery,
  practitionersQuery,
} from "@/data/appointments"
import { APPOINTMENT_TYPES, type Appointment } from "@/data/types"
import { EmptyState, ErrorState, PageHeader } from "@/design/primitives"
import { AppointmentStatusPill } from "@/features/shared/pills"
import { clinicDateOf, clinicMinutesOfDay } from "@/lib/clinic-time"
import { addDays, clinicToday, formatDate, formatTime } from "@/lib/format"
import { cn } from "@/lib/utils"
import {
  AppointmentDialog,
  NewAppointmentDialog,
  type SlotPrefill,
} from "./AppointmentDialogs"

const DAY_START = 8 * 60
const DAY_END = 18 * 60
const HOUR_PX = 96
const px = (minutes: number) => ((minutes - DAY_START) / 60) * HOUR_PX

const weekdayShort = new Intl.DateTimeFormat("en-AU", {
  weekday: "short",
  timeZone: "UTC",
})
const dayNum = (iso: string) => Number(iso.slice(8, 10))

/** Monday of the week containing `iso`. */
const weekStart = (iso: string) => {
  const dow = new Date(`${iso}T12:00:00Z`).getUTCDay()
  return addDays(iso, dow === 0 ? -6 : 1 - dow)
}

const TONE_BLOCK: Record<Appointment["status"], string> = {
  BOOKED: "border-l-stone-faint bg-paper",
  CONFIRMED: "border-l-purple bg-purple-tint/60",
  ARRIVED: "border-l-info bg-info-tint/70",
  COMPLETED: "border-l-ok bg-ok-tint/70",
  CANCELLED: "border-l-danger bg-danger-tint/50 opacity-60 line-through",
  NO_SHOW: "border-l-warn bg-warn-tint/60 opacity-70",
}

export function CalendarPage({
  date,
  view,
}: {
  date: string
  view: "day" | "week"
}) {
  const navigate = useNavigate({ from: "/calendar" })
  const dates = useMemo(
    () =>
      view === "day"
        ? [date]
        : Array.from({ length: 5 }, (_, i) => addDays(weekStart(date), i)),
    [date, view],
  )
  const { data: practitioners } = useSuspenseQuery(practitionersQuery)
  const schedule = useQuery(appointmentsForDatesQuery(dates))
  const appointments = schedule.data ?? []
  const [prefill, setPrefill] = useState<SlotPrefill | null>(null)
  const [selected, setSelected] = useState<Appointment | null>(null)
  const today = clinicToday()

  const step = view === "day" ? 1 : 7
  const go = (to: string) => navigate({ search: { date: to, view } })
  const live = appointments.filter((a) => a.status !== "CANCELLED")

  return (
    <>
      <PageHeader
        title="Calendar"
        subtitle={
          schedule.isPending
            ? "Loading appointments…"
            : `${live.length} appointment${live.length === 1 ? "" : "s"} ${view === "day" ? `on ${formatDate(date)}` : `in the week of ${formatDate(dates[0])}`}`
        }
        actions={
          <Button
            disabled={practitioners.length === 0}
            onClick={() =>
              setPrefill({
                practitionerId: practitioners[0]?.id ?? "",
                date,
                time: "09:00",
              })
            }
          >
            <Plus /> New appointment
          </Button>
        }
      />

      <div className="mb-4 flex flex-wrap items-center gap-2">
        <div className="flex items-center rounded-btn border border-line bg-paper">
          <button
            type="button"
            aria-label="Previous"
            onClick={() => go(addDays(date, -step))}
            className="grid size-9 place-items-center text-stone hover:text-ink"
          >
            <ChevronLeft className="size-4" />
          </button>
          <button
            type="button"
            onClick={() => go(today)}
            className="h-9 border-line border-x px-3 text-[13px] font-semibold hover:bg-oat"
          >
            Today
          </button>
          <button
            type="button"
            aria-label="Next"
            onClick={() => go(addDays(date, step))}
            className="grid size-9 place-items-center text-stone hover:text-ink"
          >
            <ChevronRight className="size-4" />
          </button>
        </div>
        <div className="font-serif text-lg font-medium">
          {view === "day"
            ? formatDate(date)
            : `${formatDate(dates[0])} – ${formatDate(dates[4])}`}
        </div>
        <div
          className="ml-auto flex rounded-full border border-line bg-paper p-0.5"
          role="tablist"
        >
          {(["day", "week"] as const).map((v) => (
            <button
              key={v}
              type="button"
              role="tab"
              aria-selected={view === v}
              onClick={() => navigate({ search: { date, view: v } })}
              className={cn(
                "rounded-full px-3.5 py-1 text-xs font-semibold capitalize transition-colors",
                view === v ? "bg-clay text-white" : "text-stone hover:text-ink",
              )}
            >
              {v}
            </button>
          ))}
        </div>
      </div>

      {schedule.isError ? (
        <div className="mb-4">
          <ErrorState
            error={schedule.error}
            onRetry={() => void schedule.refetch()}
          />
        </div>
      ) : null}

      {view === "day" ? (
        <DayGrid
          date={date}
          practitioners={practitioners}
          appointments={appointments}
          onSlot={(practitionerId, time) =>
            setPrefill({ practitionerId, date, time })
          }
          onSelect={setSelected}
        />
      ) : (
        <div className="grid gap-3 md:grid-cols-5">
          {dates.map((d) => {
            const items = appointments.filter(
              (a) => clinicDateOf(a.starts_at) === d,
            )
            return (
              <section
                key={d}
                className={cn(
                  "min-w-0 rounded-card border border-line bg-paper p-3 shadow-card",
                  d === today && "border-clay/50 ring-1 ring-clay/20",
                )}
              >
                <button
                  type="button"
                  onClick={() => navigate({ search: { date: d, view: "day" } })}
                  className="mb-2 flex w-full items-baseline gap-2 text-left"
                >
                  <span className="text-2xs font-semibold tracking-[0.08em] text-stone-faint uppercase">
                    {weekdayShort.format(new Date(`${d}T12:00:00Z`))}
                  </span>
                  <span
                    className={cn(
                      "font-serif text-xl",
                      d === today && "text-clay",
                    )}
                  >
                    {dayNum(d)}
                  </span>
                </button>
                {items.length === 0 ? (
                  <p className="py-4 text-center text-xs text-stone-faint">
                    No bookings
                  </p>
                ) : (
                  <ul className="space-y-1.5">
                    {items.map((a) => (
                      <li key={a.id}>
                        <button
                          type="button"
                          onClick={() => setSelected(a)}
                          className={cn(
                            "w-full rounded-chip border-l-[3px] px-2 py-1.5 text-left text-xs hover:brightness-[0.97]",
                            TONE_BLOCK[a.status],
                          )}
                        >
                          <span className="font-mono text-[11px] text-stone">
                            {formatTime(a.starts_at)}
                          </span>{" "}
                          <span className="font-semibold">
                            {a.patient_name}
                          </span>
                          <span className="block truncate text-stone">
                            {
                              practitioners.find(
                                (p) => p.id === a.practitioner_id,
                              )?.name
                            }
                          </span>
                        </button>
                      </li>
                    ))}
                  </ul>
                )}
              </section>
            )
          })}
        </div>
      )}

      {prefill ? (
        <NewAppointmentDialog
          open
          onOpenChange={(open) => !open && setPrefill(null)}
          practitioners={practitioners}
          prefill={prefill}
        />
      ) : null}
      <AppointmentDialog
        appointment={selected}
        practitioner={practitioners.find(
          (p) => p.id === selected?.practitioner_id,
        )}
        onOpenChange={(open) => !open && setSelected(null)}
      />
    </>
  )
}

function DayGrid({
  date,
  practitioners,
  appointments,
  onSlot,
  onSelect,
}: {
  date: string
  practitioners: Array<{ id: string; name: string; title: string }>
  appointments: Appointment[]
  onSlot: (practitionerId: string, time: string) => void
  onSelect: (a: Appointment) => void
}) {
  const hours = Array.from(
    { length: (DAY_END - DAY_START) / 60 },
    (_, i) => DAY_START / 60 + i,
  )
  const height = px(DAY_END)
  const nowMin =
    clinicDateOf(new Date().toISOString()) === date
      ? clinicMinutesOfDay(new Date().toISOString())
      : null

  if (practitioners.length === 0)
    return (
      <div className="rounded-card border border-line bg-paper shadow-card">
        <EmptyState
          title="No one to book with yet."
          body="Practitioners are staff holding the Doctor, Authorised Prescriber or Nurse role. Give someone one of those roles in Administration to open their column."
        />
      </div>
    )

  return (
    <div className="overflow-x-auto rounded-card border border-line bg-paper shadow-card">
      <div
        className="grid min-w-[760px]"
        style={{
          gridTemplateColumns: `56px repeat(${practitioners.length}, minmax(140px, 1fr))`,
        }}
      >
        <div className="sticky left-0 z-10 border-line border-b bg-paper" />
        {practitioners.map((p) => (
          <div key={p.id} className="border-line border-b border-l px-3 py-2.5">
            <div className="truncate text-[13.5px] font-semibold">{p.name}</div>
            <div className="truncate text-xs text-stone">{p.title}</div>
          </div>
        ))}

        <div
          className="relative sticky left-0 z-10 bg-paper"
          style={{ height }}
        >
          {hours.map((h) => (
            <div
              key={h}
              className="absolute right-2 -translate-y-1/2 font-mono text-[10.5px] text-stone-faint"
              style={{ top: px(h * 60) }}
            >
              {h > DAY_START / 60 ? `${String(h).padStart(2, "0")}:00` : ""}
            </div>
          ))}
        </div>

        {practitioners.map((p) => {
          const mine = appointments.filter((a) => a.practitioner_id === p.id)
          return (
            <div
              key={p.id}
              className="relative border-line border-l"
              style={{ height }}
            >
              {hours.map((h) => (
                <div
                  key={h}
                  className="absolute inset-x-0 border-line-faint border-t"
                  style={{ top: px(h * 60) }}
                />
              ))}
              {Array.from({ length: (DAY_END - DAY_START) / 15 }, (_, i) => {
                const m = DAY_START + i * 15
                const time = `${String(Math.floor(m / 60)).padStart(2, "0")}:${String(m % 60).padStart(2, "0")}`
                return (
                  <button
                    key={time}
                    type="button"
                    aria-label={`Book ${p.name} at ${time}`}
                    onClick={() => onSlot(p.id, time)}
                    className="absolute inset-x-0 opacity-0 transition-opacity hover:bg-clay-tint/50 hover:opacity-100 focus-visible:opacity-100"
                    style={{ top: px(m), height: HOUR_PX / 4 }}
                  />
                )
              })}
              {mine.map((a) => {
                const start = clinicMinutesOfDay(a.starts_at)
                const end = clinicMinutesOfDay(a.ends_at)
                return (
                  <button
                    key={a.id}
                    type="button"
                    onClick={() => onSelect(a)}
                    className={cn(
                      "absolute inset-x-1 z-[1] overflow-hidden rounded-chip border border-line border-l-[3px] px-2 py-1 text-left text-xs shadow-card hover:shadow-pop",
                      TONE_BLOCK[a.status],
                    )}
                    style={{
                      top: px(start) + 1,
                      height: Math.max(px(end) - px(start) - 2, 22),
                    }}
                  >
                    <div className="flex items-center justify-between gap-1">
                      <span className="truncate font-semibold">
                        {a.patient_name}
                      </span>
                      <span className="font-mono text-[10.5px] text-stone">
                        {formatTime(a.starts_at)}
                      </span>
                    </div>
                    <div className="truncate text-stone">
                      {APPOINTMENT_TYPES[a.type].label}
                    </div>
                  </button>
                )
              })}
              {nowMin !== null && nowMin >= DAY_START && nowMin <= DAY_END ? (
                <div
                  className="pointer-events-none absolute inset-x-0 z-[2] h-px bg-clay"
                  style={{ top: px(nowMin) }}
                />
              ) : null}
            </div>
          )
        })}
      </div>
      <div className="flex flex-wrap gap-2 border-line border-t px-3 py-2.5">
        {(["BOOKED", "CONFIRMED", "ARRIVED", "COMPLETED"] as const).map((s) => (
          <AppointmentStatusPill key={s} status={s} />
        ))}
        <span className="ml-auto text-xs text-stone-faint">
          Click an empty slot to book
        </span>
      </div>
    </div>
  )
}
