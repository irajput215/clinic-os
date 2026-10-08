import { Slot } from "@radix-ui/react-slot"
import { cva, type VariantProps } from "class-variance-authority"
import type * as React from "react"

import { cn } from "@/lib/utils"

const buttonVariants = cva(
  "inline-flex shrink-0 items-center justify-center gap-1.5 whitespace-nowrap rounded-btn border border-transparent font-semibold transition-[background-color,border-color,color,box-shadow] outline-none focus-visible:ring-[3px] focus-visible:ring-clay/25 disabled:pointer-events-none disabled:opacity-50 [&_svg]:pointer-events-none [&_svg]:shrink-0 [&_svg:not([class*='size-'])]:size-4",
  {
    variants: {
      variant: {
        default: "bg-clay text-white hover:bg-clay-hover",
        destructive: "bg-danger text-white hover:bg-danger-deep",
        outline:
          "border-line bg-paper text-ink hover:border-stone-faint hover:bg-oat",
        secondary: "bg-fill text-ink hover:bg-line",
        ghost: "text-stone hover:bg-fill hover:text-ink",
        link: "h-auto border-0 px-0 font-medium text-clay hover:underline underline-offset-4",
      },
      // Below 1024 px (touch-sized screens) every size is at least a 44 px target.
      size: {
        default: "h-9 px-4 text-[13.5px] max-lg:h-11",
        sm: "h-[29px] px-[11px] text-[12.5px] max-lg:h-11 max-lg:px-3.5",
        lg: "h-11 px-5 text-[14px]",
        icon: "size-9 max-lg:size-11",
        "icon-sm": "size-[30px] max-lg:size-11",
      },
    },
    defaultVariants: {
      variant: "default",
      size: "default",
    },
  },
)

function Button({
  className,
  variant,
  size,
  asChild = false,
  ...props
}: React.ComponentProps<"button"> &
  VariantProps<typeof buttonVariants> & {
    asChild?: boolean
  }) {
  const Comp = asChild ? Slot : "button"

  return (
    <Comp
      data-slot="button"
      className={cn(buttonVariants({ variant, size, className }))}
      {...props}
    />
  )
}

export { Button, buttonVariants }
