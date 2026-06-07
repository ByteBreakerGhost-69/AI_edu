/**
 * client.ts
 * Axios instance, interceptors, transformation utilities, error types,
 * and auth API. The single source of all HTTP communication.
 *
 * All other API modules import from this file — never create a second
 * Axios instance elsewhere in the codebase.
 */

import axios from "axios";
import type {
  AxiosInstance,
  AxiosRequestConfig,
  AxiosResponse,
  AxiosError,
  InternalAxiosRequestConfig,
} from "axios";
import Cookies from "js-cookie";

// -------------------------------------------------------------------------- //
// Environment configuration                                                    //
// -------------------------------------------------------------------------- //

export const API_BASE_URL =
  process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";

export const TOKEN_COOKIE_KEY    = "edu_video_token";
export const REFRESH_COOKIE_KEY  = "edu_video_refresh";
export const DEFAULT_TIMEOUT_MS  = 30_000;
export const UPLOAD_TIMEOUT_MS   = 120_000;

// -------------------------------------------------------------------------- //
// ApiError                                                                     //
// -------------------------------------------------------------------------- //

/**
 * Typed API error thrown by every function in this layer.
 * Never let raw AxiosError escape — always wrap in ApiError.
 */
export class ApiError extends Error {
  /** HTTP status code. 0 means network error (no response received). */
  readonly statusCode: number;

  /** Machine-readable error code from backend, e.g. "quota_exceeded". */
  readonly code: string;

  /** Human-readable message from backend response. */
  readonly detail: string;

  /** Raw response body for debugging and logging. */
  readonly response: unknown;

  /** True for 5xx errors — safe to retry. */
  readonly retryable: boolean;

  constructor(params: {
    message: string;
    statusCode: number;
    code: string;
    detail: string;
    response: unknown;
  }) {
    super(params.message);
    this.name = "ApiError";
    this.statusCode = params.statusCode;
    this.code = params.code;
    this.detail = params.detail;
    this.response = params.response;
    this.retryable = params.statusCode >= 500;

    // Maintain proper prototype chain for instanceof checks
    Object.setPrototypeOf(this, ApiError.prototype);
  }

  /** 401 — token missing or expired. */
  get isUnauthorized(): boolean { return this.statusCode === 401; }

  /** 402 — quota exceeded or subscription required. */
  get isPaymentRequired(): boolean { return this.statusCode === 402; }

  /** 403 — authenticated but not permitted. */
  get isForbidden(): boolean { return this.statusCode === 403; }

  /** 404 — resource not found or not owned by this user. */
  get isNotFound(): boolean { return this.statusCode === 404; }

  /** 409 — conflict (duplicate, already cancelled, etc.). */
  get isConflict(): boolean { return this.statusCode === 409; }

  /** 422 — Pydantic / FastAPI validation error. */
  get isValidationError(): boolean { return this.statusCode === 422; }
}

// -------------------------------------------------------------------------- //
// Transformation utilities                                                     //
// -------------------------------------------------------------------------- //

/**
 * Convert a single snake_case string to camelCase.
 *
 * @example snakeToCamel("job_id")         → "jobId"
 * @example snakeToCamel("total_cost_usd") → "totalCostUsd"
 */
export function snakeToCamel(str: string): string {
  return str.replace(/_([a-z])/g, (_, letter: string) => letter.toUpperCase());
}

/**
 * Convert a single camelCase string to snake_case.
 *
 * @example camelToSnake("jobId")        → "job_id"
 * @example camelToSnake("inputText")    → "input_text"
 */
export function camelToSnake(str: string): string {
  return str.replace(/[A-Z]/g, (letter) => `_${letter.toLowerCase()}`);
}

/**
 * Recursively convert all object keys from snake_case to camelCase.
 * Handles nested objects, arrays, null, and primitives correctly.
 *
 * Applied automatically to every API response by the response interceptor.
 */
export function camelizeKeys<T>(data: unknown): T {
  if (data === null || data === undefined) return data as T;

  if (Array.isArray(data)) {
    return data.map((item) => camelizeKeys(item)) as T;
  }

  if (typeof data === "object" && !(data instanceof Date)) {
    const result: Record<string, unknown> = {};
    for (const [key, value] of Object.entries(
      data as Record<string, unknown>
    )) {
      result[snakeToCamel(key)] = camelizeKeys(value);
    }
    return result as T;
  }

  return data as T;
}

/**
 * Recursively convert all object keys from camelCase to snake_case.
 * Applied automatically to every request payload by the request interceptor.
 */
export function decamelizeKeys<T>(data: unknown): T {
  if (data === null || data === undefined) return data as T;

  if (Array.isArray(data)) {
    return data.map((item) => decamelizeKeys(item)) as T;
  }

  if (typeof data === "object" && !(data instanceof Date)) {
    const result: Record<string, unknown> = {};
    for (const [key, value] of Object.entries(
      data as Record<string, unknown>
    )) {
      result[camelToSnake(key)] = decamelizeKeys(value);
    }
    return result as T;
  }

  return data as T;
}

