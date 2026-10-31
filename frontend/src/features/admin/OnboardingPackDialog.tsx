import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query"
import { CircleCheck, CircleDashed, Loader2 } from "lucide-react"
import { type ReactNode, useId, useState } from "react"
import { toast } from "sonner"
import type { IdentifierRead, OnboardingPackRead } from "@/client/types.gen"
import { Button } from "@/components/ui/button"
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog"
import {
  describeMissing,
  IDENTIFIER_HINTS,
  type IdentifierKind,
  onboardingPackQuery,
  recordAgreement,
  updateIdentifier,
} from "@/data/onboarding"
import { useCanConfigureClinic } from "@/data/useClinic"
import {
  ErrorState,
  Field,
  FormAlert,
  Mono,
  Pill,
  SkeletonRows,
} from "@/design/primitives"
import { formatDayMonthTime } from "@/lib/format"
import { describeError } from "@/lib/http"

const STATE_PILL: Record<
  IdentifierRead["state"],
  { label: string; tone: "ok" | "warn" | "danger" | "neutral" }
> = {
  MISSING: { label: "Not recorded", tone: "neutral" },
  PENDING: { label: "Pending check", tone: "warn" },
  ACTIVE: { label: "Active", tone: "ok" },
  EXPIRING: { label: "Expiring", tone: "warn" },
  EXPIRED: { label: "Expired", tone: "danger" },
}

/**
 * A prescriber's onboarding pack (manual §15.2): the agreement, the credential vault and the required
 * SOPs. All three ticks make the pack complete, and only then does the server let them sign. Values are
 * masked by the server; each identifier change asks for the editor's password (a step-up bound to this
 * person). Only `tenant:configure` sees the edit controls; the server refuses anyone else anyway.
 */
export function OnboardingPackDialog({
  userId,
  open,
  onOpenChange,
}: {
  userId: string
  open: boolean
  onOpenChange: (open: boolean) => void
}) {
  const pack = useQuery({ ...onboardingPackQuery(userId), enabled: open })
  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="max-h-[90vh] overflow-y-auto sm:max-w-[620px]">
        <DialogHeader>
          <DialogTitle>Onboarding pack</DialogTitle>
          <DialogDescription>
            {pack.data
              ? `${pack.data.name} · ${pack.data.pack_complete ? "Pack complete" : "Pack incomplete"}`
              : "Agreement, identifiers and required SOPs."}
          </DialogDescription>
        </DialogHeader>
        {pack.isPending ? (
          <SkeletonRows rows={6} />
        ) : pack.isError ? (
          <ErrorState error={pack.error} onRetry={() => pack.refetch()} />
        ) : (
          <PackBody pack={pack.data} />
        )}
      </DialogContent>
    </Dialog>
  )
}

export function PackBody({
  pack,
  readOnly = false,
}: {
  pack: OnboardingPackRead
  readOnly?: boolean
}) {
  const canConfigure = useCanConfigureClinic() === true && !readOnly
  const sopTitles = Object.fromEntries(pack.sops.map((s) => [s.id, s.title]))
  const required = pack.identifiers.filter((i) => i.required)
  const identifiersDone = !pack.missing.some(
    (m) => m === "AHPRA" || m === "PRESCRIBER_NUMBER",
  )
  const sopsDone = !pack.missing.some((m) => m.startsWith("SOP:"))
  return (
    <div className="space-y-5">
      {pack.pack_complete ? (
        <p className="flex items-center gap-2 rounded-inner bg-ok-tint px-3 py-2 text-sm text-ok-deep">
          <CircleCheck className="size-4" /> Pack complete: ready to prescribe.
        </p>
      ) : (
        <div className="rounded-inner bg-warn-tint px-3 py-2 text-sm text-warn-deep">
          <p className="font-medium">Not ready to sign scripts yet</p>
          <ul className="mt-1 list-disc pl-5">
            {pack.missing.map((m) => (
              <li key={m}>{describeMissing(m, sopTitles)}</li>
            ))}
          </ul>
        </div>
      )}

      <Section title="1 · Agreement" done={pack.agreement !== null}>
        {pack.agreement ? (
          <p className="text-sm">
            Signed version <Mono>{pack.agreement.agreement_version}</Mono> on{" "}
            {pack.agreement.signed_on}
            <span className="text-stone">
              {" "}
              · attested by {pack.agreement.attested_by_name ?? "a colleague"}
            </span>
          </p>
        ) : (
          <p className="text-sm text-stone">No agreement recorded.</p>
        )}
        {canConfigure ? <AgreementForm userId={pack.user_id} /> : null}
      </Section>

      <Section title="2 · Identifiers" done={identifiersDone}>
        <ul className="divide-y divide-line">
          {pack.identifiers.map((identifier) => (
            <IdentifierRow
              key={identifier.kind}
              userId={pack.user_id}
              identifier={identifier}
              canEdit={canConfigure}
            />
          ))}
        </ul>
        {required.length ? (
          <p className="text-xs text-stone">
            Required to sign: {required.map((i) => i.label).join(" and ")}.
          </p>
        ) : null}
      </Section>

      <Section title="3 · Required SOPs" done={sopsDone}>
        {pack.sops.length === 0 ? (
          <p className="text-sm text-stone">
            No SOP is required for this role.
          </p>
        ) : (
          <ul className="space-y-1.5 text-sm">
            {pack.sops.map((sop) => (
              <li key={sop.id} className="flex flex-wrap items-center gap-2">
                <span className="min-w-0 break-words">{sop.title}</span>
                <span className="text-xs text-stone">
                  v{sop.current_version}
                </span>
                {sop.acknowledged_version === sop.current_version ? (
                  <Pill tone="ok">Acknowledged</Pill>
                ) : (
                  <Pill tone="warn">Not yet</Pill>
                )}
              </li>
            ))}
          </ul>
        )}
      </Section>
    </div>
  )
}

