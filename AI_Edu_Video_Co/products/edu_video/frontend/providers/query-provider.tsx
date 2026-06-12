"use client";

/**
 * query-provider.tsx
 * TanStack Query client configuration and provider.
 * Tuned for educational video content access patterns.
 */

import { useState, type ReactNode } from "react";
import {
  QueryClient,
  QueryClientProvider,
  type QueryClientConfig,
} from "@tanstack/react-query";
import { ReactQueryDevtools } from "@tanstack/react-query-devtools";
import type { ApiError } from "@/lib/api/client";

// -------------------------------------------------------------------------- //
// Stale time constants                                                          //
// -------------------------------------------------------------------------- //

/**
 * Per-query-type stale times.
 * Apply via staleTime option in individual useQuery calls.
 */
export const QUERY_STALE_TIMES = {
  /** Project status — changes rapidly during rendering. */
  projectStatus: 3_000,
  /** Project list — changes on create / cancel. */
  projectList: 2 * 60 * 1_000,
  /** Quota — must reflect recent charges promptly. */
  quota: 30_000,
  /** Subscription — changes rarely. */
  subscription: 5 * 60 * 1_000,
  /** Invoices — historical, rarely changes. */
  invoices: 15 * 60 * 1_000,
  /** Review queue — admin needs fresh data. */
  reviewQueue: 15_000,
} as const;

// -------------------------------------------------------------------------- //
// QueryClient factory                                                           //
// -------------------------------------------------------------------------- //

function makeQueryClient(): QueryClient {
  const config: QueryClientConfig = {
    defaultOptions: {
      queries: {
        staleTime:            5 * 60 * 1_000,  // 5 min default
        gcTime:               30 * 60 * 1_000, // 30 min cache after unmount
        refetchOnWindowFocus: false,
        refetchOnReconnect:   false,
        retry: (failureCount, error) => {
          const err = error as ApiError;
          // Never retry 4xx — these are definitive answers
          if (typeof err?.statusCode === "number" && err.statusCode >= 400 && err.statusCode < 500) {
            return false;
          }
          return failureCount < 2;
        },
        retryDelay: (attempt) => Math.min(1_000 * 2 ** attempt, 30_000),
      },
      mutations: {
        retry: false,
      },
    },
  };
  return new QueryClient(config);
}

// -------------------------------------------------------------------------- //
// Singleton reference (client-side only)                                       //
// -------------------------------------------------------------------------- //

let _queryClientRef: QueryClient | null = null;

/** Register the QueryClient instance for imperative use outside React. */
export function setQueryClientRef(client: QueryClient): void {
  _queryClientRef = client;
}

/**
 * Get the QueryClient for imperative cache invalidation in services.
 * Returns null during SSR — always prefer useQueryClient() inside components.
 */
export function getQueryClient(): QueryClient | null {
  return _queryClientRef;
}

// -------------------------------------------------------------------------- //
// Provider                                                                      //
// -------------------------------------------------------------------------- //

/**
 * TanStack Query provider.
 * Creates a new QueryClient per session (not module-level singleton)
 * to prevent state sharing between SSR requests.
 *
 * Includes ReactQueryDevtools in development builds.
 */
export function QueryProvider({ children }: { children: ReactNode }) {
  const [queryClient] = useState(() => {
    const client = makeQueryClient();
    setQueryClientRef(client);
    return client;
  });

  return (
    <QueryClientProvider client={queryClient}>
      {children}
      {process.env.NODE_ENV === "development" && (
        <ReactQueryDevtools initialIsOpen={false} buttonPosition="bottom-left" />
      )}
    </QueryClientProvider>
  );
  }
