/**
 * utils.ts
 * Application-wide utility functions — pure, no side effects, no React.
 * Import from "@/lib/utils" throughout the codebase.
 */

import { type ClassValue, clsx } from "clsx";
import { twMerge } from "tailwind-merge";
import type {
  Project,
  ProjectStatus,
  Scene,
  Tier,
  QualityIssueSeverity,
} from "@/types";

// -------------------------------------------------------------------------- //
// className utilities                                                           //
// -------------------------------------------------------------------------- //

/**
 * Merge Tailwind CSS classes with full conflict resolution.
 * Combines clsx (conditional/array syntax) with tailwind-merge (deduplication).
 *
 * This is the ONLY way to build className strings in this project.
 * Never use string concatenation or template literals for Tailwind classes.
 *
 * @param inputs - Class values: strings, objects, arrays, conditionals
 * @returns Merged class string with conflicts resolved
 *
 * @example
 *   cn("px-4 py-2", "px-6")                    // "py-2 px-6"
 *   cn("text-red-500", isError && "text-red-700") // conditional
 *   cn({ "opacity-50": isDisabled })             // object syntax
 */
export function cn(...inputs: ClassValue[]): string {
  return twMerge(clsx(inputs));
}

// -------------------------------------------------------------------------- //
// String formatting                                                             //
// -------------------------------------------------------------------------- //

/**
 * Truncate a string to a maximum length with ellipsis.
 * Respects word boundaries — never cuts mid-word if a good break point exists.
 *
 * @param text - String to truncate
 * @param maxLength - Maximum character count (default: 100)
 * @param suffix - Appended when truncated (default: "…")
 * @returns Truncated string, or original if within limit
 *
 * @example
 *   truncate("Hello World", 8) // "Hello…"
 *   truncate("Hi", 10)         // "Hi"
 *   truncate("", 10)           // ""
 */
export function truncate(
  text: string,
  maxLength = 100,
  suffix = "…"
): string {
  if (!text || text.length <= maxLength) return text ?? "";
  const truncated = text.slice(0, maxLength - suffix.length);
  const lastSpace = truncated.lastIndexOf(" ");
  const cut = lastSpace > maxLength * 0.7 ? lastSpace : truncated.length;
  return truncated.slice(0, cut) + suffix;
}

/**
 * Capitalize the first letter of a string.
 *
 * @param str - Input string
 * @returns String with first character uppercased
 *
 * @example
 *   capitalize("hello world") // "Hello world"
 *   capitalize("")            // ""
 */
export function capitalize(str: string): string {
  if (!str) return str ?? "";
  return str.charAt(0).toUpperCase() + str.slice(1);
}

/**
 * Convert snake_case or kebab-case to Title Case.
 * Used for displaying enum values in UI labels.
 *
 * @param str - snake_case or kebab-case string
 * @returns Title Case string
 *
 * @example
 *   toTitleCase("computer_science") // "Computer Science"
 *   toTitleCase("my-subject-area")  // "My Subject Area"
 *   toTitleCase("mathematics")      // "Mathematics"
 */
export function toTitleCase(str: string): string {
  if (!str) return str ?? "";
  return str
    .replace(/[-_]/g, " ")
    .replace(/\w\S*/g, (word) => capitalize(word));
}

/**
 * Convert a string to a URL-safe slug.
 * Lowercase, strips special characters, replaces spaces with hyphens.
 *
 * @param str - Input string
 * @returns URL-safe slug
 *
 * @example
 *   slugify("Introduction to Calculus!") // "introduction-to-calculus"
 *   slugify("Newton's Laws (Part 2)")    // "newtons-laws-part-2"
 */
export function slugify(str: string): string {
  return str
    .toLowerCase()
    .normalize("NFD")
    .replace(/[\u0300-\u036f]/g, "")
    .replace(/[^a-z0-9\s-]/g, "")
    .replace(/\s+/g, "-")
    .replace(/-+/g, "-")
    .replace(/^-|-$/g, "");
}

/**
 * Pluralize a word based on count.
 *
 * @param count - Item count
 * @param singular - Singular form
 * @param plural - Plural form (default: singular + "s")
 * @returns Correctly pluralized string with count
 *
 * @example
 *   pluralize(1, "video")          // "1 video"
 *   pluralize(3, "video")          // "3 videos"
 *   pluralize(1, "quiz", "quizzes") // "1 quiz"
 */
