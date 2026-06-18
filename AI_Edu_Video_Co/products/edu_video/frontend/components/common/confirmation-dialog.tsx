"use client";

import * as React from "react";
import { AlertTriangle, Info } from "lucide-react";
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogFooter,
  DialogTitle,
  DialogDescription,
} from "@/components/ui/dialog";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { cn } from "@/lib/utils";

// -------------------------------------------------------------------------- //
// ConfirmationDialog                                                           //
// -------------------------------------------------------------------------- //

export type ConfirmationDialogProps = {
  open:             boolean;
  onOpenChange:     (open: boolean) => void;
  title:            string;
  description:      string;
  confirmLabel?:    string;
  cancelLabel?:     string;
  variant?:         "destructive" | "warning" | "default";
  onConfirm:        () => void | Promise<void>;
  isLoading?:       boolean;
  children?:        React.ReactNode;
  confirmDisabled?: boolean;
};

/**
 * Reusable confirmation dialog for destructive or important actions.
 */
export function ConfirmationDialog({
  open,
  onOpenChange,
  title,
  description,
  confirmLabel    = "Confirm",
  cancelLabel     = "Cancel",
  variant         = "destructive",
  onConfirm,
  isLoading,
  children,
  confirmDisabled = false,
}: ConfirmationDialogProps) {
  const [isConfirming, setIsConfirming] = React.useState(false);

  const IconComp = variant === "default" ? Info : AlertTriangle;
  const iconColor =
    variant === "destructive" ? "text-red-500"
    : variant === "warning"   ? "text-amber-500"
    :                           "text-blue-500";

  const loading = isLoading ?? isConfirming;

  const handleConfirm = async () => {
    setIsConfirming(true);
    try {
      await onConfirm();
    } finally {
      setIsConfirming(false);
    }
  };

  const confirmButtonVariant =
    variant === "destructive" ? "destructive" : "default";

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent size="sm">
        <DialogHeader>
          <div className="flex items-center gap-2">
            <IconComp className={cn("h-5 w-5 shrink-0", iconColor)} aria-hidden />
            <DialogTitle className="text-base">{title}</DialogTitle>
          </div>
          <DialogDescription className="mt-2 text-sm text-gray-600 dark:text-gray-400">
            {description}
          </DialogDescription>
        </DialogHeader>

        {children && <div className="mt-1">{children}</div>}

        <DialogFooter className="mt-4">
          <Button
            variant="outline"
            onClick={() => onOpenChange(false)}
            disabled={loading}
          >
            {cancelLabel}
          </Button>
          <Button
            variant={confirmButtonVariant}
            onClick={handleConfirm}
            isLoading={loading}
            disabled={confirmDisabled || loading}
            className={variant === "warning" ? "bg-amber-500 hover:bg-amber-600 text-white" : undefined}
          >
            {confirmLabel}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}

// -------------------------------------------------------------------------- //
// TypedConfirmationDialog                                                      //
// -------------------------------------------------------------------------- //

export type TypedConfirmationDialogProps = ConfirmationDialogProps & {
  /** User must type this exact string to enable the confirm button. */
  confirmText:         string;
  confirmPlaceholder?: string;
};

/**
 * Confirmation dialog that requires the user to type a specific string.
 * Use for irreversible actions like account deletion.
 */
export function TypedConfirmationDialog({
  confirmText,
  confirmPlaceholder,
  children,
  ...props
}: TypedConfirmationDialogProps) {
  const [typed, setTyped] = React.useState("");

  const matches = typed === confirmText;

  // Reset typed value when dialog closes
  React.useEffect(() => {
    if (!props.open) setTyped("");
  }, [props.open]);

  return (
    <ConfirmationDialog
      {...props}
      confirmDisabled={!matches}
    >
      {children}
      <div className="mt-4 space-y-1.5">
        <p className="text-xs text-gray-500 dark:text-gray-400">
          Type{" "}
          <span className="font-mono font-medium text-gray-700 dark:text-gray-300">
            {confirmText}
          </span>{" "}
          to confirm
        </p>
        <Input
          value={typed}
          onChange={(e) => setTyped(e.target.value)}
          placeholder={confirmPlaceholder ?? confirmText}
          autoComplete="off"
          spellCheck={false}
          error={typed.length > 0 && !matches}
        />
      </div>
    </ConfirmationDialog>
  );
}
