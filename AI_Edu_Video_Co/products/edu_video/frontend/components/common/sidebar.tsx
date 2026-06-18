"use client";

import * as React from "react";
import Link from "next/link";
import { usePathname } from "next/navigation";
import {
  LayoutDashboard, Video, BarChart3, CreditCard,
  ClipboardCheck, TrendingUp, Users, PlayCircle,
  X, Crown,
} from "lucide-react";
import { cn } from "@/lib/utils";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Progress } from "@/components/ui/progress";
import { Separator } from "@/components/ui/separator";
import { UserAvatar } from "@/components/ui/avatar";
import { useAuth } from "@/providers";
import { useSubscription } from "@/hooks/use-subscription";
import { ROUTES, APP_NAME } from "@/lib/constants";

// -------------------------------------------------------------------------- //
// Nav config                                                                   //
// -------------------------------------------------------------------------- //

type NavItem = {
  label: string;
  href:  string;
  icon:  React.ReactNode;
  badge?: string | number;
  exact?: boolean;
};

const SIDEBAR_NAV: NavItem[] = [
  { label: "Dashboard", href: ROUTES.dashboard,  icon: <LayoutDashboard className="h-5 w-5" />, exact: true },
  { label: "My Videos", href: ROUTES.projects,   icon: <Video className="h-5 w-5" /> },
  { label: "Usage",     href: ROUTES.usage,      icon: <BarChart3 className="h-5 w-5" /> },
  { label: "Billing",   href: ROUTES.billing,    icon: <CreditCard className="h-5 w-5" /> },
];

const ADMIN_NAV: NavItem[] = [
  { label: "Review Queue", href: ROUTES.adminReviewQueue, icon: <ClipboardCheck className="h-5 w-5" /> },
  { label: "Analytics",    href: ROUTES.adminAnalytics,   icon: <TrendingUp className="h-5 w-5" /> },
  { label: "Users",        href: ROUTES.adminUsers,        icon: <Users className="h-5 w-5" /> },
];

// -------------------------------------------------------------------------- //
// NavLink                                                                      //
// -------------------------------------------------------------------------- //

function NavLink({ item }: { item: NavItem }) {
  const pathname = usePathname();
  const isActive = item.exact
    ? pathname === item.href
    : pathname.startsWith(item.href);

  return (
    <Link
      href={item.href}
      className={cn(
        "flex items-center gap-3 rounded-lg px-3 py-2.5 text-sm transition-colors duration-150",
        isActive
          ? "bg-blue-50 dark:bg-blue-900/20 text-blue-700 dark:text-blue-300 font-medium"
          : "text-gray-600 dark:text-gray-400 hover:bg-gray-100 dark:hover:bg-gray-800 hover:text-gray-900 dark:hover:text-gray-200"
      )}
    >
      <span className="shrink-0">{item.icon}</span>
      <span className="truncate">{item.label}</span>
      {item.badge !== undefined && (
        <Badge variant="secondary" className="ml-auto text-xs px-1.5">
          {item.badge}
        </Badge>
      )}
    </Link>
  );
}

// -------------------------------------------------------------------------- //
// SidebarContent                                                               //
// -------------------------------------------------------------------------- //

