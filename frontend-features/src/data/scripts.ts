import { queryOptions } from "@tanstack/react-query"
import { previewMatch } from "@/data/preview/gate"
import { escriptToken, uuid } from "@/data/preview/seed"
import { readPreview, writePreview } from "@/data/preview/store"
import type { Script, ScriptDraft, ScriptState } from "@/data/types"
import { Refusal } from "@/lib/http"

/**
 * Prescriptions (the script queue): PREVIEW ONLY. No backend module exists. The proposed contract,
 * including the server-side safety gate on sign AND on dispatch, the transactional outbox and the
 * REQUIRES_RECONCILIATION outcome, is docs2/sdlc/07-script-queue/api.md.
 *
 * The preview reproduces the gate's fail-closed behaviour so the UI is designed around refusals: a
 * script whose approval does not cover the date of service is BLOCKED, with the reason code, and
 * cannot be sent.
 */
const PHARMACIES = [
  "Leaf & Stone Pharmacy",
  "Terra Dispensary Chemist",
  "GreenLeaf Compounding",
]

export const scriptsRepo = {
  /**
   * The gate answer shown on a script that is still awaiting action is evaluated now, against the
   * approvals as they are now, so recording or verifying an approval is reflected immediately. A
   * sent script keeps the decision it was sent under.
   */
  list: async (): Promise<Script[]> => {
    const s = await readPreview()
    return s.scripts
      .map((x) =>
        isActionable(x.state)
          ? { ...x, gate: previewMatch(s.approvals, x) }
          : x,
      )
      .sort((a, b) => b.created_at.localeCompare(a.created_at))
  },

  stage: (draft: ScriptDraft) =>
    writePreview((s) => {
      const product = s.products.find((p) => p.id === draft.product_id)
      if (!product)
        throw new Refusal(
          "PRODUCT_UNKNOWN",
          "Choose a product from the catalogue.",
        )
      const prescriber = s.practitioners.find(
        (p) => p.id === draft.prescriber_id && p.role === "DOCTOR",
      )
      if (!prescriber)
        throw new Refusal(
          "PRESCRIBER_NOT_AUTHORIZED",
          "Choose the doctor who will review this script.",
        )
      const me = s.practitioners.find((p) => p.id === s.me)
      const script: Script = {
        id: uuid(),
        ...draft,
        product_name: product.name,
        tga_category: product.tga_category,
        dosage_form: product.dosage_form,
        state: "AWAITING_REVIEW",
        drafted_by: s.me,
        drafted_by_name: me?.name ?? "You",
        prescriber_name: prescriber.name,
        created_at: new Date().toISOString(),
        signed_at: null,
        sent_at: null,
        escript_token: null,
        pharmacy: null,
        gate: null,
      }
      script.gate = previewMatch(s.approvals, script)
      s.scripts.unshift(script)
      return script
    }),

  /**
   * Sign, then dispatch, with the gate evaluated at each step against the date of service. A refusal
   * at either step leaves the script BLOCKED with the reason, and nothing is sent.
   */
  signAndSend: (id: string) =>
    writePreview((s) => {
      const script = s.scripts.find((x) => x.id === id)
      if (!script)
        throw new Refusal("NOT_FOUND", "That script isn't available.")
      if (script.state !== "AWAITING_REVIEW" && script.state !== "BLOCKED")
        throw new Refusal(
          "STATE_INVALID",
          "This script has already been actioned.",
        )
      if (script.prescriber_id !== s.me)
        throw new Refusal(
          "PRESCRIBER_NOT_AUTHORIZED",
          `Only ${script.prescriber_name} can sign this script.`,
        )
      const gate = previewMatch(s.approvals, script)
      script.gate = gate
      if (!gate.matched) {
        script.state = "BLOCKED"
        return script
      }
      const now = new Date().toISOString()
      script.state = "SENT"
      script.signed_at = now
      script.sent_at = now
      script.escript_token = escriptToken()
      script.pharmacy = PHARMACIES[s.scripts.length % PHARMACIES.length]
      return script
    }),

  cancel: (id: string) =>
    writePreview((s) => {
      const script = s.scripts.find((x) => x.id === id)
      if (!script)
        throw new Refusal("NOT_FOUND", "That script isn't available.")
      if (script.state === "SENT")
        throw new Refusal(
          "STATE_INVALID",
          "A sent script is cancelled with the pharmacy, not here.",
        )
      script.state = "CANCELLED"
      return script
    }),
}

export const scriptsQuery = queryOptions({
  queryKey: ["scripts"],
  queryFn: scriptsRepo.list,
  staleTime: 10_000,
})

export const productsQuery = queryOptions({
  queryKey: ["products"],
  queryFn: async () => (await readPreview()).products,
  staleTime: 5 * 60_000,
})

export const isActionable = (state: ScriptState) =>
  state === "AWAITING_REVIEW" || state === "BLOCKED"

export const SCRIPT_STATE_LABEL: Record<ScriptState, string> = {
  AWAITING_REVIEW: "Awaiting review",
  SIGNED: "Signed",
  SENT: "Sent to pharmacy",
  BLOCKED: "Blocked by safety gate",
  REQUIRES_RECONCILIATION: "Needs reconciliation",
  CANCELLED: "Cancelled",
}