export function pluralize(
  count: number,
  singular: string,
  plural?: string
): string {
  return `${count} ${count === 1 ? singular : (plural ?? `${singular}s`)}`;
}

/**
 * Format a number as a USD currency string.
 *
 * @param amount - Amount in USD (float)
 * @param decimals - Decimal places (default: 2; use 4 for micro-costs)
 * @returns Formatted currency string
 *
 * @example
 *   formatCurrency(29)        // "$29.00"
 *   formatCurrency(0.0024, 4) // "$0.0024"
 */
export function formatCurrency(amount: number, decimals = 2): string {
  if (isNaN(amount)) return "$0.00";
  return new Intl.NumberFormat("en-US", {
    style:                 "currency",
    currency:              "USD",
    minimumFractionDigits: decimals,
    maximumFractionDigits: decimals,
  }).format(amount);
}

/**
 * Format a large number with K/M abbreviations.
 * Used for analytics display.
 *
 * @param num - Number to format
 * @returns Abbreviated string
 *
 * @example
 *   formatNumber(1234)    // "1,234"
 *   formatNumber(12345)   // "12.3K"
 *   formatNumber(1234567) // "1.2M"
 */
export function formatNumber(num: number): string {
  if (isNaN(num)) return "0";
  if (num >= 1_000_000) return `${(num / 1_000_000).toFixed(1)}M`;
  if (num >= 10_000) return `${(num / 1_000).toFixed(1)}K`;
  return new Intl.NumberFormat("en-US").format(Math.round(num));
}

/**
 * Format a percentage for display.
 *
 * @param value - 0–100 or 0.0–1.0 if isDecimal=true
 * @param isDecimal - Whether value is a decimal fraction (default: false)
 * @returns Formatted percentage string
 *
 * @example
 *   formatPercent(75.5)       // "75.5%"
 *   formatPercent(0.755, true) // "75.5%"
 */
export function formatPercent(value: number, isDecimal = false): string {
  if (isNaN(value)) return "0%";
  const pct = isDecimal ? value * 100 : value;
  return `${Math.round(pct * 10) / 10}%`;
}

/**
 * Clamp a number to [min, max].
 *
 * @param value - Value to clamp
 * @param min - Minimum (inclusive)
 * @param max - Maximum (inclusive)
 * @returns Clamped value
 */
export function clamp(value: number, min: number, max: number): number {
  return Math.min(Math.max(value, min), max);
}

// -------------------------------------------------------------------------- //
// Date/time formatting                                                          //
// -------------------------------------------------------------------------- //

/**
 * Format an ISO 8601 string as relative human-readable time.
 *
 * @param isoString - ISO 8601 datetime string from API
 * @returns Relative time string e.g. "5 minutes ago", "2 days ago"
 *
 * @example
 *   formatRelativeTime("2024-01-15T10:25:00Z") // "5 minutes ago"
 */
export function formatRelativeTime(
  isoString: string | null | undefined
): string {
  if (!isoString) return "Unknown";
  const date = new Date(isoString);
  if (isNaN(date.getTime())) return "Unknown";

  const diffMs      = Date.now() - date.getTime();
  const diffSeconds = Math.floor(diffMs / 1_000);
  const diffMinutes = Math.floor(diffSeconds / 60);
  const diffHours   = Math.floor(diffMinutes / 60);
  const diffDays    = Math.floor(diffHours / 24);

  if (diffSeconds < 10) return "just now";
  if (diffSeconds < 60) return `${diffSeconds}s ago`;
  if (diffMinutes < 60) return `${diffMinutes}m ago`;
  if (diffHours < 24)   return `${diffHours}h ago`;
  if (diffDays < 7)     return `${diffDays}d ago`;
  return formatDate(isoString);
}

/**
 * Format an ISO 8601 string to a readable date.
 *
 * @param isoString - ISO 8601 datetime string
 * @param options - Intl.DateTimeFormatOptions override
 * @returns Formatted date string e.g. "Jan 15, 2024"
 */
