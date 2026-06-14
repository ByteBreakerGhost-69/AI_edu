import * as React from "react";
import { cva, type VariantProps } from "class-variance-authority";
import { cn } from "@/lib/utils";

const trackVariants = cva("w-full overflow-hidden rounded-full bg-gray-100 dark:bg-gray-800", {
  variants: {
    size: {
      sm: "h-1.5",
      md: "h-2.5",
      lg: "h-4",
    },
  },
  defaultVariants: { size: "md" },
});

const fillVariants = cva("h-full rounded-full transition-all duration-500 ease-out", {
  variants: {
    variant: {
      default:     "bg-blue-600",
      success:     "bg-green-500",
      warning:     "bg-amber-500",
      destructive: "bg-red-500",
      premium:     "bg-gradient-to-r from-purple-500 to-indigo-500",
    },
  },
  defaultVariants: { variant: "default" },
});

export type ProgressProps = React.HTMLAttributes<HTMLDivElement> &
  VariantProps<typeof fillVariants> &
  VariantProps<typeof trackVariants> & {
    /** Progress value 0–100 */
    value:       number;
    /** Show percentage label below the bar */
    showLabel?:  boolean;
    /** Custom label text (overrides auto percentage) */
    label?:      string;
    /** Pulse/shimmer animation for active render state */
    animated?:   boolean;
  };

/** Visual progress bar for render progress and quota meters. */
const Progress = React.forwardRef<HTMLDivElement, ProgressProps>(
  ({ className, value, variant, size, showLabel, label, animated, ...props }, ref) => {
    const clamped = Math.min(100, Math.max(0, value));

    return (
      <div ref={ref} className={cn("w-full", className)} {...props}>
        <div className={cn(trackVariants({ size }))}>
          <div
            className={cn(
              fillVariants({ variant }),
              animated && "relative overflow-hidden",
            )}
            style={{ width: `${clamped}%` }}
            role="progressbar"
            aria-valuenow={clamped}
            aria-valuemin={0}
            aria-valuemax={100}
          >
            {animated && (
              <span
                className="absolute inset-0 bg-gradient-to-r from-transparent via-white/20 to-transparent animate-[shimmer_1.5s_infinite]"
                aria-hidden
              />
            )}
          </div>
        </div>
        {showLabel && (
          <div className="flex justify-end mt-1">
            <span className="text-xs text-gray-500 dark:text-gray-400">
              {label ?? `${Math.round(clamped)}%`}
            </span>
          </div>
        )}
      </div>
    );
  }
);
Progress.displayName = "Progress";

export { Progress };
