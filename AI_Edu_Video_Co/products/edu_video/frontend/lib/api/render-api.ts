/**
 * render-api.ts
 * Endpoints for rendering status, quality reports, and delivery results.
 * Also provides the WebSocket URL builder for real-time progress updates.
 */

import { apiGet, withRetry, API_BASE_URL } from "./client";
import type {
  RenderingResult,
  QualityReport,
  DeliveryResult,
  WebSocketEvent,
} from "@/types";

const BASE = "/api/v1/jobs";

// -------------------------------------------------------------------------- //
// Render result endpoints                                                       //
// -------------------------------------------------------------------------- //

/**
 * Fetch the full rendering result for a completed project.
 *
 * Endpoint: GET /api/v1/jobs/{job_id}/render-result
 *
 * Available once the project reaches "done" or "review" status.
 * Contains the final video URL, all scene render results, and cost breakdown.
 *
 * @param projectId - UUID of the project
 * @returns Complete rendering result including all scene outcomes
 *
 * @throws ApiError(404) project not found
 * @throws ApiError(409) project not yet rendered
 */
export async function getRenderingResult(
  projectId: string
): Promise<RenderingResult> {
  return withRetry(() =>
    apiGet<RenderingResult>(`${BASE}/${projectId}/render-result`)
  );
}

/**
 * Fetch the quality check report for a project.
 *
 * Endpoint: GET /api/v1/jobs/{job_id}/quality-report
 *
 * Available once quality check has completed (status = "done" | "review").
 * Contains audio, timing, and completeness sub-reports.
 *
 * @param projectId - UUID of the project
 * @returns Quality report with overall score and all issues
 *
 * @throws ApiError(404) project not found or quality check not yet run
 */
export async function getQualityReport(
  projectId: string
): Promise<QualityReport> {
  return withRetry(() =>
    apiGet<QualityReport>(`${BASE}/${projectId}/quality-report`)
  );
}

/**
 * Fetch the CDN delivery result for a completed project.
 *
 * Endpoint: GET /api/v1/jobs/{job_id}/delivery
 *
 * Contains public and signed video URLs, CDN headers, and delivery status.
 * Available when project status = "done".
 *
 * @param projectId - UUID of the project
 * @returns Delivery result with all public and signed URLs
 *
 * @throws ApiError(404) project not found
 * @throws ApiError(409) project not yet delivered
 */
export async function getDeliveryResult(
  projectId: string
): Promise<DeliveryResult> {
  return withRetry(() =>
    apiGet<DeliveryResult>(`${BASE}/${projectId}/delivery`)
  );
}

// -------------------------------------------------------------------------- //
// WebSocket URL builder                                                        //
// -------------------------------------------------------------------------- //

/**
 * Build the WebSocket URL for real-time render progress updates.
 *
 * The WebSocket endpoint streams WebSocketEvent objects:
 *   - RenderProgressEvent: stage + percent progress
 *   - StatusUpdateEvent: job status transition
 *   - ErrorEvent: pipeline error with code and message
 *
 * Usage:
 *   const wsUrl = getWebSocketUrl(projectId);
 *   const ws = new WebSocket(wsUrl);
 *   ws.onmessage = (evt) => {
 *     const event: WebSocketEvent = JSON.parse(evt.data);
 *     // narrow with isRenderProgressEvent(), isStatusUpdateEvent(), etc.
 *   };
 *
 * @param projectId - UUID of the project to track
 * @returns Fully qualified WebSocket URL including auth token
 */
export function getWebSocketUrl(projectId: string): string {
  const { tokenManager } = require("./client") as typeof import("./client");
  const token = tokenManager.getToken();

  // Replace http(s):// with ws(s):// for WebSocket URL
  const wsBase = API_BASE_URL.replace(/^http/, "ws");
  const url = `${wsBase}/api/v1/ws/${projectId}`;

  // Pass token as query param — WebSocket cannot set Authorization header
  return token ? `${url}?token=${encodeURIComponent(token)}` : url;
}

// -------------------------------------------------------------------------- //
// Video analytics                                                               //
// -------------------------------------------------------------------------- //

/**
 * Analytics summary for a single project (view count, engagement, etc.).
 * Admin-only endpoint.
 */
export type ProjectAnalytics = {
  readonly projectId: string;
  readonly viewCount: number;
  readonly avgWatchDurationSeconds: number;
  readonly completionRate: number;        // 0.0–1.0
  readonly feedbackCount: number;
  readonly avgRating: number | null;      // null if no ratings yet
  readonly totalCostUsd: number;
  readonly processingTimeSeconds: number;
  readonly rendererDistribution: Record<string, number>;
  readonly updatedAt: string;             // ISO 8601
};

/**
 * Fetch analytics for a specific project.
 *
 * Endpoint: GET /api/v1/analytics/{job_id}
 * Access: Admin only.
 *
 * @param projectId - UUID of the project
 * @returns Analytics summary
 *
 * @throws ApiError(403) if not admin
 */
export async function getProjectAnalytics(
  projectId: string
): Promise<ProjectAnalytics> {
  return withRetry(() =>
    apiGet<ProjectAnalytics>(`/api/v1/analytics/${projectId}`)
  );
}

/**
 * Global platform analytics summary.
 *
 * Endpoint: GET /api/v1/analytics
 * Access: Admin only.
 */
export type GlobalAnalytics = {
  readonly totalJobsCompleted: number;
  readonly totalCostUsd: number;
  readonly timestamp: string;             // ISO 8601
};

/**
 * Fetch global platform analytics.
 *
 * Endpoint: GET /api/v1/analytics
 * Access: Admin only.
 *
 * @throws ApiError(403) if not admin
 */
export async function getGlobalAnalytics(): Promise<GlobalAnalytics> {
  return withRetry(() => apiGet<GlobalAnalytics>("/api/v1/analytics"));
}

// -------------------------------------------------------------------------- //
// Scene-level video utilities                                                   //
// -------------------------------------------------------------------------- //

/**
 * Scene video metadata returned from the signed URL endpoint.
 */
export type SceneVideoMeta = {
  readonly sceneIndex: number;
  readonly signedUrl: string;             // Time-limited direct video URL
  readonly signedExpiry: string;          // ISO 8601
  readonly durationSeconds: number;
  readonly fileSizeBytes: number;
};

/**
 * Get a time-limited signed URL for streaming a single scene's video.
 *
 * Endpoint: GET /api/v1/jobs/{job_id}/scenes/{scene_index}/video
 *
 * Used by the studio video player for scene-level playback.
 *
 * @param projectId - UUID of the project
 * @param sceneIndex - 0-based scene index
 * @returns Signed URL valid for 24 hours
 *
 * @throws ApiError(404) scene not rendered yet
 */
export async function getSceneVideoUrl(
  projectId: string,
  sceneIndex: number
): Promise<SceneVideoMeta> {
  return apiGet<SceneVideoMeta>(
    `${BASE}/${projectId}/scenes/${sceneIndex}/video`
  );
}
