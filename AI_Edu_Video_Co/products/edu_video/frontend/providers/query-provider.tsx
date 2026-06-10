"use client";

/**
 * query-provider.tsx
 * TanStack Query v5 provider with production-grade configuration.
 * Wraps the entire app — place in root layout.tsx.
 *
 * Configuration decisions:
 *   - staleTime: 30s — project status changes frequently during processing
 *   - gcTime: 5min — keep completed project data in memory
 *   - retry: custom — don't retry 4xx, retry 5xx up to 3 times
 *   - refetchOnWindowFocus: true — pick up status changes when returning to tab
 */

import React from "react";
import {
  QueryClient,
  QueryClientProvider,
  type QueryClientConfig,
} from "@tanstack/react-query";
import { ReactQueryDevtools } from "@tanstack/react-query-devtools";
import { ApiError } from "@/lib/api/client";

// -------------------------------------------------------------------------- //
// QueryClient factory                                                           //
// -------------------------------------------------------------------------- //

function createQueryClient(): QueryClient {
  const config: QueryClientConfig = {
    defaultOptions: {
      queries: {
        staleTime:            30_000,   // 30 s — data considered fresh
        gcTime:               5 * 60 * 1000, // 5 min — keep in cache after unmount
        refetchOnWindowFocus: true,
        refetchOnReconnect:   true,
        retry: (failureCount, error) => {
          // Never retry 4xx — these are definitive answers
          if (error instanceof ApiError && error.statusCode < 500) return false;
          // Retry 5xx up to 3 times
          return failureCount < 3;
        },
        retryDelay: (attempt) => Math.min(1000 * 2 ** attempt, 10_000),
      },
      mutations: {
        retry: false,   // Never auto-retry mutations — user should be informed
        onError: (error) => {
          // Mutations propagate errors to the calling hook — no global handler needed
          if (process.env.NODE_ENV === "development") {
            console.error("[QueryClient mutation error]", error);
          }
        },
      },
    },
  };
  return new QueryClient(config);
}

// Singleton for server components and SSR hydration
let browserQueryClient: QueryClient | undefined;

function getQueryClient(): QueryClient {
  if (typeof window === "undefined") {
    // Server: always create a new client (never share between requests)
    return createQueryClient();
  }
  if (!browserQueryClient) {
    browserQueryClient = createQueryClient();
  }
  return browserQueryClient;
}

// -------------------------------------------------------------------------- //
// Provider component                                                             //
// -------------------------------------------------------------------------- //

type QueryProviderProps = {
  children: React.ReactNode;
};

/**
 * TanStack Query provider.
 * Must wrap the root layout. Includes devtools in development.
 *
 * @example
 *   // app/layout.tsx
 *   export default function RootLayout({ children }) {
 *     return (
 *       <html>
 *         <body>
 *           <QueryProvider>{children}</QueryProvider>
 *         </body>
 *       </html>
 *     );
 *   }
 */
export function QueryProvider({ children }: QueryProviderProps): React.ReactElement {
  const queryClient = getQueryClient();

  return (
    <QueryClientProvider client={queryClient}>
      {children}
      {process.env.NODE_ENV === "development" && (
        <ReactQueryDevtools initialIsOpen={false} />
      )}
    </QueryClientProvider>
  );
}
