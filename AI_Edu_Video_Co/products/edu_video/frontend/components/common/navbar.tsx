"use client";

import * as React from "react";
import Link from "next/link";
import { Menu, X, Plus, Bell } from "lucide-react";
import { cn } from "@/lib/utils";
import { Button } from "@/components/ui/button";
import { UserAvatar } from "@/components/ui/avatar";
import { Badge } from "@/components/ui/badge";
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
  DialogDescription,
} from "@/components/ui/dialog";
import { WithTooltip } from "@/components/ui/tooltip";
import { useAuth } from "@/providers";
import { useSubscription } from "@/hooks/use-subscription";
import { useCreateProject } from "@/hooks/use-project-data";
import { ROUTES } from "@/lib/constants";

// -------------------------------------------------------------------------- //
// NavbarProps                                                                  //
// -------------------------------------------------------------------------- //

export type NavbarProps = {
  onMenuToggle?: () => void;
  sidebarOpen?:  boolean;
};

// -------------------------------------------------------------------------- //
// UserMenu                                                                     //
// -------------------------------------------------------------------------- //

function UserMenu() {
  const { user, logout } = useAuth();
  const { isPremium }    = useSubscription();
  const [open, setOpen]  = React.useState(false);

  if (!user) return null;

  return (
    <>
      <button
        onClick={() => setOpen(true)}
        className="flex items-center gap-2 rounded-lg px-2 py-1.5 hover:bg-gray-100 dark:hover:bg-gray-800 transition-colors focus:outline-none focus:ring-2 focus:ring-blue-500 focus:ring-offset-2"
        aria-label="Open user menu"
      >
        <UserAvatar user={user} size="sm" />
        <span className="hidden md:block text-sm font-medium text-gray-700 dark:text-gray-300 max-w-[120px] truncate">
          {user.fullName ?? user.email}
        </span>
      </button>

      <Dialog open={open} onOpenChange={setOpen}>
        <DialogContent size="sm">
          <DialogHeader>
            <DialogTitle className="flex items-center gap-3">
              <UserAvatar user={user} size="md" />
              <div className="min-w-0">
                <p className="text-sm font-semibold text-gray-900 dark:text-gray-100 truncate">
                  {user.fullName ?? user.email}
                </p>
                <p className="text-xs text-gray-500 truncate">{user.email}</p>
              </div>
            </DialogTitle>
            <DialogDescription className="sr-only">User account menu</DialogDescription>
          </DialogHeader>

          <div className="mt-2 flex flex-col gap-1">
            <Link
              href={ROUTES.dashboard}
              onClick={() => setOpen(false)}
              className="rounded-lg px-3 py-2 text-sm text-gray-700 dark:text-gray-300 hover:bg-gray-100 dark:hover:bg-gray-800 transition-colors"
            >
              Dashboard
            </Link>
            <Link
              href={ROUTES.billing}
              onClick={() => setOpen(false)}
              className="rounded-lg px-3 py-2 text-sm text-gray-700 dark:text-gray-300 hover:bg-gray-100 dark:hover:bg-gray-800 transition-colors flex items-center justify-between"
            >
              Billing
              <Badge variant={isPremium ? "premium" : "secondary"} className="text-xs">
                {isPremium ? "Premium" : "Free"}
              </Badge>
            </Link>
            {!isPremium && (
              <Link
                href={ROUTES.billingUpgrade}
                onClick={() => setOpen(false)}
                className="rounded-lg px-3 py-2 text-sm font-medium text-purple-600 dark:text-purple-400 hover:bg-purple-50 dark:hover:bg-purple-900/20 transition-colors"
              >
                Upgrade to Premium →
              </Link>
            )}
          </div>

          <div className="mt-2 border-t border-gray-100 dark:border-gray-800 pt-2">
            <button
              onClick={() => { setOpen(false); logout(); }}
              className="w-full rounded-lg px-3 py-2 text-left text-sm text-red-600 dark:text-red-400 hover:bg-red-50 dark:hover:bg-red-900/20 transition-colors"
            >
              Sign out
            </button>
          </div>
        </DialogContent>
      </Dialog>
    </>
  );
}

// -------------------------------------------------------------------------- //
// Navbar                                                                       //
// -------------------------------------------------------------------------- //

/**
 * Dashboard top navigation bar.
 * Fixed at top; accounts for the 64px (w-64) sidebar on desktop.
 */
export function Navbar({ onMenuToggle, sidebarOpen = false }: NavbarProps) {
  const { isQuotaExceeded } = useSubscription() as ReturnType<typeof useSubscription> & { isQuotaExceeded?: boolean };
  const { openModal }       = useCreateProject();

  return (
    <header
      className={cn(
        "sticky top-0 z-20 flex h-16 items-center gap-4",
        "border-b border-gray-200 dark:border-gray-800",
        "bg-white/80 dark:bg-gray-900/80 backdrop-blur-md",
        "px-4 md:px-6 lg:pl-72"
      )}
    >
      {/* Mobile menu toggle */}
      <Button
        variant="ghost"
        size="icon"
        className="lg:hidden shrink-0"
        onClick={onMenuToggle}
        aria-label={sidebarOpen ? "Close sidebar" : "Open sidebar"}
      >
        {sidebarOpen ? <X className="h-5 w-5" /> : <Menu className="h-5 w-5" />}
      </Button>

      {/* Center spacer */}
      <div className="flex-1" />

      {/* Right-side actions */}
      <div className="flex items-center gap-2">
        {/* Create video CTA */}
        <WithTooltip
          content={
            isQuotaExceeded
              ? "Monthly quota reached — upgrade to Premium"
              : "Create a new educational video"
          }
        >
          <Button
            size="sm"
            variant={isQuotaExceeded ? "outline" : "default"}
            onClick={openModal}
            className="gap-1.5"
          >
            <Plus className="h-4 w-4" aria-hidden />
            <span className="hidden sm:inline">New Video</span>
          </Button>
        </WithTooltip>

        {/* Notifications placeholder */}
        <WithTooltip content="Notifications">
          <Button variant="ghost" size="icon" aria-label="Notifications" disabled>
            <Bell className="h-5 w-5" />
          </Button>
        </WithTooltip>

        {/* User menu */}
        <UserMenu />
      </div>
    </header>
  );
}
