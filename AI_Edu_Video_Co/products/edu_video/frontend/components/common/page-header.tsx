"use client";

import * as React from "react";
import Link from "next/link";
import { ChevronRight, ArrowLeft } from "lucide-react";
import { cn } from "@/lib/utils";

// -------------------------------------------------------------------------- //
// Types                                                                        //
// -------------------------------------------------------------------------- //

export type BreadcrumbItem = {
  label: string;
  href?: string;
};

export type PageHeaderProps = {
  title:           string;
  subtitle?:       string;
  breadcrumbs?:    BreadcrumbItem[];
  actions?:        React.ReactNode;
  badge?:          React.ReactNode;
  backHref?:       string;
  backLabel?:      string;
  size?:           "sm" | "md" | "lg";
  className?:      string;
  titleClassName?: string;
};

// -------------------------------------------------------------------------- //
// PageHeader                                                                   //
// -------------------------------------------------------------------------- //

/**
 * Consistent page title bar with breadcrumbs, subtitle, and action area.
 * Use at the top of every dashboard page.
 */
export function PageHeader({
  title,
  subtitle,
  breadcrumbs,
  actions,
  badge,
  backHref,
  backLabel = "Back",
  size      = "md",
  className,
  titleClassName,
}: PageHeaderProps) {
  const titleSize =
    size === "sm" ? "text-xl"
    : size === "lg" ? "text-3xl md:text-4xl"
    : "text-2xl md:text-3xl";

  return (
    <header className={cn("mb-6 md:mb-8", className)}>
      {/* Breadcrumbs */}
      {breadcrumbs && breadcrumbs.length > 0 && (
        <nav aria-label="Breadcrumb" className="mb-3 flex items-center gap-1.5 text-sm flex-wrap">
          {breadcrumbs.map((item, i) => (
            <React.Fragment key={`${item.label}-${i}`}>
              {i > 0 && (
                <ChevronRight className="h-3.5 w-3.5 text-gray-400 shrink-0" aria-hidden />
              )}
              {item.href ? (
                <Link
                  href={item.href}
                  className="text-gray-500 hover:text-gray-700 dark:text-gray-400 dark:hover:text-gray-200 transition-colors"
                >
                  {item.label}
                </Link>
              ) : (
                <span className="text-gray-900 dark:text-gray-100 font-medium">
                  {item.label}
                </span>
              )}
            </React.Fragment>
          ))}
        </nav>
      )}

      {/* Back link */}
      {backHref && !breadcrumbs && (
        <Link
          href={backHref}
          className="group mb-3 inline-flex items-center gap-1.5 text-sm text-gray-500 hover:text-gray-700 dark:text-gray-400 dark:hover:text-gray-200 transition-colors"
        >
          <ArrowLeft className="h-4 w-4 transition-transform group-hover:-translate-x-0.5" aria-hidden />
          {backLabel}
        </Link>
      )}

      {/* Title row */}
      <div className="flex flex-col gap-3 sm:flex-row sm:items-start sm:justify-between">
        <div className="flex items-center gap-3 min-w-0">
          <h1
            className={cn(
              "font-bold text-gray-900 dark:text-gray-50 truncate",
              titleSize,
              titleClassName
            )}
          >
            {title}
          </h1>
          {badge && <div className="shrink-0">{badge}</div>}
        </div>

        {actions && (
          <div className="flex items-center gap-2 shrink-0">{actions}</div>
        )}
      </div>

      {/* Subtitle */}
      {subtitle && (
        <p className="mt-1.5 text-sm text-gray-500 dark:text-gray-400 max-w-2xl">
          {subtitle}
        </p>
      )}
    </header>
  );
}
