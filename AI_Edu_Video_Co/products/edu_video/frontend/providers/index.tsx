"use client";

/**
 * providers/index.tsx
 * Root provider composition.
 * Import this in app/layout.tsx — it wraps all children with every provider.
 */

import React from "react";
import { QueryProvider } from "./query-provider";

type RootProvidersProps = {
  children: React.ReactNode;
};

/**
 * Root provider tree for the EduVideo app.
 * Add new providers here — they apply globally.
 *
 * Current providers (outer → inner):
 *   QueryProvider — TanStack Query with retry/stale config
 *
 * WebSocketProvider is NOT here — it's scoped to the (studio) layout
 * and needs a projectId prop.
 *
 * @example
 *   // app/layout.tsx
 *   export default function RootLayout({ children }) {
 *     return (
 *       <html lang="en">
 *         <body>
 *           <RootProviders>{children}</RootProviders>
 *         </body>
 *       </html>
 *     );
 *   }
 */
export function RootProviders({ children }: RootProvidersProps): React.ReactElement {
  return (
    <QueryProvider>
      {children}
    </QueryProvider>
  );
}

export { QueryProvider } from "./query-provider";
export { WebSocketProvider, useWebSocketContext } from "./websocket-provider";
