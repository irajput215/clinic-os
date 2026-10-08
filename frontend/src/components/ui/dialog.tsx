import * as React from "react"
import * as DialogPrimitive from "@radix-ui/react-dialog"
import { XIcon } from "lucide-react"

import { cn } from "@/lib/utils"

function Dialog({
  ...props
}: React.ComponentProps<typeof DialogPrimitive.Root>) {
  return <DialogPrimitive.Root data-slot="dialog" {...props} />
}

function DialogTrigger({
  ...props
}: React.ComponentProps<typeof DialogPrimitive.Trigger>) {
  return <DialogPrimitive.Trigger data-slot="dialog-trigger" {...props} />
}

function DialogPortal({
  ...props
}: React.ComponentProps<typeof DialogPrimitive.Portal>) {
  return <DialogPrimitive.Portal data-slot="dialog-portal" {...props} />
}

function DialogClose({
  ...props
}: React.ComponentProps<typeof DialogPrimitive.Close>) {
  return <DialogPrimitive.Close data-slot="dialog-close" {...props} />
}

function DialogOverlay({
  className,
  ...props
}: React.ComponentProps<typeof DialogPrimitive.Overlay>) {
  return (
    <DialogPrimitive.Overlay
      data-slot="dialog-overlay"
      className={cn(
        "data-[state=open]:animate-in data-[state=closed]:animate-out data-[state=closed]:fade-out-0 data-[state=open]:fade-in-0 fixed inset-0 z-50 bg-ink/35 backdrop-blur-[2px]",
        className
      )}
      {...props}
    />
  )
}

function DialogContent({
  className,
  children,
  showCloseButton = true,
  onAnimationEnd,
  ...props
}: React.ComponentProps<typeof DialogPrimitive.Content> & {
  showCloseButton?: boolean
}) {
  // The first field is focused while the dialog is still zooming in, and the scroll that brings it
  // into view is measured on that scaled frame, so it can end up under the sticky footer. Once
  // the dialog has settled, bring the focused field fully into view (honouring the scroll padding).
  const settle = (event: React.AnimationEvent<HTMLDivElement>) => {
    onAnimationEnd?.(event)
    const frame = event.currentTarget
    if (event.target !== frame || frame.dataset.state !== "open") return
    const focused = document.activeElement
    if (focused instanceof HTMLElement && frame.contains(focused))
      focused.scrollIntoView({ block: "nearest" })
  }
  return (
    <DialogPortal data-slot="dialog-portal">
      <DialogOverlay />
      {/* The frame never scrolls; its body does. Inside the body, DialogHeader and DialogFooter
          are sticky, so the title and the actions stay on screen however long the form is, and
          the close button sits on the frame, above both. */}
      <DialogPrimitive.Content
        data-slot="dialog-content"
        className={cn(
          "bg-paper data-[state=open]:animate-in data-[state=closed]:animate-out data-[state=closed]:fade-out-0 data-[state=open]:fade-in-0 data-[state=closed]:zoom-out-95 data-[state=open]:zoom-in-95 fixed top-[50%] left-[50%] z-50 flex w-full max-w-[calc(100%-2rem)] translate-x-[-50%] translate-y-[-50%] flex-col overflow-hidden rounded-card border border-line shadow-pop duration-200 sm:max-w-lg max-h-[calc(100dvh-2rem)]",
          className
        )}
        {...props}
        onAnimationEnd={settle}
      >
        <div
          data-slot="dialog-body"
          // The scroll padding keeps a focused field clear of the sticky header and footer.
          className="grid min-h-0 flex-1 scroll-pt-40 scroll-pb-36 gap-4 overflow-y-auto overscroll-contain p-6"
        >
          {children}
        </div>
        {showCloseButton && (
          <DialogPrimitive.Close
            data-slot="dialog-close"
            className="absolute top-3 right-3 z-20 grid size-8 place-items-center rounded-btn text-stone transition-colors hover:bg-fill hover:text-ink disabled:pointer-events-none max-lg:top-2 max-lg:right-2 max-lg:size-11 [&_svg]:pointer-events-none [&_svg]:shrink-0 [&_svg:not([class*='size-'])]:size-4"
          >
            <XIcon />
            <span className="sr-only">Close</span>
          </DialogPrimitive.Close>
        )}
      </DialogPrimitive.Content>
    </DialogPortal>
  )
}

function DialogHeader({ className, ...props }: React.ComponentProps<"div">) {
  return (
    <div
      data-slot="dialog-header"
      // Sticky at the top of the dialog body: it reaches into the body's 24 px padding (`-mt-6`)
      // so nothing shows above it, and sticks there (`-top-6`: a sticky offset is measured from the
      // body's content edge, inside the padding). `pr-14` keeps it clear of the close button.
      className={cn(
        "sticky -top-6 z-10 -mx-6 -mt-6 flex flex-col gap-2 bg-paper px-6 pt-6 pb-2 pr-14 text-left",
        className
      )}
      {...props}
    />
  )
}

function DialogFooter({ className, ...props }: React.ComponentProps<"div">) {
  return (
    <div
      data-slot="dialog-footer"
      className={cn(
        // Sticky at the bottom of the dialog body (mirroring the header), so the primary action is
        // always on screen.
        "sticky -bottom-6 z-10 -mx-6 -mb-6 flex flex-col-reverse gap-2 bg-paper px-6 pt-3 pb-6 shadow-[0_-1px_0_var(--color-line-faint)] max-sm:pb-4 sm:flex-row sm:justify-end",
        className
      )}
      {...props}
    />
  )
}

function DialogTitle({
  className,
  ...props
}: React.ComponentProps<typeof DialogPrimitive.Title>) {
  return (
    <DialogPrimitive.Title
      data-slot="dialog-title"
      className={cn("font-serif text-[22px] leading-tight font-medium", className)}
      {...props}
    />
  )
}

function DialogDescription({
  className,
  ...props
}: React.ComponentProps<typeof DialogPrimitive.Description>) {
  return (
    <DialogPrimitive.Description
      data-slot="dialog-description"
      className={cn("text-stone text-sm", className)}
      {...props}
    />
  )
}

export {
  Dialog,
  DialogClose,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogOverlay,
  DialogPortal,
  DialogTitle,
  DialogTrigger,
}
