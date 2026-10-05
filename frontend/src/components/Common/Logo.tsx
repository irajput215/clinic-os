import { Link } from "@tanstack/react-router"

import { cn } from "@/lib/utils"

interface LogoProps {
  variant?: "full" | "icon" | "responsive"
  className?: string
  asLink?: boolean
}

const MARK = "C"
const WORDMARK = "clinicOS"

/**
 * The product wordmark. It is text rather than an image: the brand is a name, and a
 * text mark needs no theme-specific asset to stay legible in both themes.
 */
export function Logo({
  variant = "full",
  className,
  asLink = true,
}: LogoProps) {
  const showWordmark = variant !== "icon"

  const content = (
    <span className={cn("flex items-center gap-2", className)}>
      <span
        aria-hidden
        className={cn(
          "grid size-6 shrink-0 place-items-center rounded-md bg-primary text-xs font-bold text-primary-foreground",
          variant === "icon" && "size-5 text-[0.625rem]",
        )}
      >
        {MARK}
      </span>
      <span
        className={cn(
          "font-semibold tracking-tight text-foreground",
          variant === "icon" && "hidden",
          variant === "responsive" && "group-data-[collapsible=icon]:hidden",
        )}
      >
        {WORDMARK}
      </span>
      {!showWordmark && <span className="sr-only">{WORDMARK}</span>}
    </span>
  )

  if (!asLink) {
    return content
  }

  return (
    <Link to="/" aria-label={`${WORDMARK} home`}>
      {content}
    </Link>
  )
}