export function formatDate(
  isoString: string | null | undefined,
  options: Intl.DateTimeFormatOptions = {
    month: "short",
    day:   "numeric",
    year:  "numeric",
  }
): string {
  if (!isoString) return "—";
  const date = new Date(isoString);
  if (isNaN(date.getTime())) return "—";
  return new Intl.DateTimeFormat("en-US", options).format(date);
}

/**
 * Format an ISO 8601 string to date + time.
 *
 * @param isoString - ISO 8601 datetime string
 * @returns "Jan 15, 2024 at 10:30 AM"
 */
export function formatDateTime(
  isoString: string | null | undefined
): string {
  if (!isoString) return "—";
  const date = new Date(isoString);
  if (isNaN(date.getTime())) return "—";
  return new Intl.DateTimeFormat("en-US", {
    month:   "short",
    day:     "numeric",
    year:    "numeric",
    hour:    "numeric",
    minute:  "2-digit",
    hour12:  true,
  }).format(date);
}

/**
 * Check if an ISO date string represents a date in the past.
 *
 * @param isoString - ISO 8601 datetime string
 * @returns true if the date is in the past
 */
export function isPast(isoString: string | null | undefined): boolean {
  if (!isoString) return false;
  const date = new Date(isoString);
  return !isNaN(date.getTime()) && date.getTime() < Date.now();
}

/**
 * Get remaining time until a future date as a human-readable string.
 *
 * @param isoString - ISO 8601 datetime string (should be in future)
 * @returns Human-readable remaining time, or "Expired" if past
 *
 * @example
 *   getDaysUntil("2024-02-15T00:00:00Z") // "31 days"
 *   getDaysUntil("2024-01-15T12:00:00Z") // "12 hours"
 */
export function getDaysUntil(isoString: string | null | undefined): string {
  if (!isoString) return "—";
  const date = new Date(isoString);
  if (isNaN(date.getTime())) return "—";

  const diffMs      = date.getTime() - Date.now();
  if (diffMs < 0) return "Expired";

  const diffDays    = Math.floor(diffMs / (1_000 * 60 * 60 * 24));
  const diffHours   = Math.floor(diffMs / (1_000 * 60 * 60));
  const diffMinutes = Math.floor(diffMs / (1_000 * 60));

  if (diffDays > 1)    return `${diffDays} days`;
  if (diffDays === 1)  return "1 day";
  if (diffHours > 1)   return `${diffHours} hours`;
  if (diffHours === 1) return "1 hour";
  return `${diffMinutes} minutes`;
}

// -------------------------------------------------------------------------- //
// Project-specific utilities                                                    //
// -------------------------------------------------------------------------- //

/**
 * Get a human-readable progress description for a project status.
 *
 * @param status - Current project status
 * @returns Progress description string
 *
 * @example
 *   getProgressDescription("orchestrating") // "Generating your script and visuals…"
 *   getProgressDescription("done")          // "Your video is ready!"
 */
export function getProgressDescription(status: ProjectStatus): string {
  const map: Record<ProjectStatus, string> = {
    pending:       "Preparing your project…",
    queued:        "Waiting in queue…",
    orchestrating: "Generating your script and visuals…",
    rendering:     "Rendering your video…",
    review:        "Under expert review…",
    done:          "Your video is ready!",
    failed:        "Something went wrong",
    cancelled:     "Project cancelled",
  };
  return map[status] ?? "Processing…";
}

/**
 * Get estimated pipeline progress percentage for a status.
 * Provides smooth UI indication before exact % arrives via WebSocket.
 *
 * @param status - Current project status
 * @returns Progress 0–100, or null for terminal states
 */
export function getEstimatedProgress(status: ProjectStatus): number | null {
  const map: Partial<Record<ProjectStatus, number>> = {
    pending:       5,
    queued:        10,
    orchestrating: 35,
    rendering:     70,
    review:        90,
  };
  return map[status] ?? null;
}

/**
 * Get Tailwind CSS color classes for a project status badge.
 *
 * @param status - Project status
 * @returns Tailwind bg + text color classes
 */
