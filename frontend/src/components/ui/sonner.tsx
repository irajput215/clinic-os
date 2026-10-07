import {
  CircleCheckIcon,
  InfoIcon,
  Loader2Icon,
  OctagonXIcon,
  TriangleAlertIcon,
} from "lucide-react"
import type * as React from "react"
import { Toaster as Sonner, type ToasterProps } from "sonner"

const Toaster = ({ ...props }: ToasterProps) => (
  <Sonner
    theme="light"
    className="toaster group"
    icons={{
      success: <CircleCheckIcon className="size-4 text-ok" />,
      info: <InfoIcon className="size-4 text-info" />,
      warning: <TriangleAlertIcon className="size-4 text-warn" />,
      error: <OctagonXIcon className="size-4 text-danger" />,
      loading: <Loader2Icon className="size-4 animate-spin" />,
    }}
    style={
      {
        "--normal-bg": "var(--color-paper)",
        "--normal-text": "var(--color-ink)",
        "--normal-border": "var(--color-line)",
        "--border-radius": "var(--radius-inner)",
        fontFamily: "var(--font-sans)",
      } as React.CSSProperties
    }
    {...props}
  />
)

export { Toaster }
