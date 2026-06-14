"use client";

import * as React from "react";
import * as SeparatorPrimitive from "@radix-ui/react-separator";
import { cn } from "@/lib/utils";

/** Thin divider line, horizontal or vertical. */
const Separator = React.forwardRef<
  React.ElementRef<typeof SeparatorPrimitive.Root>,
  React.ComponentPropsWithoutRef<typeof SeparatorPrimitive.Root>
>(({ className, orientation = "horizontal", decorative = true, ...props }, ref) => (
  <SeparatorPrimitive.Root
    ref={ref}
    decorative={decorative}
    orientation={orientation}
    className={cn(
      "shrink-0 bg-gray-200 dark:bg-gray-700",
      orientation === "horizontal" ? "h-[1px] w-full" : "h-full w-[1px]",
      className
    )}
    {...props}
  />
));
Separator.displayName = "Separator";

/** Horizontal divider with optional centered text label. */
function SectionDivider({ label, className }: { label?: string; className?: string }) {
  if (!label) return <Separator className={className} />;

  return (
    <div className={cn("flex items-center gap-4", className)}>
      <span className="flex-1 h-px bg-gray-200 dark:bg-gray-700" aria-hidden />
      <span className="text-xs text-gray-400 whitespace-nowrap">{label}</span>
      <span className="flex-1 h-px bg-gray-200 dark:bg-gray-700" aria-hidden />
    </div>
  );
}

export { Separator, SectionDivider };