export function getStatusColor(status: ProjectStatus): string {
  const map: Record<ProjectStatus, string> = {
    pending:       "bg-gray-100 text-gray-700",
    queued:        "bg-blue-100 text-blue-700",
    orchestrating: "bg-indigo-100 text-indigo-700",
    rendering:     "bg-purple-100 text-purple-700",
    review:        "bg-amber-100 text-amber-700",
    done:          "bg-green-100 text-green-700",
    failed:        "bg-red-100 text-red-700",
    cancelled:     "bg-gray-100 text-gray-500",
  };
  return map[status] ?? "bg-gray-100 text-gray-700";
}

/**
 * Get Tailwind CSS color classes for a quality issue severity badge.
 *
 * @param severity - Issue severity level
 * @returns Tailwind classes
 */
export function getSeverityColor(severity: QualityIssueSeverity): string {
  const map: Record<QualityIssueSeverity, string> = {
    critical: "bg-red-100 text-red-700 border-red-200",
    warning:  "bg-amber-100 text-amber-700 border-amber-200",
    info:     "bg-blue-100 text-blue-700 border-blue-200",
  };
  return map[severity] ?? "bg-gray-100 text-gray-700";
}

/**
 * Format the total cost of a project for display.
 * Shows "< $0.01" for sub-cent costs.
 *
 * @param project - Project record with totalCostUsd
 * @returns Formatted cost string
 */
export function formatProjectCost(project: Project): string {
  const cost = project.totalCostUsd;
  if (cost < 0.01) return "< $0.01";
  return formatCurrency(cost, 2);
}

/**
 * Calculate the percentage of scenes with status "done".
 *
 * @param scenes - Array of scene records
 * @returns 0–100
 */
export function getScenesCompletionPercent(scenes: Scene[]): number {
  if (scenes.length === 0) return 0;
  const done = scenes.filter((s) => s.status === "done").length;
  return Math.round((done / scenes.length) * 100);
}

// -------------------------------------------------------------------------- //
// Subscription / quota utilities                                               //
// -------------------------------------------------------------------------- //

/**
 * Get display name for a subscription tier.
 *
 * @param tier - Subscription tier
 * @returns Display name string
 */
export function getTierDisplayName(tier: Tier): string {
  return tier === "premium" ? "Premium" : "Free";
}

/**
 * Get Tailwind badge classes for a subscription tier.
 *
 * @param tier - Subscription tier
 * @returns Tailwind class string
 */
export function getTierBadgeClass(tier: Tier): string {
  return tier === "premium"
    ? "bg-gradient-to-r from-purple-500 to-indigo-500 text-white"
    : "bg-gray-100 text-gray-600";
}

/**
 * Calculate quota usage as a percentage, capped at 100.
 *
 * @param used - Videos used this billing period
 * @param limit - Monthly video limit
 * @returns Percentage 0–100
 */
export function getQuotaPercent(used: number, limit: number): number {
  if (limit <= 0) return 100;
  return Math.min(100, Math.round((used / limit) * 100));
}

/**
 * Get Tailwind text color for a quota usage percentage.
 * Green → yellow → amber → red as usage climbs.
 *
 * @param percent - Usage percentage 0–100
 * @returns Tailwind text color class
 */
export function getQuotaColor(percent: number): string {
  if (percent >= 100) return "text-red-600";
  if (percent >= 80)  return "text-amber-600";
  if (percent >= 60)  return "text-yellow-600";
  return "text-green-600";
}

/**
 * Get Tailwind background color for a quota progress bar.
 *
 * @param percent - Usage percentage 0–100
 * @returns Tailwind bg color class
 */
export function getQuotaBarColor(percent: number): string {
  if (percent >= 100) return "bg-red-500";
  if (percent >= 80)  return "bg-amber-500";
  if (percent >= 60)  return "bg-yellow-500";
  return "bg-green-500";
}

// -------------------------------------------------------------------------- //
// Array & object utilities                                                      //
// -------------------------------------------------------------------------- //

/**
 * Group an array of objects by a derived key.
 *
 * @param items - Array to group
 * @param keyFn - Function that returns the grouping key
 * @returns Record mapping each key to an array of items
 *
 * @example
 *   groupBy(scenes, s => s.status)
 *   // { pending: [...], done: [...] }
 */
