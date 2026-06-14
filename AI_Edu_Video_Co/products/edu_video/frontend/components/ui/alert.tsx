import * as React from "react";
import { cva, type VariantProps } from "class-variance-authority";
import { Info, CheckCircle2, AlertTriangle, XCircle } from "lucide-react";
import { cn } from "@/lib/utils";

const alertVariants = cva(
  "relative w-full rounded-lg border p-4 flex items-start gap-3 text-sm",
  {
    variants: {
      variant: {
        default:
          "bg-gray-50 dark:bg-gray-800/50 border-gray-200 dark:border-gray-700 text-gray-700 dark:text-gray-300",
        info:
          "bg-blue-50 dark:bg-blue-900/20 border-blue-200 dark:border-blue-800 text-blue-800 dark:text-blue-200",
        success:
          "bg-green-50 dark:bg-green-900/20 border-green-200 dark:border-green-800 text-green-800 dark:text-green-200",
        warning:
          "bg-amber-50 dark:bg-amber-900/20 border-amber-200 dark:border-amber-800 text-amber-800 dark:text-amber-200",
        destructive:
          "bg-red-50 dark:bg-red-900/20 border-red-200 dark:border-red-800 text-red-800 dark:text-red-200",
      },
    },
    defaultVariants: { variant: "default" },
  }
);

const ICON_MAP = {
  default:     Info,
  info:        Info,
  success:     CheckCircle2,
  warning:     AlertTriangle,
  destructive: XCircle,
} as const;

export type AlertProps = React.HTMLAttributes<HTMLDivElement> &
  VariantProps<typeof alertVariants> & {
    title?:       string;
    icon?:        React.ReactNode;
    dismissible?: boolean;
    onDismiss?:   () => void;
  };

const Alert = React.forwardRef<HTMLDivElement, AlertProps>(
  ({ className, variant = "default", title, icon, dismissible, onDismiss, children, ...props }, ref) => {
    const IconComp = ICON_MAP[variant ?? "default"];
    const renderedIcon = icon ?? <IconComp className="h-5 w-5 shrink-0 mt-0.5" aria-hidden />;

    return (
      <div
        ref={ref}
        role="alert"
        className={cn(alertVariants({ variant }), className)}
        {...props}
      >
        {renderedIcon}
        <div className="flex-1 min-w-0">
          {title && <AlertTitle>{title}</AlertTitle>}
          {children && <AlertDescription>{children}</AlertDescription>}
        </div>
        {dismissible && (
          <button
            onClick={onDismiss}
            className="ml-auto shrink-0 opacity-60 hover:opacity-100 transition-opacity focus:outline-none focus:ring-2 focus:ring-current focus:ring-offset-1 rounded-sm"
            aria-label="Dismiss"
          >
            <XCircle className="h-4 w-4" />
          </button>
        )}
      </div>
    );
  }
);
Alert.displayName = "Alert";

function AlertTitle({ className, ...props }: React.HTMLAttributes<HTMLParagraphElement>) {
  return <p className={cn("font-semibold mb-1 leading-none tracking-tight", className)} {...props} />;
}

function AlertDescription({ className, ...props }: React.HTMLAttributes<HTMLParagraphElement>) {
  return <p className={cn("text-sm opacity-90", className)} {...props} />;
}

function AlertIcon({ variant }: { variant?: AlertProps["variant"] }) {
  const IconComp = ICON_MAP[variant ?? "default"];
  return <IconComp className="h-5 w-5 shrink-0 mt-0.5" aria-hidden />;
}

export { Alert, AlertTitle, AlertDescription, AlertIcon };
