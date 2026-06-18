"use client";

import * as React from "react";
import Link from "next/link";
import {
  Video, Search, Receipt, MessageSquare, CheckSquare,
} from "lucide-react";
import { cn } from "@/lib/utils";
import { Button } from "@/components/ui/button";
import type { ButtonProps } from "@/components/ui/button";

// -------------------------------------------------------------------------- //
// Types                                                                        //
// -------------------------------------------------------------------------- //

type ButtonVariant = ButtonProps["variant"];

export type EmptyStateProps = {
  icon?:             React.ReactNode;
  illustration?:     React.ReactNode;
  title:             string;
  description?:      string;
  action?: {
    label:    string;
    onClick?: () => void;
    href?:    string;
    variant?: ButtonVariant;
  };
  secondaryAction?: {
    label:    string;
    onClick?: () => void;
    href?:    string;
    variant?: ButtonVariant;
  };
  size?:      "sm" | "md" | "lg";
  className?: string;
};

// -------------------------------------------------------------------------- //
// EmptyState                                                                   //
// -------------------------------------------------------------------------- //

const SIZE_CONFIG = {
  sm: {
    padding:      "py-8 px-4",
    iconWrapper:  "h-12 w-12 rounded-xl",
    iconSize:     "h-6 w-6",
    titleClass:   "text-base",
  },
  md: {
    padding:      "py-16 px-6",
    iconWrapper:  "h-16 w-16 rounded-2xl",
    iconSize:     "h-8 w-8",
    titleClass:   "text-lg",
  },
  lg: {
    padding:      "py-24 px-8",
    iconWrapper:  "h-20 w-20 rounded-2xl",
    iconSize:     "h-10 w-10",
    titleClass:   "text-xl",
  },
} as const;

/**
 * Zero-state component with optional illustration, title, description, and CTA.
 */
export function EmptyState({
  icon,
  illustration,
  title,
  description,
  action,
  secondaryAction,
  size      = "md",
  className,
}: EmptyStateProps) {
  const cfg = SIZE_CONFIG[size];

  const renderAction = (
    act: NonNullable<EmptyStateProps["action"]>,
    defaultVariant: ButtonVariant
  ) => {
    const btn = (
      <Button variant={act.variant ?? defaultVariant} onClick={act.onClick}>
        {act.label}
      </Button>
    );
    if (act.href) {
      return (
        <Link href={act.href} key={act.label}>
          {btn}
        </Link>
      );
    }
    return btn;
  };

  return (
    <div
      className={cn(
        "flex flex-col items-center justify-center text-center",
        cfg.padding,
        className
      )}
    >
      {illustration ?? (
        icon && (
          <div
            className={cn(
              "mx-auto mb-4 flex items-center justify-center",
              "bg-gray-100 dark:bg-gray-800 text-gray-400 dark:text-gray-500",
              cfg.iconWrapper
            )}
          >
            {React.isValidElement(icon)
              ? React.cloneElement(icon as React.ReactElement<{ className?: string }>, {
                  className: cn(cfg.iconSize, (icon as React.ReactElement<{ className?: string }>).props.className),
                })
              : icon}
          </div>
        )
      )}

      <h3 className={cn("mt-4 font-semibold text-gray-900 dark:text-gray-100", cfg.titleClass)}>
        {title}
      </h3>

      {description && (
        <p className="mt-2 text-sm text-gray-500 dark:text-gray-400 max-w-sm">
          {description}
        </p>
      )}

      {(action || secondaryAction) && (
        <div className="mt-6 flex flex-col sm:flex-row gap-3 items-center justify-center">
          {action          && renderAction(action,          "default")}
          {secondaryAction && renderAction(secondaryAction, "outline")}
        </div>
      )}
    </div>
  );
}

// -------------------------------------------------------------------------- //
// Domain-specific pre-built empty states                                       //
// -------------------------------------------------------------------------- //

export function EmptyProjects({ onCreateClick }: { onCreateClick?: () => void }) {
  return (
    <EmptyState
      icon={<Video />}
      title="No videos yet"
      description="Create your first AI-powered educational video in minutes."
      action={{ label: "Create Video", onClick: onCreateClick }}
    />
  );
}

export function EmptySearchResults({ query, onClear }: { query?: string; onClear?: () => void }) {
  return (
    <EmptyState
      icon={<Search />}
      title={query ? `No results for "${query}"` : "No results found"}
      description="Try different keywords or clear your filters."
      action={{ label: "Clear search", onClick: onClear, variant: "outline" }}
    />
  );
}

export function EmptyInvoices() {
  return (
    <EmptyState
      icon={<Receipt />}
      title="No invoices yet"
      description="Your billing history will appear here after your first payment."
    />
  );
}

export function EmptyFeedback() {
  return (
    <EmptyState
      icon={<MessageSquare />}
      title="No feedback yet"
      description="User feedback on this video will appear here."
    />
  );
}

export function EmptyReviewQueue() {
  return (
    <EmptyState
      icon={<CheckSquare />}
      title="Queue is empty"
      description="All videos have been reviewed. Check back later."
    />
  );  
}
