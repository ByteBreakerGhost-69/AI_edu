import * as React from "react";
import { cva, type VariantProps } from "class-variance-authority";
import { cn } from "@/lib/utils";
import { PROJECT_STATUS_LABELS } from "@/types";
import type { ProjectStatus } from "@/types";

const badgeVariants = cva(
  "inline-flex items-center gap-1 px-2 py-0.5 text-xs font-medium rounded-full transition-colors",
  {
    variants: {
      variant: {
        default:
          "bg-blue-100 text-blue-800 dark:bg-blue-900/30 dark:text-blue-300",
        secondary:
          "bg-gray-100 text-gray-800 dark:bg-gray-800 dark:text-gray-300",
        success:
          "bg-green-100 text-green-800 dark:bg-green-900/30 dark:text-green-300",
        warning:
          "bg-amber-100 text-amber-800 dark:bg-amber-900/30 dark:text-amber-300",
        destructive:
          "bg-red-100 text-red-800 dark:bg-red-900/30 dark:text-red-300",
        outline:
          "border border-current bg-transparent text-gray-700 dark:text-gray-300",
        premium:
          "bg-gradient-to-r from-purple-500 to-indigo-500 text-white",
      },
    },
    defaultVariants: { variant: "default" },
  }
);

export type BadgeProps = React.HTMLAttributes<HTMLSpanElement> &
  VariantProps<typeof badgeVariants>;

/** Small status/label indicator chip. */
const Badge = React.forwardRef<HTMLSpanElement, BadgeProps>(
  ({ className, variant, ...props }, ref) => (
    <span
      ref={ref}
      className={cn(badgeVariants({ variant }), className)}
      {...props}
    />
  )
);
Badge.displayName = "Badge";

/** Status-to-variant mapping for project pipeline states. */
const STATUS_VARIANT_MAP: Record<ProjectStatus, BadgeProps["variant"]> = {
  pending:       "secondary",
  queued:        "default",
  orchestrating: "default",
  rendering:     "default",
  review:        "warning",
  done:          "success",
  failed:        "destructive",
  cancelled:     "outline",
};

/** Convenience badge pre-configured for ProjectStatus values. */
function ProjectStatusBadge({
  status,
  className,
}: {
  status: ProjectStatus;
  className?: string;
}) {
  return (
    <Badge variant={STATUS_VARIANT_MAP[status]} className={className}>
      {PROJECT_STATUS_LABELS[status]}
    </Badge>
  );
}

export { Badge, badgeVariants, ProjectStatusBadge };