// -------------------------------------------------------------------------- //
// Token management                                                             //
// -------------------------------------------------------------------------- //

/**
 * Auth token utilities backed by cookies.
 * Cookies survive page refresh and work in SSR contexts (unlike localStorage).
 */
export const tokenManager = {
  /** Get the current access token, or null if not authenticated. */
  getToken(): string | null {
    return Cookies.get(TOKEN_COOKIE_KEY) ?? null;
  },

  /**
   * Persist the access token.
   * Expires in 30 minutes — matches backend ACCESS_TOKEN_EXPIRE_MINUTES.
   */
  setToken(token: string): void {
    Cookies.set(TOKEN_COOKIE_KEY, token, {
      expires: 1 / 48,   // 30 minutes expressed as fraction of a day
      sameSite: "strict",
      secure: process.env.NODE_ENV === "production",
    });
  },

  /** Get the refresh token, or null if absent. */
  getRefreshToken(): string | null {
    return Cookies.get(REFRESH_COOKIE_KEY) ?? null;
  },

  /**
   * Persist the refresh token.
   * Expires in 7 days.
   */
  setRefreshToken(token: string): void {
    Cookies.set(REFRESH_COOKIE_KEY, token, {
      expires: 7,
      sameSite: "strict",
      secure: process.env.NODE_ENV === "production",
    });
  },

  /** Remove all auth cookies. Call on logout or 401. */
  clearTokens(): void {
    Cookies.remove(TOKEN_COOKIE_KEY);
    Cookies.remove(REFRESH_COOKIE_KEY);
  },

  /** True if an access token cookie exists. */
  isAuthenticated(): boolean {
    return this.getToken() !== null;
  },
};

// -------------------------------------------------------------------------- //
// Axios instance                                                               //
// -------------------------------------------------------------------------- //

/**
 * The configured Axios instance.
 * Import this in other modules only if you need raw AxiosRequestConfig access.
 * For all regular calls use the typed helpers (apiGet, apiPost, etc.) below.
 */
export const apiClient: AxiosInstance = axios.create({
  baseURL: API_BASE_URL,
  timeout: DEFAULT_TIMEOUT_MS,
  headers: {
    "Content-Type": "application/json",
    Accept: "application/json",
  },
});

// -------------------------------------------------------------------------- //
// Request interceptor                                                          //
// -------------------------------------------------------------------------- //

apiClient.interceptors.request.use(
  (config: InternalAxiosRequestConfig) => {
    // Attach Bearer token if present
    const token = tokenManager.getToken();
    if (token) {
      config.headers.Authorization = `Bearer ${token}`;
    }

    // Transform request body: camelCase → snake_case
    if (
      config.data &&
      typeof config.data === "object" &&
      !(config.data instanceof FormData) &&
      !(config.data instanceof URLSearchParams)
    ) {
      config.data = decamelizeKeys(config.data);
    }

    // Transform query params: camelCase → snake_case
    if (config.params && typeof config.params === "object") {
      config.params = decamelizeKeys(config.params);
    }

    if (process.env.NODE_ENV === "development") {
      console.debug(
        `[API →] ${config.method?.toUpperCase() ?? "?"} ${config.url}`,
        config.data ?? config.params ?? ""
      );
    }

    return config;
  },
  (error: AxiosError) => Promise.reject(error)
);

// -------------------------------------------------------------------------- //
// Response interceptor                                                         //
// -------------------------------------------------------------------------- //

apiClient.interceptors.response.use(
  (response: AxiosResponse) => {
    // Transform response keys: snake_case → camelCase
    if (response.data && typeof response.data === "object") {
      response.data = camelizeKeys(response.data);
    }

    if (process.env.NODE_ENV === "development") {
      console.debug(
        `[API ←] ${response.status} ${response.config.url}`,
        response.data
      );
    }

    return response;
  },
  (error: AxiosError) => {
    const status = error.response?.status ?? 0;
    const raw = error.response?.data as Record<string, unknown> | undefined;

    // 401: clear tokens and redirect to login
    if (status === 401) {
      tokenManager.clearTokens();
      if (typeof window !== "undefined") {
        window.location.href = "/login?reason=session_expired";
      }
    }

    // Extract error code — backend uses "error" or "code" key
    const errorCode =
      (raw?.["error"] as string | undefined) ??
      (raw?.["code"] as string | undefined) ??
      "unknown_error";

    // Extract human-readable detail — backend uses "detail" or "message"
    const detailRaw = raw?.["detail"];
    const errorDetail =
      typeof detailRaw === "string"
        ? detailRaw
        : typeof detailRaw === "object" && detailRaw !== null
        ? JSON.stringify(detailRaw)
        : (raw?.["message"] as string | undefined) ??
          error.message ??
          "An unexpected error occurred";

    const apiError = new ApiError({
      message: errorDetail,
      statusCode: status,
      code: errorCode,
      detail: errorDetail,
      response: raw,
    });

    if (process.env.NODE_ENV === "development") {
      console.error(
        `[API ✗] ${status} ${error.config?.url ?? "unknown"}`,
        apiError
      );
    }

    return Promise.reject(apiError);
  }
);

