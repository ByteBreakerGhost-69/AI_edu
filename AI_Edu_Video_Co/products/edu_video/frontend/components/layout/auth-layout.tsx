import type { ReactNode } from "react";
import { PlayCircle } from "lucide-react";
import { cn } from "@/lib/utils";
import { APP_NAME } from "@/lib/constants";

// -------------------------------------------------------------------------- //
// Types                                                                        //
// -------------------------------------------------------------------------- //

export type AuthLayoutProps = {
  children:     ReactNode;
  /**
   * Content above the card. Defaults to logo + tagline.
   */
  heading?:     ReactNode;
  /**
   * Content below the card. Defaults to ToS + Privacy links.
   */
  footer?:      ReactNode;
  /**
   * Background style variant.
   * "default" — subtle gradient (light) / deep dark gradient (dark).
   * "plain"   — solid background, no gradient.
   */
  background?:  "default" | "plain";
};

// -------------------------------------------------------------------------- //
// AuthLayout                                                                   //
// -------------------------------------------------------------------------- //

/**
 * Centered card layout for authentication pages (login, register, reset).
 * Server component — no client-side JavaScript required.
 *
 * @example
 *   // app/(auth)/layout.tsx
 *   export default function Layout({ children }) {
 *     return <AuthLayout>{children}</AuthLayout>;
 *   }
 */
export function AuthLayout({
  children,
  heading,
  footer,
  background = "default",
}: AuthLayoutProps) {
  return (
    <div
      className={cn(
        "min-h-screen flex flex-col items-center justify-center px-4 py-12",
        background === "default"
          ? [
              "bg-gradient-to-br from-gray-50 via-white to-blue-50/30",
              "dark:from-gray-950 dark:via-gray-900 dark:to-blue-950/20",
            ]
          : "bg-gray-50 dark:bg-gray-950"
      )}
    >
      {/* Branding / heading */}
      <div className="mb-8 text-center">
        {heading ?? (
          <>
            <div className="flex items-center justify-center gap-2.5 mb-4">
              <div className="flex h-10 w-10 items-center justify-center rounded-xl bg-blue-600">
                <PlayCircle className="h-6 w-6 text-white" aria-hidden />
              </div>
              <span className="text-2xl font-bold text-gray-900 dark:text-white">
                {APP_NAME}
              </span>
            </div>
            <p className="text-sm text-gray-500 dark:text-gray-400 max-w-sm">
              AI-powered educational videos for every curriculum
            </p>
          </>
        )}
      </div>

      {/* Card */}
      <div
        className={cn(
          "w-full max-w-md rounded-2xl p-8",
          "border border-gray-200 dark:border-gray-700/50",
          "bg-white dark:bg-gray-900",
          "shadow-xl shadow-black/5 dark:shadow-black/20"
        )}
      >
        {children}
      </div>

      {/* Footer */}
      <div className="mt-8">
        {footer ?? (
          <p className="text-center text-xs text-gray-400 dark:text-gray-500">
            By continuing, you agree to our{" "}
            <a
              href="/terms"
              className="underline hover:text-gray-600 dark:hover:text-gray-300 transition-colors"
            >
              Terms of Service
            </a>{" "}
            and{" "}
            <a
              href="/privacy"
              className="underline hover:text-gray-600 dark:hover:text-gray-300 transition-colors"
            >
              Privacy Policy
            </a>
          </p>
        )}
      </div>
    </div>
  );
}
