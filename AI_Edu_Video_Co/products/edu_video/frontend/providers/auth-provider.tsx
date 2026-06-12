"use client";

/**
 * auth-provider.tsx
 * Single source of truth for authentication state across the app.
 * Parses user identity from JWT token; manages login/logout/register.
 */

import {
  createContext,
  useContext,
  useEffect,
  useState,
  useCallback,
  useRef,
  type ReactNode,
} from "react";
import { useRouter, usePathname } from "next/navigation";
import { login as apiLogin, logout as apiLogout, register as apiRegister, tokenManager } from "@/lib/api/client";
import { ROUTES, PROTECTED_ROUTES } from "@/lib/constants";
import type { ApiError } from "@/lib/api/client";

// -------------------------------------------------------------------------- //
// Types                                                                         //
// -------------------------------------------------------------------------- //

/**
 * Authenticated user identity parsed from JWT claims.
 * Does NOT contain subscription/quota data — use useSubscriptionStore for that.
 */
export type AuthUser = {
  readonly id:         string;
  readonly email:      string;
  readonly fullName:   string | null;
  readonly role:       "free" | "premium" | "admin";
  readonly isVerified: boolean;
};

type LoginResult =
  | { success: true }
  | { success: false; error: string };

type RegisterResult =
  | { success: true }
  | { success: false; error: string; fieldErrors?: Record<string, string> };

type AuthContextValue = {
  /** Authenticated user, or null if logged out. */
  user:            AuthUser | null;
  /** True while the initial token check is running. */
  isLoading:       boolean;
  /** True if user is authenticated. */
  isAuthenticated: boolean;
  /** True if user has the admin role. */
  isAdmin:         boolean;
  /** True if user has premium or admin role (coarse check — use subscription store for features). */
  isPremiumUser:   boolean;
  /** Login with email + password. */
  login:           (email: string, password: string) => Promise<LoginResult>;
  /** Register a new account. */
  register:        (email: string, password: string, fullName?: string) => Promise<RegisterResult>;
  /** Logout — clears token, resets stores, redirects to login. */
  logout:          () => void;
  /** Re-parse the user from the current token (call after token refresh). */
  refreshUser:     () => void;
};

// -------------------------------------------------------------------------- //
// Context                                                                       //
// -------------------------------------------------------------------------- //

const AuthContext = createContext<AuthContextValue | null>(null);

// -------------------------------------------------------------------------- //
// Token parsing                                                                 //
// -------------------------------------------------------------------------- //

/**
 * Decode JWT payload and extract AuthUser claims.
 * Does NOT verify signature — backend verifies on every API request.
 *
 * @param token - JWT access token string
 * @returns AuthUser or null if token is malformed
 */
function parseUserFromToken(token: string): AuthUser | null {
  try {
    const parts = token.split(".");
    if (parts.length !== 3) return null;

    const padded  = parts[1]!.replace(/-/g, "+").replace(/_/g, "/");
    const payload = JSON.parse(atob(padded)) as Record<string, unknown>;

    const userId = payload["user_id"] as string | undefined;
    const email  = payload["sub"]     as string | undefined;
    if (!userId || !email) return null;

    const role = (payload["role"] as string | undefined) ?? "free";
    const validRole = ["free", "premium", "admin"].includes(role) ? role : "free";

    return {
      id:         userId,
      email,
      fullName:   (payload["full_name"]  as string | undefined) ?? null,
      role:       validRole as AuthUser["role"],
      isVerified: Boolean(payload["is_verified"]),
    };
  } catch {
    return null;
  }
}

// -------------------------------------------------------------------------- //
// Provider                                                                      //
// -------------------------------------------------------------------------- //

/**
 * Authentication context provider.
 * Place inside QueryProvider but outside components that need auth context.
 *
 * On mount: checks for existing JWT cookie, parses user, redirects if needed.
 * On login: stores token, parses user, loads subscription in background.
 * On logout: clears token, resets all stores, redirects to /login.
 */