// -------------------------------------------------------------------------- //
// Retry utility                                                                //
// -------------------------------------------------------------------------- //

/**
 * Wrap an API call with automatic retry for 5xx (server) errors.
 * Uses exponential backoff: 1 s → 2 s → 4 s.
 * 4xx errors are never retried.
 *
 * @param fn - Async function wrapping the API call
 * @param maxRetries - Maximum attempts including the first (default 3)
 */
export async function withRetry<T>(
  fn: () => Promise<T>,
  maxRetries = 3
): Promise<T> {
  let lastError: ApiError | undefined;

  for (let attempt = 0; attempt < maxRetries; attempt++) {
    try {
      return await fn();
    } catch (error) {
      if (error instanceof ApiError && error.retryable) {
        lastError = error;
        const delayMs = Math.pow(2, attempt) * 1000;
        await new Promise((resolve) => setTimeout(resolve, delayMs));
      } else {
        throw error;
      }
    }
  }

  // All attempts exhausted
  throw lastError!;
}

// -------------------------------------------------------------------------- //
// Typed request helpers                                                        //
// -------------------------------------------------------------------------- //

/**
 * Type-safe GET. Applies camelCase transformation automatically.
 */
export async function apiGet<T>(
  url: string,
  params?: Record<string, unknown>,
  config?: AxiosRequestConfig
): Promise<T> {
  const response = await apiClient.get<T>(url, { params, ...config });
  return response.data;
}

/**
 * Type-safe POST. Transforms request camelCase→snake_case and response
 * snake_case→camelCase automatically.
 */
export async function apiPost<T>(
  url: string,
  data?: unknown,
  config?: AxiosRequestConfig
): Promise<T> {
  const response = await apiClient.post<T>(url, data, config);
  return response.data;
}

/**
 * Type-safe PUT.
 */
export async function apiPut<T>(
  url: string,
  data?: unknown,
  config?: AxiosRequestConfig
): Promise<T> {
  const response = await apiClient.put<T>(url, data, config);
  return response.data;
}

/**
 * Type-safe PATCH.
 */
export async function apiPatch<T>(
  url: string,
  data?: unknown,
  config?: AxiosRequestConfig
): Promise<T> {
  const response = await apiClient.patch<T>(url, data, config);
  return response.data;
}

/**
 * Type-safe DELETE.
 */
export async function apiDelete<T = void>(
  url: string,
  config?: AxiosRequestConfig
): Promise<T> {
  const response = await apiClient.delete<T>(url, config);
  return response.data;
}

/**
 * Multipart file upload with progress reporting.
 * Uses extended 120 s timeout.
 *
 * @param url - Upload endpoint
 * @param formData - FormData containing the file(s)
 * @param onProgress - Callback receiving 0–100 progress percent
 */
export async function apiUpload<T>(
  url: string,
  formData: FormData,
  onProgress?: (progressPercent: number) => void
): Promise<T> {
  const response = await apiClient.post<T>(url, formData, {
    timeout: UPLOAD_TIMEOUT_MS,
    headers: { "Content-Type": "multipart/form-data" },
    onUploadProgress: (evt) => {
      if (onProgress && evt.total) {
        onProgress(Math.round((evt.loaded / evt.total) * 100));
      }
    },
  });
  return response.data;
}

// -------------------------------------------------------------------------- //
// Auth API                                                                     //
// -------------------------------------------------------------------------- //

/** Response from POST /auth/token. */
export type LoginResponse = {
  readonly accessToken: string;
  readonly tokenType: "bearer";
};

/** Response from POST /auth/register. */
export type RegisterResponse = {
  readonly id: string;
  readonly email: string;
  readonly fullName: string | null;
  readonly role: string;
  readonly createdAt: string;
};

/** Registration payload. */
export type RegisterRequest = {
  email: string;
  password: string;
  fullName?: string;
};

/**
 * Authenticate with email + password.
 * Uses OAuth2 password flow (application/x-www-form-urlencoded).
 * Stores the returned token in a cookie automatically.
 *
 * @throws ApiError(401) on invalid credentials
 */
export async function login(
  email: string,
  password: string
): Promise<LoginResponse> {
  const form = new URLSearchParams();
  form.append("username", email);
  form.append("password", password);

  // Bypass the JSON interceptor — OAuth2 requires form encoding
  const response = await apiClient.post<LoginResponse>(
    "/auth/token",
    form.toString(),
    { headers: { "Content-Type": "application/x-www-form-urlencoded" } }
  );

  const data = response.data;
  tokenManager.setToken(data.accessToken);
  return data;
}

/**
 * Register a new user account.
 *
 * @throws ApiError(409) if email is already registered
 * @throws ApiError(422) if validation fails (password too short, etc.)
 */
export async function register(
  payload: RegisterRequest
): Promise<RegisterResponse> {
  return apiPost<RegisterResponse>("/auth/register", payload);
}

/**
 * Logout: clear local auth cookies.
 * No backend call is needed — JWTs are stateless.
 */
export function logout(): void {
  tokenManager.clearTokens();
}
