import { Link, type LinkProps } from "@tanstack/react-router"
import { FlaskConical, Lock, TriangleAlert } from "lucide-react"
import type { ReactNode } from "react"
import { Button } from "@/components/ui/button"
import { apiRequestId, describeError, isForbidden } from "@/lib/http"
import { cn } from "@/lib/utils"

/** Serif page title, muted one-line subtitle, actions on the right, hairline below. */
export function PageHeader({
  title,
  subtitle,
  actions,
}: {
  title: string
  subtitle?: ReactNode
  actions?: ReactNode
}) {
  return (
    <header className="mb-6 flex flex-wrap items-end justify-between gap-4 border-line border-b pb-5">
      <div className="min-w-0">
        <h1 className="font-serif text-[31px] leading-[1.1] font-medium tracking-[-0.015em] text-ink">
          {title}
        </h1>
        {subtitle ? (
          <p className="mt-1.5 max-w-[640px] text-sm text-stone">{subtitle}</p>
        ) : null}
      </div>
      {actions ? (
        <div className="flex items-center gap-2">{actions}</div>
      ) : null}
    </header>
  )
}

export function Card({
  title,
  action,
  children,
  className,
  bodyClassName,
}: {
  title?: ReactNode
  action?: ReactNode
  children: ReactNode
  className?: string
  bodyClassName?: string
}) {
  return (
    <section
      className={cn(
        "min-w-0 rounded-card border border-line bg-paper px-5 py-[18px] shadow-card",
        className,
      )}
    >
      {title || action ? (
        <div className="mb-3.5 flex items-baseline justify-between gap-3">
          {title ? (
            <h2 className="text-base font-semibold text-ink">{title}</h2>
          ) : (
            <span />
          )}
          {action}
        </div>
      ) : null}
      <div className={bodyClassName}>{children}</div>
    </section>
  )
}

/** A clay "Open calendar →" style link for a card header. */
export function CardLink(props: LinkProps & { children: ReactNode }) {
  return (
    <Link
      {...props}
      className="text-sm font-medium text-clay underline-offset-4 hover:text-clay-hover hover:underline"
    />
  )
}

export function StatCard({
  value,
  label,
  sub,
  subTone = "ink",
  to,
}: {
  value: ReactNode
  label: string
  sub?: ReactNode
  subTone?: "ink" | "danger" | "ok"
  to?: LinkProps["to"]
}) {
  const body = (
    <>
      <div className="font-serif text-[30px] leading-[1.15] font-medium text-ink tabular-nums">
        {value}
      </div>
      <div className="mt-0.5 text-xs font-medium tracking-[0.02em] text-stone">
        {label}
      </div>
      {sub ? (
        <div
          className={cn(
            "mt-[3px] text-xs",
            subTone === "danger" && "text-danger",
            subTone === "ok" && "text-ok",
          )}
        >
          {sub}
        </div>
      ) : null}
    </>
  )
  const cls =
    "block min-w-0 rounded-card border border-line bg-paper px-4 py-3.5 shadow-card transition-[border-color,box-shadow,transform] duration-150"
  return to ? (
    <Link
      to={to}
      className={cn(
        cls,
        "hover:-translate-y-px hover:border-stone-faint hover:shadow-pop",
      )}
    >
      {body}
    </Link>
  ) : (
    <div className={cls}>{body}</div>
  )
}

export type Tone =
  | "neutral"
  | "ok"
  | "warn"
  | "danger"
  | "info"
  | "clay"
  | "purple"

const TONES: Record<Tone, string> = {
  neutral: "bg-fill text-stone",
  ok: "bg-ok-tint text-ok-deep",
  warn: "bg-warn-tint text-warn-deep",
  danger: "bg-danger-tint text-danger-deep",
  info: "bg-info-tint text-info-deep",
  clay: "bg-clay-tint text-clay-deep",
  purple: "bg-purple-tint text-purple-deep",
}

export function Pill({
  tone = "neutral",
  children,
  className,
  title,
}: {
  tone?: Tone
  children: ReactNode
  className?: string
  title?: string
}) {
  return (
    <span
      title={title}
      className={cn(
        "inline-flex shrink-0 items-center gap-1 rounded-full px-2.5 py-0.5 text-[11.5px] leading-[1.6] font-semibold tracking-[0.01em] whitespace-nowrap",
        TONES[tone],
        className,
      )}
    >
      {children}
    </span>
  )
}

