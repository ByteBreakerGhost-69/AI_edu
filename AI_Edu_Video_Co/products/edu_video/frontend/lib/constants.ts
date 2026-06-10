/**
 * constants.ts
 * Application-wide constants — routes, query keys, config values.
 * Never hardcode magic strings in components; import from here instead.
 */

// -------------------------------------------------------------------------- //
// App metadata                                                                  //
// -------------------------------------------------------------------------- //

/** Application display name. */
export const APP_NAME = "EduVideo";

/** Landing page tagline. */
export const APP_TAGLINE = "AI-powered educational videos for every curriculum";

/** Support contact email. */
export const SUPPORT_EMAIL = "support@eduvideo.ai";

/** Maximum image upload size: 10 MB. */
export const MAX_UPLOAD_SIZE_BYTES = 10 * 1024 * 1024;

/** Accepted image MIME types for project input. */
export const ACCEPTED_IMAGE_TYPES = [
  "image/jpeg",
  "image/png",
  "image/webp",
  "image/gif",
] as const;

/** Project status polling interval (ms). */
export const STATUS_POLL_INTERVAL_MS = 3_000;

/** Maximum polling duration before giving up (10 minutes). */
export const STATUS_POLL_MAX_DURATION_MS = 10 * 60 * 1_000;

/** Debounce delay for search inputs (ms). */
export const SEARCH_DEBOUNCE_MS = 350;

/** Default pagination page size. */
export const DEFAULT_PAGE_LIMIT = 20;

// -------------------------------------------------------------------------- //
// Route paths                                                                   //
// -------------------------------------------------------------------------- //

/**
 * All frontend route paths as a typed constant.
 * Use ROUTES.dashboard instead of "/dashboard" everywhere — catches typos
 * at compile time and makes route refactors a single change.
 *
 * Next.js App Router route groups:
 *   (landing)   → public marketing pages
 *   (auth)      → login, register, etc.
 *   (dashboard) → authenticated user pages
 *   (studio)    → video editor
 *   (admin)     → internal admin panel
 */
export const ROUTES = {
  // Public
  home:           "/",
  pricing:        "/#pricing",
  about:          "/about",

  // Auth
  login:          "/login",
  register:       "/register",
  forgotPassword: "/forgot-password",
  resetPassword:  "/reset-password",

  // Dashboard
  dashboard:  "/dashboard",
  projects:   "/projects",
  newProject: "/projects/new",

  // Billing
  billing:         "/billing",
  billingUpgrade:  "/billing/upgrade",
  billingInvoices: "/billing/invoices",
  usage:           "/usage",

  // Studio (dynamic segment — call as a function)
  studio:        (projectId: string) => `/studio/${projectId}`,
  studioLoading: (projectId: string) => `/studio/${projectId}/loading`,

  // Admin
  admin:             "/admin",
  adminReviewQueue:  "/admin/review-queue",
  adminUsers:        "/admin/users",
  adminAnalytics:    "/admin/analytics",
} as const;

/**
 * Routes that require a valid JWT (enforced by middleware/auth.ts).
 */
export const PROTECTED_ROUTES = [
  "/dashboard",
  "/projects",
  "/billing",
  "/usage",
  "/studio",
  "/admin",
] as const;

/**
 * Routes that require the "admin" role.
 */
export const ADMIN_ROUTES = [
  "/admin",
  "/admin/review-queue",
  "/admin/users",
  "/admin/analytics",
] as const;

// -------------------------------------------------------------------------- //
// TanStack Query keys                                                           //
// -------------------------------------------------------------------------- //

/**
 * Query key factories for TanStack Query cache management.
 *
 * Structure: [entity, ...discriminators]
 *
 * Usage:
 *   queryClient.invalidateQueries({ queryKey: QUERY_KEYS.projects.all() })
 *   queryClient.invalidateQueries({ queryKey: QUERY_KEYS.projects.detail(id) })
 *
 * Convention:
 *   .all()         → invalidates every query for this entity
 *   .list(params)  → paginated/filtered list
 *   .detail(id)    → single item
 *   .status(id)    → lightweight status-only query
 */
