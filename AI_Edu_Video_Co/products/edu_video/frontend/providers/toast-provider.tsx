"use client";

/**
 * toast-provider.tsx
 * Toast notification system using sonner.
 * Exports both the ToastProvider component and the imperative `toast` API.
 *
 * Usage:
 *   import { toast } from "@/providers/toast-provider";
 *   toast.success("Video created!");
 */

import { type ReactNode } from "react";
import { Toaster, toast as sonnerToast } from "sonner";
import { TOAST_DURATION } from "@/lib/constants";

// -------------------------------------------------------------------------- //
// Types                                                                         //
// -------------------------------------------------------------------------- //

export type ToastOptions = {
  /** Auto-dismiss duration in ms. Omit to use variant default. */
  duration?:    number;
  /** Secondary description text below the title. */
  description?: string;
  /** Unique ID — prevents duplicate toasts with same ID. */
  id?:          string;
  /** Optional action button. */
  action?: {
    label:   string;
    onClick: () => void;
  };
};

// -------------------------------------------------------------------------- //
// Imperative toast API                                                          //
// -------------------------------------------------------------------------- //

/**
 * Global toast API — call anywhere in the codebase (components, services, hooks).
 * Wraps sonner with typed variants and sensible duration defaults.
 *
 * @example
 *   toast.success("Project created!", { description: "It's now in the queue." })
 *   toast.error("Upload failed")
 *   toast.loading("Uploading…", { id: "upload" })
 *   toast.dismiss("upload")
 */
export const toast = {
  /**
   * Show a success notification (green checkmark).
   * Default duration: 4 s.
   */
  success: (message: string, options?: ToastOptions): string | number =>
    sonnerToast.success(message, {
      duration:    options?.duration ?? TOAST_DURATION.normal,
      description: options?.description,
      action:      options?.action
        ? { label: options.action.label, onClick: options.action.onClick }
        : undefined,
      id: options?.id,
    }),

  /**
   * Show an error notification (red).
   * Default duration: 6 s — errors need more reading time.
   */
  error: (message: string, options?: ToastOptions): string | number =>
    sonnerToast.error(message, {
      duration:    options?.duration ?? TOAST_DURATION.long,
      description: options?.description,
      action:      options?.action
        ? { label: options.action.label, onClick: options.action.onClick }
        : undefined,
      id: options?.id,
    }),

  /**
   * Show an info notification (neutral).
   * Default duration: 4 s.
   */
  info: (message: string, options?: ToastOptions): string | number =>
    sonnerToast.info(message, {
      duration:    options?.duration ?? TOAST_DURATION.normal,
      description: options?.description,
      id:          options?.id,
    }),

  /**
   * Show a warning notification (amber).
   * Default duration: 6 s.
   */
  warning: (message: string, options?: ToastOptions): string | number =>
    sonnerToast.warning(message, {
      duration:    options?.duration ?? TOAST_DURATION.long,
      description: options?.description,
      id:          options?.id,
    }),

  /**
   * Show a persistent loading notification.
   * IMPORTANT: Always call toast.dismiss(id) when the operation completes.
   *
   * @returns Toast ID — save this to dismiss later.
   */
  loading: (message: string, options?: ToastOptions): string | number =>
    sonnerToast.loading(message, {
      duration:    options?.duration ?? TOAST_DURATION.persistent,
      description: options?.description,
      id:          options?.id,
    }),

  /**
   * Show a promise toast that transitions loading → success/error automatically.
   *
   * @example
   *   toast.promise(uploadFile(), {
   *     loading: "Uploading your image…",
   *     success: "Image uploaded!",
   *     error:   (err) => `Upload failed: ${err.message}`,
   *   })
   */
  promise: <T>(
    promise: Promise<T>,
    messages: {
      loading: string;
      success: string | ((data: T) => string);
      error:   string | ((error: unknown) => string);
    },
    options?: Omit<ToastOptions, "duration">
  ): Promise<T> =>
    sonnerToast.promise(promise, {
      loading: messages.loading,
      success: messages.success,
      error:   messages.error,
      id:      options?.id,
    }),

  /**
   * Dismiss a specific toast by ID, or all active toasts if no ID given.
   */
  dismiss: (id?: string | number): void => sonnerToast.dismiss(id),

  /**
   * Show a toast with an inline action button.
   * Convenience wrapper for undo / navigate / retry patterns.
   *
   * @example
   *   toast.withAction("Project cancelled", "Undo", () => restoreProject(id))
   */
  withAction: (
    message:     string,
    actionLabel: string,
    onAction:    () => void,
    options?:    Omit<ToastOptions, "action">
  ): string | number =>
    sonnerToast(message, {
      duration:    options?.duration ?? TOAST_DURATION.long,
      description: options?.description,
      action:      { label: actionLabel, onClick: onAction },
      id:          options?.id,
    }),
};

// -------------------------------------------------------------------------- //
// Provider component                                                             //
// -------------------------------------------------------------------------- //

/**
 * Toast notification provider.
 * Renders the sonner Toaster — place near the root, inside ThemeProvider.
 * The `toast` export above works without this component being mounted,
 * but notifications will not appear until Toaster is rendered.
 */
export function ToastProvider({ children }: { children: ReactNode }) {
  return (
    <>
      {children}
      <Toaster
        position="bottom-right"
        expand={false}
        richColors
        closeButton
        toastOptions={{
          classNames: {
            toast:        "font-sans text-sm shadow-lg border rounded-lg",
            title:        "font-medium",
            description:  "text-xs opacity-80 mt-0.5",
            actionButton: "bg-primary text-primary-foreground text-xs font-medium px-2.5 py-1 rounded-md",
            cancelButton: "bg-muted text-muted-foreground text-xs px-2.5 py-1 rounded-md",
            closeButton:  "bg-background border border-border text-muted-foreground hover:text-foreground",
          },
        }}
      />
    </>
  );
    }
