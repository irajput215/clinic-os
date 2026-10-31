import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query"
import { useNavigate } from "@tanstack/react-router"
import { Loader2, Plus, Printer } from "lucide-react"
import { useId, useState } from "react"
import { toast } from "sonner"
import type { SopCard, SopDetail, SopWrite } from "@/client/types.gen"
import { Button } from "@/components/ui/button"
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog"
import {
  acknowledgeSop,
  createSop,
  matrixQuery,
  needsAcknowledgement,
  publishSopVersion,
  ROLE_LABELS,
  sopQuery,
  sopsQuery,
} from "@/data/onboarding"
import { myPermissionsQuery } from "@/data/permissions"
import {
  Card,
  EmptyState,
  ErrorState,
  Field,
  FormAlert,
  PageHeader,
  Pill,
  SkeletonRows,
  TabBar,
} from "@/design/primitives"
import { formatDayMonthTime } from "@/lib/format"
import { describeError } from "@/lib/http"
import { SOP_TAB_KEYS, SOP_TABS, type SopTab } from "./tabs"

function usePermission(code: string): boolean {
  const { data } = useQuery(myPermissionsQuery)
  return data ? !data.known || data.codes.includes(code) : false
}

/**
 * SOPs & policies (manual §13): the practice's procedures, each versioned. Staff read and acknowledge
 * the current version of every SOP that applies to their role; a new version asks again. Whoever
 * configures the practice publishes, and they or an auditor see who has acknowledged what.
 */
export function SopsPage({ tab }: { tab: SopTab }) {
  const navigate = useNavigate()
  const canConfigure = usePermission("tenant:configure")
  const canAudit = usePermission("audit:read")
  const keys = SOP_TAB_KEYS.filter(
    (k) => k !== "matrix" || canConfigure || canAudit,
  )
  const active = keys.includes(tab) ? tab : "procedures"
  return (
    <>
      <PageHeader
        title="SOPs & policies"
        subtitle="How this practice works. Read and acknowledge each procedure that applies to your role."
      />
      {keys.length > 1 ? (
        <TabBar
          label="SOPs"
          tabs={keys.map((key) => ({ key, label: SOP_TABS[key] }))}
          value={active}
          onSelect={(key) =>
            navigate({ to: ".", search: { tab: key }, replace: true })
          }
        />
      ) : null}
      {active === "matrix" ? (
        <Matrix />
      ) : (
        <Procedures canConfigure={canConfigure} />
      )}
    </>
  )
}

function Procedures({ canConfigure }: { canConfigure: boolean }) {
  const sops = useQuery(sopsQuery)
  const [reading, setReading] = useState<string | null>(null)
  const [editing, setEditing] = useState<SopDetail | "new" | null>(null)
  return (
    <div className="space-y-4">
      {canConfigure ? (
        <div className="flex justify-end">
          <Button onClick={() => setEditing("new")}>
            <Plus /> New SOP
          </Button>
        </div>
      ) : null}
      <Card bodyClassName="-mx-5 -my-[18px]">
        {sops.isPending ? (
          <div className="p-5">
            <SkeletonRows rows={4} />
          </div>
        ) : sops.isError ? (
          <div className="p-5">
            <ErrorState error={sops.error} onRetry={() => sops.refetch()} />
          </div>
        ) : sops.data.length === 0 ? (
          <EmptyState
            title={
              canConfigure
                ? "No SOPs yet: publish your first."
                : "No SOPs apply to your role yet."
            }
          />
        ) : (
          <ul className="divide-y divide-line-faint" data-testid="sop-list">
            {sops.data.map((sop) => (
              <li key={sop.id}>
                <button
                  type="button"
                  className="flex min-h-11 w-full flex-wrap items-center justify-between gap-2 px-5 py-3 text-left hover:bg-oat/60"
                  onClick={() => setReading(sop.id)}
                >
                  <span className="min-w-0">
                    <span className="block font-medium break-words">
                      {sop.title}
                    </span>
                    <span className="block text-xs text-stone">
                      v{sop.current_version} ·{" "}
                      {sop.applies_to_roles.length
                        ? sop.applies_to_roles
                            .map((r) => ROLE_LABELS[r] ?? r)
                            .join(", ")
                        : "Everyone"}
                    </span>
                  </span>
                  <span className="flex flex-wrap gap-1">
                    {sop.required_for_onboarding ? (
                      <Pill tone="info">Onboarding</Pill>
                    ) : null}
                    <AckPill sop={sop} />
                  </span>
                </button>
              </li>
            ))}
          </ul>
        )}
      </Card>
      {reading ? (
        <SopReader
          sopId={reading}
          canConfigure={canConfigure}
          onClose={() => setReading(null)}
          onRevise={(detail) => {
            setReading(null)
            setEditing(detail)
          }}
        />
      ) : null}
      {editing ? (
        <SopEditor
          sop={editing === "new" ? null : editing}
          onClose={() => setEditing(null)}
        />
      ) : null}
    </div>
  )
}

