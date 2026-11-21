import { useQuery } from "@tanstack/react-query"
import { Link } from "@tanstack/react-router"
import { Copy } from "lucide-react"
import { toast } from "sonner"
import type { InboxMessageSummary } from "@/client/types.gen"
import { Button } from "@/components/ui/button"
import {
  inboxAddressQuery,
  inboxQueueQuery,
  QUEUE_FILTER_KEYS,
  QUEUE_FILTERS,
  type QueueFilter,
  STATE_REASONS,
} from "@/data/inbox"
import {
  Card,
  EmptyState,
  ErrorState,
  Mono,
  NotForYourRole,
  PageHeader,
  Pill,
  SkeletonRows,
} from "@/design/primitives"
import { formatDayMonthTime } from "@/lib/format"
import { isForbidden } from "@/lib/http"
import { cn } from "@/lib/utils"

const EMPTY: Record<QueueFilter, { title: string; body?: string }> = {
  open: {
    title: "Nothing to review.",
    body: "TGA letters sent to your clinic's inbox address appear here, oldest first.",
  },
  VERIFIED: { title: "No accepted letters yet." },
  REJECTED: { title: "No rejected letters." },
}

/**
 * The review queue (`GET /tga-inbox/messages`): oldest first, so nothing waits behind newer mail
 * (FEAT-09 R17). Each row opens the review screen.
 */
export function InboxPage({ filter }: { filter: QueueFilter }) {
  const queue = useQuery(inboxQueueQuery(filter))
  const address = useQuery({ ...inboxAddressQuery, retry: false })
  const forbidden = queue.isError && isForbidden(queue.error)

  return (
    <>
      <PageHeader
        title="TGA inbox"
        subtitle="Approval letters emailed to the clinic are read automatically. Check each one against the PDF, choose the patient and accept it. Accepting records a pending approval; a second clinician verifies it on the register before it can authorise a script."
      />

      {forbidden ? (
        <NotForYourRole />
      ) : (
        <>
          {address.data ? (
            <div className="mb-4 flex flex-wrap items-center gap-2 rounded-inner border border-line bg-oat px-4 py-3 text-sm text-stone">
              <span>Ask the TGA to send approval letters to</span>
              <Mono className="text-ink break-all whitespace-normal">
                {address.data.address}
              </Mono>
              <Button
                size="sm"
                variant="ghost"
                aria-label="Copy the inbox address"
                onClick={() =>
                  navigator.clipboard
                    .writeText(address.data.address)
                    .then(() => toast.success("Inbox address copied"))
                }
              >
                <Copy />
              </Button>
            </div>
          ) : null}

          <nav
            className="mb-4 flex flex-wrap gap-1.5"
            aria-label="Filter the inbox"
          >
            {QUEUE_FILTER_KEYS.map((key) => (
              <Link
                key={key}
                to="/tga-inbox"
                search={{ filter: key }}
                aria-current={filter === key ? "page" : undefined}
                className={cn(
                  "rounded-full border px-3.5 py-1.5 text-[13px] font-medium transition-colors max-lg:inline-flex max-lg:min-h-11 max-lg:items-center",
                  filter === key
                    ? "border-clay bg-clay-tint text-clay-deep"
                    : "border-line bg-paper text-stone hover:text-ink",
                )}
              >
                {QUEUE_FILTERS[key].label}
                {filter === key && queue.data ? (
                  <span className="ml-1.5 font-mono text-[11px] opacity-70">
                    {queue.data.count}
                  </span>
                ) : null}
              </Link>
            ))}
          </nav>

          <Card bodyClassName="-mx-5 -my-[18px]">
            {queue.isPending ? (
              <div className="p-5">
                <SkeletonRows rows={5} />
              </div>
            ) : queue.isError ? (
              <div className="p-5">
                <ErrorState
                  error={queue.error}
                  onRetry={() => queue.refetch()}
                />
              </div>
            ) : queue.data.data.length === 0 ? (
              <EmptyState
                title={EMPTY[filter].title}
                body={EMPTY[filter].body}
              />
            ) : (
              <QueueTable rows={queue.data.data} />
            )}
          </Card>
        </>
      )}
    </>
  )
}

function StatePill({ row }: { row: InboxMessageSummary }) {
  if (row.processing_state === "VERIFIED")
    return <Pill tone="ok">Accepted</Pill>
  if (row.processing_state === "REJECTED")
    return <Pill tone="neutral">Rejected</Pill>
  if (row.state_reason === "UNTRUSTED_SENDER")
    return <Pill tone="danger">Unverified sender</Pill>
  if (row.processing_state === "FAILED")
    return (
      <Pill
        tone="warn"
        title={row.state_reason ? STATE_REASONS[row.state_reason] : undefined}
      >
        Read by hand
      </Pill>
    )
  return <Pill tone="info">Ready to check</Pill>
}

function QueueTable({ rows }: { rows: InboxMessageSummary[] }) {
  return (
    <div className="relative overflow-x-auto">
      <table className="data-table">
        <thead>
          <tr>
            <th className="pl-5">Received</th>
            <th>Subject</th>
            <th className="max-lg:hidden">From</th>
            <th className="max-md:hidden">Files</th>
            <th
              className="max-md:hidden"
              title="Mean confidence of the five approval fields. It orders and flags; it never decides."
            >
              Read score
            </th>
            <th className="pr-5">Status</th>
          </tr>
        </thead>
        <tbody>
          {rows.map((row) => (
            <tr key={row.id}>
              <td className="pl-5">
                <Mono>{formatDayMonthTime(row.received_at)}</Mono>
              </td>
              <td className="max-w-[360px]">
                <Link
                  to="/tga-inbox/$messageId"
                  params={{ messageId: row.id }}
                  className="font-medium text-ink underline-offset-2 hover:underline"
                >
                  {row.subject || "(no subject)"}
                </Link>
                {row.claimed_by &&
                row.lease_expires_at &&
                new Date(row.lease_expires_at) > new Date() ? (
                  <span className="ml-2 text-xs text-stone">
                    · being reviewed
                  </span>
                ) : null}
              </td>
              <td className="max-lg:hidden text-stone">{row.from_address}</td>
              <td className="max-md:hidden">
                <Mono>
                  {row.clean_attachment_count}/{row.attachment_count}
                </Mono>
              </td>
              <td className="max-md:hidden">
                {row.composite_score == null ? (
                  <span className="text-stone-faint">—</span>
                ) : (
                  <Mono>{Number(row.composite_score).toFixed(2)}</Mono>
                )}
              </td>
              <td className="pr-5">
                <StatePill row={row} />
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}
