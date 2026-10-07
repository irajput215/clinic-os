import { CircleCheck } from "lucide-react"
import type { ReactNode, Ref } from "react"
import { apiRequestId } from "@/lib/http"
import { cn } from "@/lib/utils"
import { BrandMark } from "@/shell/BrandMark"

/**
 * The public card every signed-out page shares: sign in, organisation signup, password recovery
 * and reset. One backdrop, one card, one footer, so the four read as one place.
 */
export function AuthLayout({
  children,
  className,
}: {
  children: ReactNode
  className?: string
}) {
  return (
    <div className="backdrop-pattern flex min-h-dvh items-center justify-center p-6 max-sm:px-4">
      <main
        className={cn(
          "w-full max-w-[400px] animate-rise rounded-[18px] border border-line bg-paper/95 px-[38px] pt-10 pb-8 shadow-[0_24px_70px_rgba(38,34,27,0.16),0_2px_6px_rgba(38,34,27,0.06)] backdrop-blur-[4px] max-sm:px-6",
          className,
        )}
      >
        <BrandMark className="mb-[18px]" />
        {children}
        <div className="mt-6 flex justify-between border-line border-t pt-4 font-mono text-[10.5px] tracking-[0.04em] text-stone-faint uppercase">
          <span>AU data residency</span>
          <span>AES-256 at rest</span>
        </div>
      </main>
    </div>
  )
}

/** Serif page title. Focusable so a state change (form to confirmation) can move focus to it. */
export function AuthTitle({
  children,
  titleRef,
}: {
  children: ReactNode
  titleRef?: Ref<HTMLHeadingElement>
}) {
  return (
    <h1
      ref={titleRef}
      tabIndex={titleRef ? -1 : undefined}
      className="font-serif text-[30px] leading-tight font-semibold tracking-[-0.015em] outline-none"
    >
      {children}
    </h1>
  )
}

/** The italic line under the title: what this page does, in one sentence. */
export function AuthLead({ children }: { children: ReactNode }) {
  return (
    <p className="mt-1.5 mb-6 font-serif text-[15px] text-pretty text-stone italic">
      {children}
    </p>
  )
}

/** The one refusal on a form: the API's sentence and, when it sent one, its correlation handle. */
export function AuthFailure({
  message,
  error,
  action,
}: {
  message: string | null
  error?: unknown
  action?: ReactNode
}) {
  if (!message) return null
  const reference = error === undefined ? undefined : apiRequestId(error)
  return (
    <div
      role="alert"
      className="mt-4 rounded-btn bg-danger-tint px-3 py-2.5 text-[13px] text-danger-deep"
    >
      {message}
      {action ? <> {action}</> : null}
      {reference ? (
        <span className="mt-1 block font-mono text-[11px] opacity-75">
          Reference {reference}
        </span>
      ) : null}
    </div>
  )
}

/** A completed step: what happened and what to do next. */
export function AuthConfirmation({ children }: { children: ReactNode }) {
  return (
    <div
      role="status"
      className="flex items-start gap-2.5 rounded-btn bg-ok-tint px-3 py-3 text-[13.5px] leading-relaxed text-pretty text-ok-deep"
    >
      <CircleCheck className="mt-0.5 size-4 shrink-0" />
      <div>{children}</div>
    </div>
  )
}

/** Small centred line with a link back to another public page. */
export function AuthAside({ children }: { children: ReactNode }) {
  return <p className="mt-4 text-center text-[13px] text-stone">{children}</p>
}

export const authLinkClass =
  "rounded-[3px] font-medium text-clay underline-offset-2 hover:underline"
