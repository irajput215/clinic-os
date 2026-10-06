/**
 * The states every administration panel can be in: loading, empty, failed, and refused.
 *
 * A `403` is never an error here. The API answers `403` for a signed-in caller who does not
 * hold `users:manage`, and for an account that belongs to no organisation; both mean "there
 * is nothing this screen may show you", which is a state with an explanation, not a crash
 * and not a blank page. `main.tsx` signs out on `401` only, so a `403` stays in the page for
 * every request and no screen has to opt out of anything.
 */

import { AlertCircle, Inbox, RefreshCw, ShieldX } from "lucide-react"

import { Button } from "@/components/ui/button"
import { Card, CardContent } from "@/components/ui/card"
import { Skeleton } from "@/components/ui/skeleton"

export function AdminLoading({
  label = "Loading administration data",
}: {
  label?: string
}) {
  return (
    <Card data-testid="admin-loading" aria-busy="true" aria-label={label}>
      <CardContent className="flex flex-col gap-4 py-6">
        <Skeleton className="h-5 w-48" />
        <Skeleton className="h-4 w-full max-w-xl" />
        <Skeleton className="h-4 w-full max-w-lg" />
        <Skeleton className="h-24 w-full" />
      </CardContent>
    </Card>
  )
}

/** The page-level fallback while the signed-in user is still being resolved. */
export function AdminPageLoading() {
  return (
    <div className="flex flex-col gap-6" data-testid="admin-page-loading">
      <div className="flex flex-col gap-2">
        <Skeleton className="h-8 w-56" />
        <Skeleton className="h-4 w-80" />
      </div>
      <Skeleton className="h-9 w-full max-w-md" />
      <AdminLoading />
    </div>
  )
}

/**
 * "You are signed in, but this is not yours to see." It covers both `403` shapes the
 * administration API returns without claiming to tell them apart.
 */
export function AccessDenied({
  title = "You do not have permission",
  description,
}: {
  title?: string
  description?: string
}) {
  return (
    <Card data-testid="admin-access-denied" role="alert">
      <CardContent className="flex flex-col items-center gap-4 py-12 text-center">
        <div className="rounded-full bg-muted p-3">
          <ShieldX
            className="size-6 text-muted-foreground"
            aria-hidden="true"
          />
        </div>
        <div className="flex max-w-xl flex-col gap-1">
          <p className="font-medium">{title}</p>
          <p className="text-sm text-muted-foreground">
            {description ??
              "Managing users and roles needs the users:manage permission, which is held by an owner or administrator of your organisation. Your account does not have it, or does not belong to an organisation yet."}
          </p>
        </div>
      </CardContent>
    </Card>
  )
}

/** A failure worth retrying — never a `403`, which has its own state above. */
export function AdminError({
  title = "We couldn't load this",
  description,
  onRetry,
  retrying,
}: {
  title?: string
  description?: string
  onRetry: () => void
  retrying: boolean
}) {
  return (
    <Card data-testid="admin-error" role="alert">
      <CardContent className="flex flex-col items-start gap-4 py-8">
        <div className="flex items-center gap-2">
          <AlertCircle className="size-5 text-destructive" aria-hidden="true" />
          <p className="font-medium">{title}</p>
        </div>
        <p className="text-sm text-muted-foreground">
          {description ??
            "The API could not answer. Check your connection and try again."}
        </p>
        <Button variant="outline" onClick={onRetry} disabled={retrying}>
          <RefreshCw className="size-4" aria-hidden="true" />
          Try again
        </Button>
      </CardContent>
    </Card>
  )
}

export function AdminEmpty({ message }: { message: string }) {
  return (
    <Card data-testid="admin-empty">
      <CardContent className="flex flex-col items-center gap-3 py-10 text-center">
        <div className="rounded-full bg-muted p-3">
          <Inbox className="size-5 text-muted-foreground" aria-hidden="true" />
        </div>
        <p className="text-sm text-muted-foreground">{message}</p>
      </CardContent>
    </Card>
  )
}