function Section({
  title,
  done,
  children,
}: {
  title: string
  done: boolean
  children: ReactNode
}) {
  return (
    <section className="space-y-2">
      <h3 className="flex items-center gap-2 text-sm font-semibold">
        {done ? (
          <CircleCheck className="size-4 text-ok" aria-label="Done" />
        ) : (
          <CircleDashed className="size-4 text-stone" aria-label="Not done" />
        )}
        {title}
      </h3>
      {children}
    </section>
  )
}

function useSavePack(userId: string) {
  const queryClient = useQueryClient()
  return (saved: OnboardingPackRead) => {
    queryClient.setQueryData(onboardingPackQuery(userId).queryKey, saved)
    void queryClient.invalidateQueries({ queryKey: ["admin", "staff"] })
  }
}

function AgreementForm({ userId }: { userId: string }) {
  const [open, setOpen] = useState(false)
  const [version, setVersion] = useState("")
  const [signedOn, setSignedOn] = useState("")
  const ids = { version: useId(), signedOn: useId() }
  const save = useSavePack(userId)
  const record = useMutation({
    mutationFn: () => recordAgreement(userId, version.trim(), signedOn),
    onSuccess: (pack) => {
      save(pack)
      setOpen(false)
      toast.success("Agreement recorded")
    },
  })
  if (!open)
    return (
      <Button size="sm" variant="outline" onClick={() => setOpen(true)}>
        Record agreement
      </Button>
    )
  return (
    <form
      noValidate
      className="grid gap-3 sm:grid-cols-[1fr_1fr_auto] sm:items-end"
      onSubmit={(e) => {
        e.preventDefault()
        if (version.trim() && signedOn) record.mutate()
      }}
    >
      <Field label="Agreement version" htmlFor={ids.version}>
        <input
          id={ids.version}
          className="field-input"
          value={version}
          placeholder="2026-1"
          onChange={(e) => setVersion(e.target.value)}
        />
      </Field>
      <Field label="Signed on" htmlFor={ids.signedOn}>
        <input
          id={ids.signedOn}
          type="date"
          className="field-input"
          value={signedOn}
          onChange={(e) => setSignedOn(e.target.value)}
        />
      </Field>
      <Button
        type="submit"
        disabled={record.isPending || !version.trim() || !signedOn}
      >
        {record.isPending ? <Loader2 className="animate-spin" /> : null}
        Save
      </Button>
      {record.isError ? (
        <div className="sm:col-span-3">
          <FormAlert>{describeError(record.error)}</FormAlert>
        </div>
      ) : null}
    </form>
  )
}