export function groupBy<T, K extends string>(
  items: T[],
  keyFn: (item: T) => K
): Partial<Record<K, T[]>> {
  return items.reduce<Partial<Record<K, T[]>>>((acc, item) => {
    const key = keyFn(item);
    return { ...acc, [key]: [...(acc[key] ?? []), item] };
  }, {});
}

/**
 * Sort an array by a derived key. Returns a new array.
 *
 * @param items - Array to sort
 * @param keyFn - Returns the sort key
 * @param direction - "asc" (default) or "desc"
 * @returns New sorted array
 */
export function sortBy<T>(
  items: T[],
  keyFn: (item: T) => string | number,
  direction: "asc" | "desc" = "asc"
): T[] {
  return [...items].sort((a, b) => {
    const ka = keyFn(a);
    const kb = keyFn(b);
    const cmp = ka < kb ? -1 : ka > kb ? 1 : 0;
    return direction === "asc" ? cmp : -cmp;
  });
}

/**
 * Remove duplicates from an array by a key function.
 * Keeps the first occurrence of each key.
 *
 * @param items - Array with potential duplicates
 * @param keyFn - Returns the uniqueness key
 * @returns Deduplicated array
 */
export function uniqueBy<T>(
  items: T[],
  keyFn: (item: T) => string | number
): T[] {
  const seen = new Set<string | number>();
  return items.filter((item) => {
    const key = keyFn(item);
    if (seen.has(key)) return false;
    seen.add(key);
    return true;
  });
}

/**
 * Split an array into sub-arrays of a fixed size.
 *
 * @param items - Array to chunk
 * @param size - Maximum chunk size
 * @returns Array of chunks
 *
 * @example
 *   chunk([1,2,3,4,5], 2) // [[1,2],[3,4],[5]]
 */
export function chunk<T>(items: T[], size: number): T[][] {
  if (size <= 0) return [items];
  const out: T[][] = [];
  for (let i = 0; i < items.length; i += size) {
    out.push(items.slice(i, i + size));
  }
  return out;
}

/**
 * Pick specific keys from an object. Typed version of lodash pick.
 *
 * @param obj - Source object
 * @param keys - Keys to include
 * @returns New object with only the specified keys
 */
export function pick<T extends object, K extends keyof T>(
  obj: T,
  keys: K[]
): Pick<T, K> {
  return keys.reduce<Pick<T, K>>((acc, key) => {
    if (key in obj) acc[key] = obj[key];
    return acc;
  }, {} as Pick<T, K>);
}

/**
 * Omit specific keys from an object.
 *
 * @param obj - Source object
 * @param keys - Keys to exclude
 * @returns New object without the specified keys
 */
export function omit<T extends object, K extends keyof T>(
  obj: T,
  keys: K[]
): Omit<T, K> {
  const result = { ...obj };
  for (const key of keys) delete result[key];
  return result as Omit<T, K>;
}

// -------------------------------------------------------------------------- //
// Type guards and narrowing                                                     //
// -------------------------------------------------------------------------- //

/**
 * Check if a value is a non-null plain object.
 */
export function isObject(
  value: unknown
): value is Record<string, unknown> {
  return (
    typeof value === "object" &&
    value !== null &&
    !Array.isArray(value) &&
    !(value instanceof Date)
  );
}

/**
 * Check if a value is a non-empty string (after trimming).
 */
export function isNonEmptyString(value: unknown): value is string {
  return typeof value === "string" && value.trim().length > 0;
}

/**
 * Check if a value is a finite number (not NaN or ±Infinity).
 */
export function isFiniteNumber(value: unknown): value is number {
  return typeof value === "number" && Number.isFinite(value);
}

/**
 * Check if a caught error has a specific API error code.
 *
 * @param error - Caught error (unknown)
 * @param code - Error code to match e.g. "quota_exceeded"
 */
export function isApiErrorCode(error: unknown, code: string): boolean {
  return isObject(error) && "code" in error && error["code"] === code;
}

/**
 * Check if a caught error is an HTTP 402 (quota exceeded / payment required).
 */
export function isQuotaExceededError(error: unknown): boolean {
  return isObject(error) && "statusCode" in error && error["statusCode"] === 402;
}

/**
 * Check if a caught error is a network error (no HTTP response received).
 */
