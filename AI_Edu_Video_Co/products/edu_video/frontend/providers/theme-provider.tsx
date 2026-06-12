"use client";

/**
 * theme-provider.tsx
 * Dark/light/system theme management.
 * Wraps next-themes ThemeProvider with typed helpers and a custom hook.
 */

import { type ReactNode } from "react";
import { ThemeProvider as NextThemesProvider, useTheme as useNextTheme } from "next-themes";

// -------------------------------------------------------------------------- //
// Types                                                                         //
// -------------------------------------------------------------------------- //

export type Theme = "light" | "dark" | "system";

export type ThemeContextValue = {
  /** Active resolved theme: "light" or "dark" (never "system"). */
  resolvedTheme: "light" | "dark" | undefined;
  /** User's chosen theme preference (may be "system"). */
  theme:         Theme | undefined;
  /** Set the theme. */
  setTheme:      (theme: Theme) => void;
  /** True if the resolved theme is dark. */
  isDark:        boolean;
  /** True if the resolved theme is light. */
  isLight:       boolean;
  /** True while theme is initialising (avoids hydration flash). */
  isLoading:     boolean;
};

// -------------------------------------------------------------------------- //
// Provider                                                                      //
// -------------------------------------------------------------------------- //

/**
 * Theme provider with dark/light/system support.
 * Persists user choice to localStorage via next-themes.
 * Respects OS system preference when theme = "system".
 *
 * Place at the top of the provider stack — wraps all other providers.
 */
export function ThemeProvider({ children }: { children: ReactNode }) {
  return (
    <NextThemesProvider
      attribute="class"
      defaultTheme="system"
      enableSystem
      disableTransitionOnChange
      storageKey="eduvideo-theme"
    >
      {children}
    </NextThemesProvider>
  );
}

// -------------------------------------------------------------------------- //
// Hook                                                                          //
// -------------------------------------------------------------------------- //

/**
 * Access the current theme and setter.
 * Must be used inside ThemeProvider.
 *
 * @example
 *   const { isDark, setTheme } = useTheme();
 */
export function useTheme(): ThemeContextValue {
  const { resolvedTheme, theme, setTheme } = useNextTheme();

  const resolved = resolvedTheme as "light" | "dark" | undefined;

  return {
    resolvedTheme: resolved,
    theme:         theme as Theme | undefined,
    setTheme:      (t: Theme) => setTheme(t),
    isDark:        resolved === "dark",
    isLight:       resolved === "light",
    isLoading:     resolved === undefined,
  };
}