function IdentifierRow({
  userId,
  identifier,
  canEdit,
}: {
  userId: string
  identifier: IdentifierRead
  canEdit: boolean
}) {
  const [editing, setEditing] = useState(false)
  const pill = STATE_PILL[identifier.state]
  return (
    <li className="py-2.5">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <div className="min-w-0">
          <p className="text-sm font-medium">
            {identifier.label}
            {identifier.required ? null : (
              <span className="font-normal text-stone"> · optional</span>
            )}
          </p>
          <p className="text-xs text-stone">
            {identifier.masked ? <Mono>{identifier.masked}</Mono> : "-"}
            {identifier.expires_on
              ? ` · expires ${identifier.expires_on}`
              : null}
            {identifier.verified_at
              ? ` · verified by ${identifier.verified_by_name ?? "a colleague"} ${formatDayMonthTime(identifier.verified_at)} (${identifier.verification_method})`
              : null}
          </p>
        </div>
        <div className="flex items-center gap-2">
          <Pill tone={pill.tone}>{pill.label}</Pill>
          {canEdit && !editing ? (
            <Button
              size="sm"
              variant="outline"
              aria-label={`Edit ${identifier.label}`}
              onClick={() => setEditing(true)}
            >
              Edit
            </Button>
          ) : null}
        </div>
      </div>
      {editing ? (
        <IdentifierForm
          userId={userId}
          identifier={identifier}
          onDone={() => setEditing(false)}
        />
      ) : null}
    </li>
  )
}

function IdentifierForm({
  userId,
  identifier,
  onDone,
}: {
  userId: string
  identifier: IdentifierRead
  onDone: () => void
}) {
  const kind = identifier.kind as IdentifierKind
  const [value, setValue] = useState("")
  const [verified, setVerified] = useState(true)
  const [method, setMethod] = useState(
    identifier.verification_method ?? "AHPRA public register",
  )
  const [expiresOn, setExpiresOn] = useState(identifier.expires_on ?? "")
  const [password, setPassword] = useState("")
  const ids = {
    value: useId(),
    verified: useId(),
    method: useId(),
    expires: useId(),
    password: useId(),
  }
  const save = useSavePack(userId)
  const update = useMutation({
    mutationFn: () =>
      updateIdentifier(
        userId,
        kind,
        {
          value: value.trim() || null,
          status: verified ? "ACTIVE" : "PENDING",
          verification_method: verified ? method.trim() || null : null,
          expires_on: expiresOn || null,
        },
        password,
      ),
    onSuccess: (pack) => {
      save(pack)
      onDone()
      toast.success(`${identifier.label} saved`)
    },
  })
  const needsValue = identifier.state === "MISSING"
  return (
    <form
      noValidate
      className="mt-3 grid gap-3 rounded-inner border border-line p-3 sm:grid-cols-2"
      onSubmit={(e) => {
        e.preventDefault()
        update.mutate()
      }}
    >
      <Field
        label={
          needsValue ? identifier.label : `New ${identifier.label} (optional)`
        }
        htmlFor={ids.value}
        hint={IDENTIFIER_HINTS[kind]}
      >
        <input
          id={ids.value}
          className="field-input font-mono"
          autoComplete="off"
          value={value}
          onChange={(e) => setValue(e.target.value)}
        />
      </Field>
      <Field label="Expires on (if any)" htmlFor={ids.expires}>
        <input
          id={ids.expires}
          type="date"
          className="field-input"
          value={expiresOn}
          onChange={(e) => setExpiresOn(e.target.value)}
        />
      </Field>
      <label
        htmlFor={ids.verified}
        className="flex min-h-11 items-center gap-2 text-sm sm:col-span-2"
      >
        <input
          id={ids.verified}
          type="checkbox"
          className="size-4"
          checked={verified}
          onChange={(e) => setVerified(e.target.checked)}
        />
        I checked this identifier
      </label>
      {verified ? (
        <Field label="How it was checked" htmlFor={ids.method}>
          <input
            id={ids.method}
            className="field-input"
            value={method}
            onChange={(e) => setMethod(e.target.value)}
          />
        </Field>
      ) : null}
      <Field
        label="Your password"
        htmlFor={ids.password}
        hint="Confirms it's you making this change"
      >
        <input
          id={ids.password}
          type="password"
          autoComplete="current-password"
          className="field-input"
          value={password}
          onChange={(e) => setPassword(e.target.value)}
        />
      </Field>
      {update.isError ? (
        <div className="sm:col-span-2">
          <FormAlert>{describeError(update.error)}</FormAlert>
        </div>
      ) : null}
      <div className="flex justify-end gap-2 sm:col-span-2">
        <Button type="button" variant="outline" onClick={onDone}>
          Cancel
        </Button>
        <Button
          type="submit"
          disabled={
            update.isPending || !password || (needsValue && !value.trim())
          }
        >
          {update.isPending ? <Loader2 className="animate-spin" /> : null}
          Save {identifier.label}
        </Button>
      </div>
    </form>
  )
}