function AckPill({ sop }: { sop: SopCard }) {
  if (!sop.applies_to_me) return <Pill>Not for your role</Pill>
  if (needsAcknowledgement(sop))
    return (
      <Pill tone="warn">
        {sop.my_acknowledged_version
          ? `New version: acknowledge v${sop.current_version}`
          : "Needs your acknowledgement"}
      </Pill>
    )
  return <Pill tone="ok">Acknowledged</Pill>
}

/** A print of the current text, stamped UNCONTROLLED COPY (R9): the app is the controlled copy. */
function printSop(sop: SopDetail) {
  const win = window.open("", "_blank", "noopener=no,width=800,height=900")
  if (!win) return
  const doc = win.document
  doc.title = `${sop.title} v${sop.current_version}`
  const style = doc.createElement("style")
  style.textContent = `body{font:14px/1.55 system-ui,sans-serif;margin:40px;color:#222}
h1{font-size:22px;margin:0 0 4px}.meta{color:#666;margin-bottom:24px}
.body{white-space:pre-wrap}.stamp{position:fixed;top:40%;left:0;right:0;text-align:center;
font-size:64px;font-weight:700;color:rgba(200,0,0,.14);transform:rotate(-24deg);pointer-events:none}
.banner{border:2px solid #c00;color:#c00;font-weight:700;padding:6px 10px;margin-bottom:16px;display:inline-block}`
  doc.head.append(style)
  const stamp = doc.createElement("div")
  stamp.className = "stamp"
  stamp.textContent = "UNCONTROLLED COPY"
  const banner = doc.createElement("div")
  banner.className = "banner"
  banner.textContent =
    "UNCONTROLLED COPY: check the app for the current version"
  const title = doc.createElement("h1")
  title.textContent = sop.title
  const meta = doc.createElement("div")
  meta.className = "meta"
  meta.textContent = `Version ${sop.current_version} · printed ${new Date().toLocaleString("en-AU")}`
  const body = doc.createElement("div")
  body.className = "body"
  body.textContent = sop.body
  doc.body.append(stamp, banner, title, meta, body)
  win.focus()
  win.print()
}

