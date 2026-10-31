import { useQuery } from "@tanstack/react-query"
import { Link, type LinkProps } from "@tanstack/react-router"
import {
  ChevronDown,
  ChevronUp,
  CircleCheck,
  CircleDashed,
  Copy,
  Info,
} from "lucide-react"
import { useState } from "react"
import { toast } from "sonner"
import type { SetupStep } from "@/client/types.gen"
import { Button } from "@/components/ui/button"
import { setupQuery } from "@/data/practice"
import { useCanConfigureClinic, useClinicSlug } from "@/data/useClinic"
import { Card, ErrorState, Pill, SkeletonRows } from "@/design/primitives"

const STEPS: Record<
  SetupStep["key"],
  {
    title: string
    detail: string
    action?: string
    to?: LinkProps["to"]
    search?: LinkProps["search"]
  }
> = {
  clinic_name: {
    title: "Clinic name",
    detail: "How your clinic appears to staff and on the booking page.",
    action: "Set name",
    to: "/settings",
    search: { tab: "clinic" },
  },
  hours: {
    title: "Opening hours and slot length",
    detail: "What the calendar and the booking page offer.",
    action: "Set hours",
    to: "/settings",
    search: { tab: "clinic" },
  },
  team_invited: {
    title: "Invite your team",
    detail:
      "Doctors, nurses and reception each sign in with their own account.",
    action: "Invite staff",
    to: "/admin",
    search: { tab: "staff" },
  },
  prescriber_ready: {
    title: "A prescriber ready to sign",
    detail:
      "Complete at least one doctor's onboarding pack: agreement, AHPRA and prescriber number.",
    action: "Open packs",
    to: "/admin",
    search: { tab: "staff" },
  },
  workflow: {
    title: "Practice settings",
    detail: "How long records are kept.",
    action: "Set retention",
    to: "/settings",
    search: { tab: "practice" },
  },
  consents: {
    title: "Consent documents",
    detail:
      "Privacy, telehealth and treatment consents are published for online applications.",
  },
  permissions_reviewed: {
    title: "Review the permission grid",
    detail: "See what each role may do.",
    action: "Open roles",
    to: "/admin",
    search: { tab: "roles" },
  },
  booking_page: {
    title: "Share your booking page",
    detail: "Patients apply and book here.",
  },
  integrations: {
    title: "Integrations",
    detail:
      "eScripts, Medicare, address search and SMS: not connected, awaiting approval.",
  },
}

const COLLAPSED = "clinic-os.setup.collapsed"

function readCollapsed(): boolean {
  try {
    return window.localStorage.getItem(COLLAPSED) === "1"
  } catch {
    return false
  }
}

/**
 * "Set up your clinic" (docs3 feature 01): for whoever configures the practice, until every required
 * step is done. Every tick comes from the server, which derives it from the clinic's own data, so it
 * can't be ticked by hand and can't drift from the truth.
 */
export function SetupChecklist() {
  const canConfigure = useCanConfigureClinic()
  const setup = useQuery({
    ...setupQuery,
    enabled: canConfigure === true,
    retry: false,
  })
  const slug = useClinicSlug()
  const [collapsed, setCollapsed] = useState(readCollapsed)
  if (canConfigure !== true) return null
  if (setup.isPending)
    return (
      <Card title="Set up your clinic" className="mb-3.5">
        <SkeletonRows rows={3} />
      </Card>
    )
  if (setup.isError)
    return (
      <Card title="Set up your clinic" className="mb-3.5">
        <ErrorState error={setup.error} onRetry={() => setup.refetch()} />
      </Card>
    )
  const {
    steps,
    required_done: done,
    required_total: total,
    ready,
  } = setup.data
  if (ready) return null

  const toggle = () => {
    setCollapsed((now) => {
      try {
        window.localStorage.setItem(COLLAPSED, now ? "0" : "1")
      } catch {
        // Storage unavailable: remember for this visit only.
      }
      return !now
    })
  }
  const bookingUrl = slug ? `${window.location.origin}/book/${slug}` : null

  return (
    <Card
      title="Set up your clinic"
      className="mb-3.5"
      action={
        <Button
          size="sm"
          variant="ghost"
          aria-expanded={!collapsed}
          aria-label={collapsed ? "Show setup steps" : "Hide setup steps"}
          onClick={toggle}
        >
          {collapsed ? <ChevronDown /> : <ChevronUp />}
          {done} of {total} done
        </Button>
      }
    >
      <div
        className="h-1.5 overflow-hidden rounded-full bg-fill"
        role="progressbar"
        aria-label="Required setup steps done"
        aria-valuenow={done}
        aria-valuemin={0}
        aria-valuemax={total}
      >
        <div
          className="h-full rounded-full bg-ok"
          style={{ width: `${(100 * done) / Math.max(total, 1)}%` }}
        />
      </div>
      {collapsed ? null : (
        <ol
          className="mt-3 divide-y divide-line-faint"
          data-testid="setup-steps"
        >
          {steps.map((step) => {
            const meta = STEPS[step.key]
            return (
              <li
                key={step.key}
                className="flex flex-wrap items-center justify-between gap-2 py-2.5"
              >
                <div className="flex min-w-0 items-start gap-2.5">
                  {step.status === "done" ? (
                    <CircleCheck
                      className="mt-0.5 size-4 shrink-0 text-ok"
                      aria-label="Done"
                    />
                  ) : step.status === "informational" ? (
                    <Info
                      className="mt-0.5 size-4 shrink-0 text-stone"
                      aria-label="For information"
                    />
                  ) : (
                    <CircleDashed
                      className="mt-0.5 size-4 shrink-0 text-stone"
                      aria-label="To do"
                    />
                  )}
                  <div className="min-w-0">
                    <p className="text-sm font-medium">
                      {meta.title}
                      {step.status === "optional" ? (
                        <span className="font-normal text-stone">
                          {" "}
                          · optional
                        </span>
                      ) : null}
                    </p>
                    <p className="text-xs text-stone">{meta.detail}</p>
                    {step.key === "booking_page" && bookingUrl ? (
                      <p className="mt-0.5 font-mono text-xs break-all">
                        {bookingUrl}
                      </p>
                    ) : null}
                  </div>
                </div>
                {step.key === "booking_page" && bookingUrl ? (
                  <Button
                    size="sm"
                    variant="outline"
                    onClick={async () => {
                      try {
                        await navigator.clipboard.writeText(bookingUrl)
                        toast.success("Booking link copied")
                      } catch {
                        toast.error("Couldn't copy; select the link instead")
                      }
                    }}
                  >
                    <Copy /> Copy link
                  </Button>
                ) : step.status === "done" ? (
                  <Pill tone="ok">Done</Pill>
                ) : meta.to ? (
                  <Link
                    to={meta.to}
                    search={meta.search}
                    className="inline-flex min-h-11 items-center text-sm font-medium text-clay hover:underline"
                  >
                    {meta.action} →
                  </Link>
                ) : null}
              </li>
            )
          })}
        </ol>
      )}
    </Card>
  )
}
