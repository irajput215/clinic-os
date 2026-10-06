import { cn } from "@/lib/utils"

/** Two stepped rounded tiles: the Clinic OS mark. */
export function BrandMark({
  size = 46,
  className,
}: {
  size?: number
  className?: string
}) {
  const tile = size * 0.61
  return (
    <span
      aria-hidden
      className={cn("relative inline-block shrink-0", className)}
      style={{ width: size, height: size }}
    >
      <span
        className="absolute rounded-[30%] bg-clay-soft"
        style={{
          left: size * 0.065,
          top: size * 0.065,
          width: tile,
          height: tile,
        }}
      />
      <span
        className="absolute rounded-[30%] bg-clay shadow-[0_6px_16px_rgba(192,91,61,0.32)]"
        style={{
          left: size * 0.337,
          top: size * 0.337,
          width: tile,
          height: tile,
        }}
      />
    </span>
  )
}