export const QUERY_KEYS = {
  auth: {
    me: ()           => ["auth", "me"] as const,
  },

  projects: {
    all:      ()           => ["projects"] as const,
    list:     (params?: Record<string, unknown>) =>
                             ["projects", "list", params] as const,
    detail:   (id: string) => ["projects", id] as const,
    status:   (id: string) => ["projects", id, "status"] as const,
    scenes:   (id: string) => ["projects", id, "scenes"] as const,
    render:   (id: string) => ["projects", id, "render"] as const,
    quality:  (id: string) => ["projects", id, "quality"] as const,
    delivery: (id: string) => ["projects", id, "delivery"] as const,
    subtitles:(id: string, format?: string) =>
                             ["projects", id, "subtitles", format] as const,
    feedback: (id: string) => ["projects", id, "feedback"] as const,
  },

  billing: {
    all:            ()            => ["billing"] as const,
    subscription:   ()            => ["billing", "subscription"] as const,
    quota:          ()            => ["billing", "quota"] as const,
    paymentMethods: ()            => ["billing", "payment-methods"] as const,
    invoices:       (page?: number) =>
                                    ["billing", "invoices", page] as const,
    invoice:        (id: string) => ["billing", "invoices", id] as const,
  },

  review: {
    all:    ()             => ["review"] as const,
    queue:  (params?: Record<string, unknown>) =>
                             ["review", "queue", params] as const,
    detail: (id: string)  => ["review", id] as const,
  },

  analytics: {
    all:      ()              => ["analytics"] as const,
    platform: ()              => ["analytics", "platform"] as const,
    project:  (id: string)   => ["analytics", "project", id] as const,
  },
} as const;

// -------------------------------------------------------------------------- //
// API / infrastructure config                                                   //
// -------------------------------------------------------------------------- //

/**
 * Backend REST API base URL.
 * Read from environment — never hardcode.
 */
export const API_BASE_URL =
  process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";

/**
 * WebSocket base URL.
 * Derived from API_BASE_URL by swapping http(s) → ws(s).
 */
export const WS_BASE_URL = API_BASE_URL.replace(/^http/, "ws");

/**
 * Stripe publishable (public) key — safe to expose in frontend.
 */
export const STRIPE_PUBLISHABLE_KEY =
  process.env.NEXT_PUBLIC_STRIPE_PUBLISHABLE_KEY ?? "";

/**
 * GCS public bucket URL for direct asset access.
 */
export const GCS_BASE_URL = `https://storage.googleapis.com/${
  process.env.NEXT_PUBLIC_GCS_BUCKET_NAME ?? "edu-video-assets"
}`;

// -------------------------------------------------------------------------- //
// UI constants                                                                  //
// -------------------------------------------------------------------------- //

/**
 * Tailwind CSS breakpoints (px) — mirrors tailwind.config.js.
 * Use for programmatic responsive logic in JavaScript.
 */
export const BREAKPOINTS = {
  sm:   640,
  md:   768,
  lg:  1024,
  xl:  1280,
  "2xl": 1536,
} as const;

/**
 * Z-index stacking levels for consistent layer ordering.
 */
export const Z_INDEX = {
  base:      0,
  dropdown: 10,
  sticky:   20,
  overlay:  30,
  modal:    40,
  toast:    50,
  tooltip:  60,
} as const;

/**
 * Animation duration presets (milliseconds).
 */
export const ANIMATION_DURATION = {
  fast:   150,
  normal: 250,
  slow:   400,
} as const;

/**
 * Toast notification auto-dismiss durations (milliseconds).
 */
export const TOAST_DURATION = {
  short:      2_000,
  normal:     4_000,
  long:       6_000,
  persistent: Infinity,
} as const;

// -------------------------------------------------------------------------- //
// Feature flags                                                                 //
// -------------------------------------------------------------------------- //

/**
 * Feature flags for gradual rollout.
 * Controlled via NEXT_PUBLIC_* environment variables.
 */
export const FEATURES = {
  /** HLS adaptive streaming — requires CDN + HLS manifest setup. */
  hlsStreaming:
    process.env.NEXT_PUBLIC_ENABLE_HLS === "true",

  /** In-video quiz overlay. */
  quizOverlay:
    process.env.NEXT_PUBLIC_ENABLE_QUIZ === "true",

  /** AI-powered search in projects list. */
  aiSearch:
    process.env.NEXT_PUBLIC_ENABLE_AI_SEARCH === "true",

  /** Admin analytics dashboard — on by default. */
  adminAnalytics: true,

  /** WebSocket real-time updates — off only if explicitly disabled. */
  websocket:
    process.env.NEXT_PUBLIC_ENABLE_WEBSOCKET !== "false",
} as const;

// -------------------------------------------------------------------------- //
// Tier limits (mirrors backend billing/tier_config.py)                         //
// -------------------------------------------------------------------------- //

/**
 * Client-side copy of tier limits.
 * Used for UI gatekeeping only — backend is the authoritative source.
 * Keep in sync with backend TIER_DEFINITIONS on any tier change.
 */
export const TIER_LIMITS = {
  free: {
    videosPerMonth:          3,
    maxScenesPerVideo:       4,
    maxVideoDurationSeconds: 180,
    storageRetentionDays:    7,
  },
  premium: {
    videosPerMonth:          50,
    maxScenesPerVideo:       8,
    maxVideoDurationSeconds: 600,
    storageRetentionDays:    365,
  },
} as const;

/** Monthly price for premium tier in USD. */
export const PREMIUM_PRICE_USD = 29;

/** Free trial period in days. */
export const TRIAL_DAYS = 7;