function SopReader({
  sopId,
  canConfigure,
  onClose,
  onRevise,
}: {
  sopId: string
  canConfigure: boolean
  onClose: () => void
  onRevise: (sop: SopDetail) => void
}) {
  const sop = useQuery(sopQuery(sopId))
  const queryClient = useQueryClient()
  const acknowledge = useMutation({
    mutationFn: (version: number) => acknowledgeSop(sopId, version),
    onSuccess: async () => {
      await queryClient.invalidateQueries({ queryKey: ["sops"] })
      await queryClient.invalidateQueries({ queryKey: ["onboarding"] })
      toast.success("Acknowledged")
    },
  })
  const detail = sop.data
  return (
    <Dialog open onOpenChange={(open) => (open ? null : onClose())}>
      <DialogContent className="max-h-[90vh] overflow-y-auto sm:max-w-[680px]">
        <DialogHeader>
          <DialogTitle>{detail?.title ?? "SOP"}</DialogTitle>
          <DialogDescription>
            {detail
              ? `Version ${detail.current_version} · published ${formatDayMonthTime(detail.versions[0]?.published_at ?? detail.updated_at)}`
              : "Loading"}
          </DialogDescription>
        </DialogHeader>
        {sop.isPending ? (
          <SkeletonRows rows={6} />
        ) : sop.isError ? (
          <ErrorState error={sop.error} onRetry={() => sop.refetch()} />
        ) : (
          <div className="space-y-4">
            <div
              className="rounded-inner border border-line-faint bg-oat/40 p-4 text-sm leading-relaxed break-words whitespace-pre-wrap"
              data-testid="sop-body"
            >
              {sop.data.body}
            </div>
            <details className="text-sm">
              <summary className="min-h-11 cursor-pointer py-2 text-stone">
                Version history ({sop.data.versions.length})
              </summary>
              <ul className="space-y-1 pl-4 text-xs text-stone">
                {sop.data.versions.map((v) => (
                  <li key={v.version}>
                    v{v.version} · {formatDayMonthTime(v.published_at)}
                    {v.published_by_name ? ` · ${v.published_by_name}` : null}
                  </li>
                ))}
              </ul>
            </details>
            {acknowledge.isError ? (
              <FormAlert>{describeError(acknowledge.error)}</FormAlert>
            ) : null}
            <div className="flex flex-wrap justify-end gap-2">
              <Button variant="outline" onClick={() => printSop(sop.data)}>
                <Printer /> Print
              </Button>
              {canConfigure ? (
                <Button variant="outline" onClick={() => onRevise(sop.data)}>
                  Publish new version
                </Button>
              ) : null}
              {needsAcknowledgement(sop.data) ? (
                <Button
                  disabled={acknowledge.isPending}
                  onClick={() => acknowledge.mutate(sop.data.current_version)}
                >
                  {acknowledge.isPending ? (
                    <Loader2 className="animate-spin" />
                  ) : null}
                  Acknowledge version {sop.data.current_version}
                </Button>
              ) : sop.data.applies_to_me ? (
                <Pill tone="ok">
                  You acknowledged v{sop.data.current_version}
                </Pill>
              ) : null}
            </div>
          </div>
        )}
      </DialogContent>
    </Dialog>
  )
}

