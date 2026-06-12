"use client";

/**
 * providers/index.tsx
 * Root provider composition in the correct nesting order.
 *
 * Order (outermost → innermost):
 *   ThemeProvider         — must be outermost (applies CSS class to <html>)
 *   QueryProvider         — needed by AuthProvider (loads subscription)
 *   AuthProvider          — needed by all authenticated pages
 *   ToastProvider         — uses theme + auth context for styling
 *
 * RealtimeProvider is NOT included here — it is scoped to individual
 * studio / project layouts and requires a projectId prop.
 *
 * Usage in app/layout.tsx:
 *   import { RootProviders } from "@/providers";
 *   <RootProviders>{children}</RootProviders>
 */

import { type ReactNode } from "react";
import { ThemeProvider }  from "./theme-provider";
import { QueryProvider }  from "./query-provider";
import { AuthProvider }   from "./auth-provider";
import { ToastProvider }  from "./toast-provider";

// -------------------------------------------------------------------------- //
// Root provider composition                                                    //
// -------------------------------------------------------------------------- //

type RootProvidersProps = {
  children: ReactNode;
};

/**
 * Compose all global providers in the correct dependency order.
 *
 * @example
 *   // app/layout.tsx
 *   export default function RootLayout({ children }) {
 *     return (
 *       <html lang="en" suppressHydrationWarning>
 *         <body>
 *           <RootProviders>{children}</RootProviders>
 *         </body>
 *       </html>
 *     );
 *   }
 */
export function RootProviders({ children }: RootProvidersProps) {
  return (
    <ThemeProvider>
      <QueryProvider>
        <AuthProvider>
          <ToastProvider>
            {children}
          </ToastProvider>
        </AuthProvider>
      </QueryProvider>
    </ThemeProvider>
  );
}

// -------------------------------------------------------------------------- //
// Named re-exports                                                              //
// -------------------------------------------------------------------------- //

// Auth
export { AuthProvider, useAuth, useAuthUser }          from "./auth-provider";
export type { AuthUser }                                from "./auth-provider";

// Query
export { QueryProvider, QUERY_STALE_TIMES, getQueryClient } from "./query-provider";

// Toast
export { ToastProvider, toast }                        from "./toast-provider";
export type { ToastOptions }                            from "./toast-provider";

// Theme
export { ThemeProvider, useTheme }                     from "./theme-provider";
export type { Theme }                                   from "./theme-provider";

// Realtime (scoped — not in RootProviders)
export { RealtimeProvider, useRealtime, useRealtimeStatus } from "./realtime-provider";
export type { RealtimeStatus }                              from "./realtime-provider";
