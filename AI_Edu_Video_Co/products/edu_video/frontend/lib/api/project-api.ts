/**
 * project-api.ts
 * All endpoints related to projects (backend: "jobs").
 * Frontend uses the term "Project" — backend uses "Job".
 */

import { apiGet, apiPost, apiDelete, withRetry } from "./client";
import type {
  Project,
  CreateProjectRequest,
  CreateProjectResponse,
  ProjectListResponse,
  ProjectListParams,
  ProjectStatusResponse,
} from "@/types";

const BASE = "/api/v1/jobs";

// -------------------------------------------------------------------------- //
// Project CRUD                                                                  //
// -------------------------------------------------------------------------- //

/**
 * Create a new educational video project.
 *
 * Endpoint: POST /api/v1/jobs/create
 *
 * The backend auto-detects subject and curriculum from input text if omitted.
 * Quota is checked before any pipeline work begins.
 *
 * @param payload - Creation parameters (title + input text / image URL required)
 * @returns Response with job_id, queue position, and estimated duration
 *
 * @throws ApiError(402) quota exceeded or subject/curriculum not on user's tier
 * @throws ApiError(403) subject or curriculum blocked by feature gate
 * @throws ApiError(422) validation failure (text too short, unknown subject, etc.)
 */
export async function createProject(
  payload: CreateProjectRequest
): Promise<CreateProjectResponse> {
  return apiPost<CreateProjectResponse>(`${BASE}/create`, payload);
}

/**
 * Fetch a paginated list of the authenticated user's projects.
 *
 * Endpoint: GET /api/v1/jobs/
 *
 * Results are sorted newest-first by default.
 * Automatically retried up to 3 times on 5xx errors.
 *
 * @param params - Optional filter by status + pagination (page, limit)
 * @returns Paginated project list with total count
 */
export async function listProjects(
  params?: ProjectListParams
): Promise<ProjectListResponse> {
  return withRetry(() =>
    apiGet<ProjectListResponse>(BASE, params as Record<string, unknown>)
  );
}

/**
 * Fetch a single project by its UUID.
 *
 * Endpoint: GET /api/v1/jobs/{job_id}
 *
 * Returns the full project including scene summaries when available.
 * Retried on transient server errors.
 *
 * @param projectId - UUID of the project
 * @returns Full Project object
 *
 * @throws ApiError(404) project not found or belongs to a different user
 */
export async function getProject(projectId: string): Promise<Project> {
  return withRetry(() => apiGet<Project>(`${BASE}/${projectId}`));
}

/**
 * Poll lightweight status for an active project.
 *
 * Endpoint: GET /api/v1/jobs/{job_id}/status
 *
 * Designed for tight polling loops during processing.
 * Returns only status, video URL (when done), and queue position.
 * Lower payload than getProject() — prefer this during rendering.
 *
 * @param projectId - UUID of the project
 * @returns Lightweight status response
 *
 * @throws ApiError(404) if project not found
 */
export async function getProjectStatus(
  projectId: string
): Promise<ProjectStatusResponse> {
  return apiGet<ProjectStatusResponse>(`${BASE}/${projectId}/status`);
}

/**
 * Cancel a project that has not yet completed rendering.
 *
 * Endpoint: DELETE /api/v1/jobs/{job_id}
 *
 * Only cancellable when status is one of: pending | queued | failed.
 * Actively rendering or completed projects cannot be cancelled.
 *
 * @param projectId - UUID of the project to cancel
 *
 * @throws ApiError(409) project already rendering or completed
 * @throws ApiError(404) project not found or belongs to another user
 */
export async function cancelProject(projectId: string): Promise<void> {
  return apiDelete<void>(`${BASE}/${projectId}`);
}

// -------------------------------------------------------------------------- //
// Image upload (for image-to-video input)                                      //
// -------------------------------------------------------------------------- //

/**
 * Response from the image upload endpoint.
 */
export type ImageUploadResponse = {
  readonly gcsUrl: string;           // Use as inputImageUrl in createProject()
  readonly filename: string;
  readonly sizeBytes: number;
  readonly mimeType: string;
};

/**
 * Upload an image file to use as project input.
 *
 * Endpoint: POST /api/v1/jobs/upload-image
 *
 * Returns a GCS URL that can be passed as inputImageUrl in createProject().
 * Uses extended 120 s timeout and reports progress.
 *
 * @param file - Image file (JPEG, PNG, WebP, max 10 MB)
 * @param onProgress - Optional upload progress callback (0–100)
 * @returns GCS URL of the uploaded image
 *
 * @throws ApiError(413) file too large
 * @throws ApiError(415) unsupported file type
 */
export async function uploadProjectImage(
  file: File,
  onProgress?: (percent: number) => void
): Promise<ImageUploadResponse> {
  const { apiUpload } = await import("./client");
  const form = new FormData();
  form.append("file", file);
  return apiUpload<ImageUploadResponse>(
    `${BASE}/upload-image`,
    form,
    onProgress
  );
}

// -------------------------------------------------------------------------- //
// Scene retrieval                                                               //
// -------------------------------------------------------------------------- //

/**
 * Fetch all scenes for a project.
 *
 * Endpoint: GET /api/v1/jobs/{job_id}/scenes
 *
 * Returns scenes sorted by sceneIndex ascending.
 * Available once project reaches "orchestrating" status.
 *
 * @param projectId - UUID of the project
 * @returns Array of scenes (may be empty during early pipeline stages)
 */
export async function getProjectScenes(
  projectId: string
): Promise<import("@/types").Scene[]> {
  return withRetry(() =>
    apiGet<import("@/types").Scene[]>(`${BASE}/${projectId}/scenes`)
  );
}

/**
 * Request partial scene regeneration.
 *
 * Endpoint: POST /api/v1/jobs/{job_id}/regen
 *
 * Triggers re-rendering of specific scenes (Layers 4 + 5 only).
 * Use after user feedback on poor animation or audio.
 *
 * @param projectId - UUID of the project
 * @param sceneIndices - 0-based indices of scenes to regenerate
 * @param reason - Reason string for logging (e.g. "user_feedback:poor_animation")
 *
 * @throws ApiError(409) if project is not in a state that allows regen
 */
export async function regenScenes(
  projectId: string,
  sceneIndices: number[],
  reason: string
): Promise<void> {
  return apiPost<void>(`${BASE}/${projectId}/regen`, {
    sceneIndices,
    reason,
  });
}

// -------------------------------------------------------------------------- //
// Subtitle download                                                             //
// -------------------------------------------------------------------------- //

/**
 * Download subtitle file content for a completed project.
 *
 * Endpoint: GET /api/v1/jobs/{job_id}/subtitles
 *
 * Returns raw SRT or VTT content as a string.
 * Only available on premium tier when project status = "done".
 *
 * @param projectId - UUID of the project
 * @param format - "srt" (default) or "vtt"
 * @returns Subtitle file content as a string
 *
 * @throws ApiError(402) feature not available on free tier
 * @throws ApiError(404) project not found or not yet completed
 */
export async function getSubtitles(
  projectId: string,
  format: "srt" | "vtt" = "srt"
): Promise<string> {
  return apiGet<string>(`${BASE}/${projectId}/subtitles`, { format });
}