function SopEditor({
  sop,
  onClose,
}: {
  sop: SopDetail | null
  onClose: () => void
}) {
  const [title, setTitle] = useState(sop?.title ?? "")
  const [body, setBody] = useState(sop?.body ?? "")
  const [roles, setRoles] = useState<string[]>(sop?.applies_to_roles ?? [])
  const [required, setRequired] = useState(
    sop?.required_for_onboarding ?? false,
  )
  const ids = { title: useId(), body: useId(), required: useId() }
  const queryClient = useQueryClient()
  const save = useMutation({
    mutationFn: () => {
      const write: SopWrite = {
        title: title.trim(),
        body: body.trim(),
        applies_to_roles: roles,
        required_for_onboarding: required,
      }
      return sop ? publishSopVersion(sop.id, write) : createSop(write)
    },
    onSuccess: async (saved) => {
      await queryClient.invalidateQueries({ queryKey: ["sops"] })
      await queryClient.invalidateQueries({ queryKey: ["onboarding"] })
      void queryClient.invalidateQueries({ queryKey: ["admin", "staff"] })
      toast.success(`Published version ${saved.current_version}`)
      onClose()
    },
  })
  return (
    <Dialog open onOpenChange={(open) => (open ? null : onClose())}>
      <DialogContent className="max-h-[90vh] overflow-y-auto sm:max-w-[680px]">
        <DialogHeader>
          <DialogTitle>
            {sop ? `New version of ${sop.title}` : "New SOP"}
          </DialogTitle>
          <DialogDescription>
            {sop
              ? `Publishing makes this version ${sop.current_version + 1}. Everyone it applies to must acknowledge it again.`
              : "Publishing makes this version 1."}
          </DialogDescription>
        </DialogHeader>
        <form
          noValidate
          className="space-y-4"
          onSubmit={(e) => {
            e.preventDefault()
            if (title.trim() && body.trim()) save.mutate()
          }}
        >
          <Field label="Title" htmlFor={ids.title}>
            <input
              id={ids.title}
              className="field-input"
              value={title}
              maxLength={200}
              onChange={(e) => setTitle(e.target.value)}
            />
          </Field>
          <Field label="Procedure" htmlFor={ids.body}>
            <textarea
              id={ids.body}
              className="field-input min-h-48"
              value={body}
              onChange={(e) => setBody(e.target.value)}
            />
          </Field>
          <fieldset>
            <legend className="field-label">
              Applies to (none ticked: everyone)
            </legend>
            <div className="grid gap-1 sm:grid-cols-2">
              {Object.entries(ROLE_LABELS).map(([code, label]) => (
                <label
                  key={code}
                  className="flex min-h-11 items-center gap-2 text-sm"
                >
                  <input
                    type="checkbox"
                    className="size-4"
                    checked={roles.includes(code)}
                    onChange={(e) =>
                      setRoles((now) =>
                        e.target.checked
                          ? [...now, code]
                          : now.filter((r) => r !== code),
                      )
                    }
                  />
                  {label}
                </label>
              ))}
            </div>
          </fieldset>
          <label
            htmlFor={ids.required}
            className="flex min-h-11 items-center gap-2 text-sm"
          >
            <input
              id={ids.required}
              type="checkbox"
              className="size-4"
              checked={required}
              onChange={(e) => setRequired(e.target.checked)}
            />
            Required for onboarding (a prescriber can't sign until they
            acknowledge it)
          </label>
          {save.isError ? (
            <FormAlert>{describeError(save.error)}</FormAlert>
          ) : null}
          <div className="flex justify-end gap-2">
            <Button type="button" variant="outline" onClick={onClose}>
              Cancel
            </Button>
            <Button
              type="submit"
              disabled={save.isPending || !title.trim() || !body.trim()}
            >
              {save.isPending ? <Loader2 className="animate-spin" /> : null}
              Publish
            </Button>
          </div>
        </form>
      </DialogContent>
    </Dialog>
  )
}

function Matrix() {
  const matrix = useQuery(matrixQuery)
  if (matrix.isPending)
    return (
      <Card>
        <SkeletonRows rows={5} />
      </Card>
    )
  if (matrix.isError)
    return (
      <Card>
        <ErrorState error={matrix.error} onRetry={() => matrix.refetch()} />
      </Card>
    )
  const { sops, staff } = matrix.data
  if (sops.length === 0)
    return (
      <Card>
        <EmptyState title="No SOPs yet." />
      </Card>
    )
  return (
    <Card bodyClassName="-mx-5 -my-[18px]">
      <div className="overflow-x-auto">
        <table className="data-table" data-testid="sop-matrix">
          <thead>
            <tr>
              <th className="pl-5">Staff member</th>
              {sops.map((sop) => (
                <th key={sop.id} className="min-w-32">
                  {sop.title} · v{sop.current_version}
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {staff.map((row) => (
              <tr key={row.user_id}>
                <td className="pl-5 font-medium">{row.name}</td>
                {sops.map((sop) => {
                  const acked = row.acknowledged[sop.id]
                  if (!row.applicable.includes(sop.id))
                    return (
                      <td key={sop.id} className="text-stone-faint">
                        n/a
                      </td>
                    )
                  return (
                    <td key={sop.id}>
                      {acked === sop.current_version ? (
                        <Pill tone="ok">v{acked}</Pill>
                      ) : acked ? (
                        <Pill tone="warn">v{acked} (old)</Pill>
                      ) : (
                        <Pill tone="danger">Not yet</Pill>
                      )}
                    </td>
                  )
                })}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </Card>
  )
}
