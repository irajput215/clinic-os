/**
 * "You are signed in, and this is not yours to see."
 *
 * The patients API refuses a signed-in caller in two ways, and both are `403`:
 *
 * - the account belongs to no organisation, which `app.api.deps.get_actor` answers with the
 *   `NO_ORGANISATION` code; and
 * - the account's roles do not hold the permission the route seeks, which the policy layer
 *   answers with `PERMISSION_NOT_HELD`.
 *
 * Neither is a reason to sign someone out, and they used to be treated as one: `main.tsx`
 * cleared the token on any `403`, so opening the Patients tab dropped the session and bounced
 * to sign-in — the API's actual answer discarded, in a loop, because signing in again led
 * straight back to the same screen. The screen owns this state now, and the two cases are
 * told apart by the reason code so each says what to do next.
 */

import { ShieldX } from "lucide-react"

import { Card, CardContent } from "@/components/ui/card"
import { apiErrorCode } from "@/lib/http"

type NoAccessReason = "no-organisation" | "permission" | "unknown"

/** Kept in step with the reason codes the API sends (`deps.get_actor`, `policy.DecisionCode`). */
function reasonFor(error: unknown): NoAccessReason {
  const code = apiErrorCode(error)
  if (code === "NO_ORGANISATION") return "no-organisation"
  if (code === "PERMISSION_NOT_HELD") return "permission"
  return "unknown"
}

const COPY: Record<NoAccessReason, { title: string; description: string }> = {
  "no-organisation": {
    title: "Your account is not part of an organisation",
    description:
      "Patients belong to an organisation, and this account does not belong to one yet. Ask an owner or administrator to invite you — or register a clinic, which creates the organisation and makes you its administrator.",
  },
  permission: {
    title: "You do not have access to patients",
    description:
      "Your roles in this organisation do not include the permission this screen needs. An owner or administrator can assign you a role that includes it.",
  },
  unknown: {
    title: "You do not have access to patients",
    description:
      "The API refused this request for your account. An owner or administrator can tell you which role you hold.",
  },
}

export function PatientsNoAccess({ error }: { error: unknown }) {
  const reason = reasonFor(error)
  const { title, description } = COPY[reason]

  return (
    <Card data-testid="patients-no-access" data-reason={reason} role="alert">
      <CardContent className="flex flex-col items-center gap-4 py-12 text-center">
        <div className="rounded-full bg-muted p-3">
          <ShieldX
            className="size-6 text-muted-foreground"
            aria-hidden="true"
          />
        </div>
        <div className="flex max-w-xl flex-col gap-1">
          <p className="font-medium">{title}</p>
          <p className="text-sm text-muted-foreground">{description}</p>
        </div>
      </CardContent>
    </Card>
  )
}

export default PatientsNoAccess