function SidebarContent({ onClose }: { onClose?: () => void }) {
  const { user } = useAuth();
  const { tier, isPremium, quotaUsed, quotaLimit, quotaPercent } = useSubscription();

  const progressVariant =
    quotaPercent >= 80 ? "destructive"
    : quotaPercent >= 60 ? "warning"
    : "default";

  return (
    <div className="flex h-full flex-col">
      {/* Logo */}
      <div className="flex items-center gap-2.5 px-4 py-5">
        <PlayCircle className="h-7 w-7 text-blue-500 shrink-0" aria-hidden />
        <span className="text-lg font-bold text-gray-900 dark:text-white">
          {APP_NAME}
        </span>
        {onClose && (
          <Button
            variant="ghost"
            size="icon"
            className="ml-auto lg:hidden h-8 w-8"
            onClick={onClose}
            aria-label="Close sidebar"
          >
            <X className="h-4 w-4" />
          </Button>
        )}
      </div>

      {/* Primary nav */}
      <nav className="mt-2 flex-1 space-y-0.5 px-3 overflow-y-auto">
        {SIDEBAR_NAV.map((item) => (
          <NavLink key={item.href} item={item} />
        ))}

        {/* Admin section */}
        {user?.role === "admin" && (
          <>
            <div className="mt-4 mb-1">
              <Separator />
              <p className="mt-2 px-3 text-xs font-semibold uppercase tracking-wider text-gray-400">
                Admin
              </p>
            </div>
            {ADMIN_NAV.map((item) => (
              <NavLink key={item.href} item={item} />
            ))}
          </>
        )}
      </nav>

      {/* Quota meter */}
      <div className="mx-3 mt-auto mb-2 rounded-xl border border-gray-200 dark:border-gray-700/50 bg-gray-50 dark:bg-gray-800/50 p-3">
        {isPremium ? (
          <div className="flex items-center gap-1.5">
            <Crown className="h-3.5 w-3.5 text-amber-500 shrink-0" aria-hidden />
            <span className="text-xs font-medium text-amber-600 dark:text-amber-400">
              Premium Plan
            </span>
          </div>
        ) : (
          <>
            <div className="mb-2 flex items-center justify-between">
              <span className="text-xs text-gray-500">Videos this month</span>
              <span className="text-xs font-medium text-gray-700 dark:text-gray-300">
                {quotaUsed ?? 0} / {quotaLimit ?? 3}
              </span>
            </div>
            <Progress value={quotaPercent ?? 0} variant={progressVariant} size="sm" />
            {(quotaPercent ?? 0) > 50 && (
              <Link
                href={ROUTES.billingUpgrade}
                className="mt-2 block text-xs text-blue-500 hover:text-blue-600 transition-colors"
              >
                Upgrade for more →
              </Link>
            )}
          </>
        )}
      </div>

      {/* User section */}
      {user && (
        <div className="mx-3 mb-3">
          <div className="flex items-center gap-3 rounded-xl p-3 hover:bg-gray-100 dark:hover:bg-gray-800 cursor-pointer transition-colors">
            <UserAvatar user={user} size="sm" />
            <div className="flex-1 min-w-0">
              <p className="text-sm font-medium text-gray-900 dark:text-gray-100 truncate">
                {user.fullName ?? user.email}
              </p>
              <p className="text-xs text-gray-500 truncate">{user.email}</p>
            </div>
            <Badge variant={isPremium ? "premium" : "secondary"} className="shrink-0 text-xs">
              {isPremium ? "Pro" : "Free"}
            </Badge>
          </div>
        </div>
      )}
    </div>
  );
}

// -------------------------------------------------------------------------- //
// Sidebar                                                                      //
// -------------------------------------------------------------------------- //

export type SidebarProps = {
  open?:    boolean;
  onClose?: () => void;
};

/**
 * Dashboard sidebar — fixed on desktop, slide-out drawer on mobile.
 */
export function Sidebar({ open = false, onClose }: SidebarProps) {
  const basePanel = "fixed left-0 top-0 h-full w-64 bg-white dark:bg-gray-900 border-r border-gray-200 dark:border-gray-800 flex flex-col";

  return (
    <>
      {/* Desktop */}
      <aside className={cn(basePanel, "z-30 hidden lg:flex")}>
        <SidebarContent />
      </aside>

      {/* Mobile drawer */}
      {open && (
        <>
          {/* Backdrop */}
          <div
            className="fixed inset-0 z-40 bg-black/40 backdrop-blur-sm lg:hidden"
            onClick={onClose}
            aria-hidden
          />
          {/* Panel */}
          <aside
            className={cn(
              basePanel,
              "z-50 w-72 shadow-xl lg:hidden",
              "animate-in slide-in-from-left duration-200"
            )}
          >
            <SidebarContent onClose={onClose} />
          </aside>
        </>
      )}
    </>
  );
            }