export function isNetworkError(error: unknown): boolean {
  return isObject(error) && "statusCode" in error && error["statusCode"] === 0;
}

// -------------------------------------------------------------------------- //
// Browser utilities                                                             //
// -------------------------------------------------------------------------- //

/**
 * Copy text to the system clipboard.
 * Falls back to execCommand for older browsers.
 *
 * @param text - Text to copy
 * @returns Promise resolving to true on success, false on failure
 */
export async function copyToClipboard(text: string): Promise<boolean> {
  try {
    if (navigator?.clipboard?.writeText) {
      await navigator.clipboard.writeText(text);
      return true;
    }
    // Legacy fallback
    const el = document.createElement("textarea");
    el.value = text;
    el.style.cssText = "position:fixed;opacity:0;pointer-events:none";
    document.body.appendChild(el);
    el.select();
    const ok = document.execCommand("copy");
    document.body.removeChild(el);
    return ok;
  } catch {
    return false;
  }
}

/**
 * Generate a stable non-negative integer hash from a string.
 * Used for deterministic colour/avatar assignment.
 *
 * @param str - Input string
 * @returns Non-negative integer hash
 */
export function hashString(str: string): number {
  let hash = 0;
  for (let i = 0; i < str.length; i++) {
    hash = ((hash << 5) - hash + str.charCodeAt(i)) | 0;
  }
  return Math.abs(hash);
}

/**
 * Get a consistent Tailwind avatar background color for a seed string.
 *
 * @param seed - String to derive color from (e.g. userId)
 * @returns Tailwind bg color class
 */
export function getAvatarColor(seed: string): string {
  const colors = [
    "bg-blue-500", "bg-indigo-500", "bg-purple-500", "bg-pink-500",
    "bg-green-500", "bg-teal-500",  "bg-cyan-500",   "bg-amber-500",
  ];
  return colors[hashString(seed) % colors.length]!;
}

/**
 * Derive 1–2 character initials from a full name or email.
 *
 * @param name - Full name or email address
 * @returns Uppercase initials
 *
 * @example
 *   getInitials("John Doe")           // "JD"
 *   getInitials("john.doe@email.com") // "JD"
 *   getInitials("John")               // "JO"
 */
export function getInitials(name: string | null | undefined): string {
  if (!name) return "?";
  const base    = name.includes("@") ? name.split("@")[0]! : name;
  const parts   = base.trim().replace(/[._-]/g, " ").split(/\s+/).filter(Boolean);
  if (parts.length === 0) return "?";
  if (parts.length === 1) return parts[0]!.slice(0, 2).toUpperCase();
  return (parts[0]![0]! + parts[parts.length - 1]![0]!).toUpperCase();
}

/**
 * Sleep for a given number of milliseconds.
 *
 * @param ms - Milliseconds to wait
 */
export function sleep(ms: number): Promise<void> {
  return new Promise((resolve) => setTimeout(resolve, ms));
}

/**
 * Debounce a function — delays execution until after wait ms since last call.
 *
 * @param fn - Function to debounce
 * @param wait - Debounce delay in milliseconds
 * @returns Debounced function with a cancel() method
 */
export function debounce<T extends (...args: Parameters<T>) => ReturnType<T>>(
  fn: T,
  wait: number
): T & { cancel: () => void } {
  let timer: ReturnType<typeof setTimeout> | null = null;

  const debounced = (...args: Parameters<T>): void => {
    if (timer) clearTimeout(timer);
    timer = setTimeout(() => {
      timer = null;
      fn(...args);
    }, wait);
  };

  debounced.cancel = () => {
    if (timer) { clearTimeout(timer); timer = null; }
  };

  return debounced as unknown as T & { cancel: () => void };
}

/**
 * Throttle a function — executes at most once per `limit` ms.
 *
 * @param fn - Function to throttle
 * @param limit - Minimum interval between invocations in ms
 * @returns Throttled function
 */
export function throttle<T extends (...args: Parameters<T>) => ReturnType<T>>(
  fn: T,
  limit: number
): T {
  let lastRun = 0;

  return ((...args: Parameters<T>) => {
    const now = Date.now();
    if (now - lastRun >= limit) {
      lastRun = now;
      return fn(...args);
    }
  }) as T;
}