/** Monospace chip for references, tokens, dates and amounts. */
export function Mono({
  children,
  className,
}: {
  children: ReactNode
  className?: string
}) {
  return (
    <span
      className={cn(
        "font-mono text-[12.5px] tracking-[0.01em] whitespace-nowrap",
        className,
      )}
    >
      {children}
    </span>
  )
}

export function EmptyState({
  title,
  body,
  action,
}: {
  title: string
  body?: ReactNode
  action?: ReactNode
}) {
  return (
    <div className="flex flex-col items-center gap-2 px-6 py-10 text-center">
      <div className="mb-1 size-1.5 rounded-full bg-stone-faint" />
      <p className="text-sm font-medium text-ink">{title}</p>
      {body ? <p className="max-w-[380px] text-sm text-stone">{body}</p> : null}
      {action ? <div className="mt-2">{action}</div> : null}
    </div>
  )
}

/** A failed read: `403` explains the role boundary, anything else offers a retry. */
export function ErrorState({
  error,
  onRetry,
}: {
  error: unknown
  onRetry?: () => void
}) {
  if (isForbidden(error))
    return (
      <div className="flex items-start gap-3 rounded-inner border border-line bg-oat px-4 py-3.5 text-sm text-stone">
        <Lock className="mt-0.5 size-4 shrink-0" />
        <p>
          <span className="font-semibold text-ink">
            Not available to your role.
          </span>{" "}
          Ask your practice manager if you need access.
        </p>
      </div>
    )
  return (
    <div className="flex items-start justify-between gap-3 rounded-inner border border-danger/25 bg-danger-tint px-4 py-3.5 text-sm text-danger-deep">
      <div className="flex items-start gap-3">
        <TriangleAlert className="mt-0.5 size-4 shrink-0" />
        <p>
          {describeError(error)}
          {apiRequestId(error) ? (
            <span className="mt-1 block font-mono text-[11px] opacity-75">
              Reference {apiRequestId(error)}
            </span>
          ) : null}
        </p>
      </div>
      {onRetry ? (
        <Button size="sm" variant="outline" onClick={onRetry}>
          Try again
        </Button>
      ) : null}
    </div>
  )
}

/** Shown on every screen that reads preview data, so it is never mistaken for clinical data. */
export function PreviewBanner({
  what,
  standalone = false,
}: {
  what: string
  /** `what` already says everything (the public page); skip the backend explanation. */
  standalone?: boolean
}) {
  return (
    <div
      role="note"
      className="mb-5 flex items-start gap-3 rounded-inner border border-dashed border-warn/40 bg-warn-tint/60 px-4 py-3 text-[13px] text-warn-deep"
    >
      <FlaskConical className="mt-0.5 size-4 shrink-0" />
      <p>
        <span className="font-semibold">Preview data.</span> {what}
        {standalone
          ? null
          : " The backend module for this isn't merged yet, so changes here stay in this browser tab."}
      </p>
    </div>
  )
}

export function SkeletonRows({ rows = 4 }: { rows?: number }) {
  return (
    <div
      className="space-y-2.5"
      role="status"
      aria-busy="true"
      aria-label="Loading"
    >
      {Array.from({ length: rows }, (_, i) => (
        <div
          key={i}
          className="h-11 animate-pulse rounded-inner bg-fill/70"
          style={{ animationDelay: `${i * 80}ms` }}
        />
      ))}
    </div>
  )
}

export function Field({
  label,
  htmlFor,
  error,
  hint,
  children,
  className,
}: {
  label: string
  htmlFor?: string
  error?: string
  hint?: string
  children: ReactNode
  className?: string
}) {
  return (
    <div className={cn("min-w-0", className)}>
      <label htmlFor={htmlFor} className="field-label">
        {label}
      </label>
      {children}
      {error ? (
        <p className="mt-1 text-xs text-danger" role="alert">
          {error}
        </p>
      ) : hint ? (
        <p className="mt-1 text-xs text-stone-faint">{hint}</p>
      ) : null}
    </div>
  )
}

/** Route-level pending and error screens, so every page loads and fails the same way. */
export function PagePending() {
  return (
    <div aria-busy="true">
      <div className="mb-6 border-line border-b pb-5">
        <div className="h-8 w-64 animate-pulse rounded-btn bg-fill" />
        <div className="mt-2.5 h-4 w-96 max-w-full animate-pulse rounded bg-fill/70" />
      </div>
      <SkeletonRows rows={5} />
    </div>
  )
}

export function PageError({
  error,
  reset,
}: {
  error: unknown
  reset?: () => void
}) {
  return (
    <div className="pt-4">
      <ErrorState error={error} onRetry={reset} />
    </div>
  )
}
