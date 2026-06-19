"use client";

import { useState, useEffect, type ReactNode } from "react";
import { usePathname } from "next/navigation";
import { Navbar } from "@/components/common/navbar";
import { Sidebar } from "@/components/common/sidebar";
import { cn } from "@/lib/utils";

// -------------------------------------------------------------------------- //
// Types                                                                        //
// -------------------------------------------------------------------------- //

const MAX_WIDTH_CLASSES = {
  sm:   "max-w-2xl",
  md:   "max-w-4xl",
  lg:   "max-w-6xl",
  xl:   "max-w-7xl",
  full: "",
} as const;

export type DashboardLayoutProps = {
  children:   ReactNode;
  /**
   * Remove default padding from the main content area.
   * Use for full-bleed pages (analytics, studio preview).
   */
  noPadding?: boolean;
  /**
   * Constrain the content area width.
   * Defaults to "xl" (max-w-7xl).
   */
  maxWidth?:  keyof typeof MAX_WIDTH_CLASSES;
  /**
   * Additional className applied to the <main> element.
   */
  className?: string;
};

// -------------------------------------------------------------------------- //
// DashboardLayout                                                              //
// -------------------------------------------------------------------------- //

/**
 * Shell for all authenticated dashboard pages.
 * Coordinates the fixed sidebar, sticky navbar, and scrollable main content.
 *
 * Sidebar is fixed on desktop (lg+) and slides in as a drawer on mobile.
 * The main content area is offset by the sidebar width (lg:pl-64) on desktop.
 *
 * @example
 *   // app/(dashboard)/layout.tsx
 *   export default function Layout({ children }) {
 *     return <DashboardLayout>{children}</DashboardLayout>;
 *   }
 */
export function DashboardLayout({
  children,
  noPadding = false,
  maxWidth  = "xl",
  className,
}: DashboardLayoutProps) {
  const [sidebarOpen, setSidebarOpen] = useState(false);
  const pathname = usePathname();

  // Close mobile sidebar on every route change
  useEffect(() => {
    setSidebarOpen(false);
  }, [pathname]);

  const maxWidthClass = MAX_WIDTH_CLASSES[maxWidth];

  return (
    <div className="min-h-screen bg-gray-50 dark:bg-gray-950">
      {/* Sidebar — fixed on desktop, drawer on mobile */}
      <Sidebar
        open={sidebarOpen}
        onClose={() => setSidebarOpen(false)}
      />

      {/* Right-side shell — offset by sidebar width on desktop */}
      <div className="flex min-h-screen flex-col lg:pl-64">
        {/* Sticky top navbar */}
        <Navbar
          onMenuToggle={() => setSidebarOpen((v) => !v)}
          sidebarOpen={sidebarOpen}
        />

        {/* Page content */}
        <main
          className={cn(
            "flex-1",
            !noPadding && "p-4 sm:p-6 md:p-8",
            maxWidthClass,
            maxWidth !== "full" && "mx-auto w-full",
            className
          )}
        >
          {children}
        </main>
      </div>
    </div>
  );
}
