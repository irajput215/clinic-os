import { useQuery } from "@tanstack/react-query"
import { Link, type LinkProps } from "@tanstack/react-router"
import { ArrowRight, X } from "lucide-react"
import { useState } from "react"
import { Button } from "@/components/ui/button"
import {
  describeMissing,
  needsAcknowledgement,
  onboardingPackQuery,
  sopsQuery,
} from "@/data/onboarding"
import { myPermissionsQuery } from "@/data/permissions"
import { Card, Pill } from "@/design/primitives"
import { OnboardingPackDialog } from "@/features/admin/OnboardingPackDialog"

interface Line {
  text: string
  to?: LinkProps["to"]
  search?: LinkProps["search"]
}

/**
 * The manual's day-one quick-starts, by role. Only lines whose screen exists are listed; a line for a
 * screen not built yet is left out rather than shown broken (R3).
 */
const QUICK_STARTS: Array<{ roles: string[]; title: string; lines: Line[] }> = [
  {
    roles: ["PRACTICE_OWNER"],
    title: "Practice manager",
    lines: [
      {
        text: "Set the clinic's details and hours",
        to: "/settings",
        search: { tab: "clinic" },
      },
      { text: "Invite your staff", to: "/admin", search: { tab: "staff" } },
      {
        text: "Check the permission grid",
        to: "/admin",
        search: { tab: "roles" },
      },
      {
        text: "Complete each doctor's onboarding pack",
        to: "/admin",
        search: { tab: "staff" },
      },
      { text: "Publish your SOPs", to: "/sops" },
    ],
  },
  {
    roles: ["DOCTOR", "AUTHORISED_PRESCRIBER"],
    title: "Doctor",
    lines: [
      { text: "See today's consults", to: "/calendar" },
      { text: "Script queue: Review & sign", to: "/scripts" },
      { text: "Check a patient's TGA approval", to: "/approvals" },
    ],
  },
  {
    roles: ["NURSE"],
    title: "Nurse",
    lines: [
      { text: "Open the script queue", to: "/scripts" },
      { text: "Stage a draft with the triage outcome", to: "/scripts" },
      { text: "Check the approval before you stage", to: "/approvals" },
    ],
  },
  {
    roles: ["ADMINISTRATOR"],
    title: "Reception and admin",
    lines: [
      { text: "Open today's calendar", to: "/calendar" },
      { text: "Patients: review online applications", to: "/patients" },
      { text: "Press / anywhere to find a patient" },
      { text: "Add a new patient", to: "/patients" },
    ],
  },
]

const storageKey = (userId: string) =>
  `clinic-os.first-hour.dismissed.${userId}`

function readDismissed(userId: string): boolean {
  try {
    return window.localStorage.getItem(storageKey(userId)) === "1"
  } catch {
    return false
  }
}

/** "Your first hour" (docs3 feature 02, R3, R4): one checklist per role the person holds. */
export function FirstHourCard({ userId }: { userId: string }) {
  const [dismissed, setDismissed] = useState(() => readDismissed(userId))
  const [packOpen, setPackOpen] = useState(false)
  const permissions = useQuery(myPermissionsQuery)
  const roles: readonly string[] = permissions.data?.known
    ? permissions.data.roleCodes
    : []
  const prescriber = roles.some(
    (r) => r === "DOCTOR" || r === "AUTHORISED_PRESCRIBER",
  )
  const pack = useQuery({
    ...onboardingPackQuery(userId),
    enabled: prescriber && !dismissed,
    retry: false,
  })
  const sops = useQuery({ ...sopsQuery, enabled: !dismissed, retry: false })
  const waiting = (sops.data ?? []).filter(needsAcknowledgement).length
  const cards = QUICK_STARTS.filter((q) =>
    q.roles.some((r) => roles.includes(r)),
  )
  if (dismissed || cards.length === 0) return null

  const dismiss = () => {
    try {
      window.localStorage.setItem(storageKey(userId), "1")
    } catch {
      // Private mode or blocked storage: hide it for this visit only.
    }
    setDismissed(true)
  }

  return (
    <Card
      title="Your first hour"
      className="mb-3.5"
      action={
        <Button
          size="sm"
          variant="ghost"
          aria-label="Hide your first hour"
          onClick={dismiss}
        >
          <X /> Hide
        </Button>
      }
    >
      <div className="grid gap-5 md:grid-cols-2" data-testid="first-hour">
        {cards.map((card) => (
          <section key={card.title}>
            <h3 className="mb-1.5 text-sm font-semibold">{card.title}</h3>
            <ol className="space-y-0.5 text-sm">
              {card.lines.map((line) => (
                <li key={line.text}>
                  {line.to ? (
                    <Link
                      to={line.to}
                      search={line.search}
                      className="flex min-h-11 items-center gap-1.5 text-ink hover:text-clay"
                    >
                      <ArrowRight className="size-3.5 shrink-0 text-stone" />
                      {line.text}
                    </Link>
                  ) : (
                    <span className="flex min-h-11 items-center gap-1.5 text-stone">
                      <ArrowRight className="size-3.5 shrink-0" />
                      {line.text}
                    </span>
                  )}
                </li>
              ))}
            </ol>
          </section>
        ))}
        {prescriber && pack.data ? (
          <section>
            <h3 className="mb-1.5 text-sm font-semibold">
              Your onboarding pack{" "}
              {pack.data.pack_complete ? (
                <Pill tone="ok">Complete</Pill>
              ) : (
                <Pill tone="warn">Incomplete</Pill>
              )}
            </h3>
            {pack.data.pack_complete ? (
              <p className="text-sm text-stone">
                You're ready to sign scripts.
              </p>
            ) : (
              <ul className="list-disc pl-5 text-sm text-stone">
                {pack.data.missing.map((m) => (
                  <li key={m}>
                    {describeMissing(
                      m,
                      Object.fromEntries(
                        pack.data.sops.map((s) => [s.id, s.title]),
                      ),
                    )}
                  </li>
                ))}
              </ul>
            )}
            <Button
              size="sm"
              variant="outline"
              className="mt-2"
              onClick={() => setPackOpen(true)}
            >
              View my pack
            </Button>
          </section>
        ) : null}
        {waiting ? (
          <section>
            <h3 className="mb-1.5 text-sm font-semibold">SOPs</h3>
            <Link
              to="/sops"
              className="flex min-h-11 items-center gap-1.5 text-sm hover:text-clay"
            >
              <ArrowRight className="size-3.5 shrink-0 text-stone" />
              {waiting} SOP{waiting === 1 ? "" : "s"} waiting for your
              acknowledgement
            </Link>
          </section>
        ) : null}
      </div>
      {packOpen ? (
        <OnboardingPackDialog userId={userId} open onOpenChange={setPackOpen} />
      ) : null}
    </Card>
  )
}