export function AuthProvider({ children }: { children: ReactNode }) {
  const router         = useRouter();
  const pathname       = usePathname();
  const [user, setUser]         = useState<AuthUser | null>(null);
  const [isLoading, setLoading] = useState(true);
  const initialized = useRef(false);

  // ---------------------------------------------------------------- //
  // Initial auth check                                                //
  // ---------------------------------------------------------------- //

  useEffect(() => {
    if (initialized.current) return;
    initialized.current = true;

    const token = tokenManager.getToken();
    if (token) {
      const parsed = parseUserFromToken(token);
      if (parsed) {
        setUser(parsed);
      } else {
        tokenManager.clearTokens();
      }
    }
    setLoading(false);
  }, []);

  // ---------------------------------------------------------------- //
  // Route protection                                                   //
  // ---------------------------------------------------------------- //

  useEffect(() => {
    if (isLoading) return;
    const isProtected = PROTECTED_ROUTES.some((r) => pathname.startsWith(r));
    if (isProtected && !user) {
      router.replace(`${ROUTES.login}?redirect=${encodeURIComponent(pathname)}`);
    }
  }, [isLoading, user, pathname, router]);

  // ---------------------------------------------------------------- //
  // Actions                                                            //
  // ---------------------------------------------------------------- //

  const handleLogin = useCallback(
    async (email: string, password: string): Promise<LoginResult> => {
      try {
        await apiLogin(email, password);

        const token  = tokenManager.getToken();
        if (!token) return { success: false, error: "Authentication failed. Please try again." };

        const parsed = parseUserFromToken(token);
        if (!parsed) {
          tokenManager.clearTokens();
          return { success: false, error: "Invalid session. Please try again." };
        }

        setUser(parsed);

        // Load subscription data in the background — non-blocking
        import("@/services/billing-service")
          .then(({ loadSubscriptionData }) => loadSubscriptionData())
          .catch(console.error);

        return { success: true };
      } catch (error) {
        const err = error as ApiError;
        if (err.statusCode === 401) {
          return { success: false, error: "Invalid email or password. Please try again." };
        }
        return { success: false, error: err.detail ?? "Login failed. Please try again." };
      }
    },
    []
  );

  const handleRegister = useCallback(
    async (email: string, password: string, fullName?: string): Promise<RegisterResult> => {
      try {
        await apiRegister({ email, password, fullName });
        return { success: true };
      } catch (error) {
        const err = error as ApiError;
        if (err.statusCode === 409) {
          return {
            success:     false,
            error:       "An account with this email already exists.",
            fieldErrors: { email: "Email already in use" },
          };
        }
        if (err.isValidationError) {
          return {
            success:     false,
            error:       "Please check your details and try again.",
            fieldErrors: err.response as Record<string, string> | undefined,
          };
        }
        return { success: false, error: err.detail ?? "Registration failed. Please try again." };
      }
    },
    []
  );

  const handleLogout = useCallback(() => {
    apiLogout();
    setUser(null);

    // Reset all stores asynchronously
    import("@/store").then(
      ({ useProjectStore, useRenderStore, useStudioStore, useSubscriptionStore }) => {
        useProjectStore.getState().reset();
        useRenderStore.getState().reset();
        useStudioStore.getState().reset();
        useSubscriptionStore.getState().reset();
      }
    ).catch(console.error);

    router.replace(ROUTES.login);
  }, [router]);

  const refreshUser = useCallback(() => {
    const token = tokenManager.getToken();
    if (token) {
      setUser(parseUserFromToken(token));
    } else {
      setUser(null);
    }
  }, []);

  // ---------------------------------------------------------------- //
  // Context value                                                      //
  // ---------------------------------------------------------------- //

  const value: AuthContextValue = {
    user,
    isLoading,
    isAuthenticated: user !== null,
    isAdmin:         user?.role === "admin",
    isPremiumUser:   user?.role === "premium" || user?.role === "admin",
    login:           handleLogin,
    register:        handleRegister,
    logout:          handleLogout,
    refreshUser,
  };

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
}

// -------------------------------------------------------------------------- //
// Hooks                                                                         //
// -------------------------------------------------------------------------- //

/**
 * Access authentication context.
 * @throws Error if used outside AuthProvider.
 */
export function useAuth(): AuthContextValue {
  const ctx = useContext(AuthContext);
  if (!ctx) throw new Error("useAuth must be used within AuthProvider");
  return ctx;
}

/**
 * Access the current user without throwing if outside provider.
 * Returns null when unauthenticated or outside provider.
 */
export function useAuthUser(): AuthUser | null {
  return useContext(AuthContext)?.user ?? null;
}
