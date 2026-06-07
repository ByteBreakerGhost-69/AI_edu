/**
 * feedback-api.ts
 * Endpoints for user feedback submission and review queue management.
 */

import { apiGet, apiPost, withRetry } from "./client";
import type {
  FeedbackRequest,
  FeedbackResult,
  Feedback,
} from "@/types";

const FEEDBACK_BASE = "/api/v1/feedback";
const REVIEW_BASE   = "/api/v1/review";

// -------------------------------------------------------------------------- //
// User feedback                                                                 //
// -------------------------------------------------------------------------- //

/**
 * Submit user feedback on a delivered project or specific scene.
 *
 * Endpoint: POST /api/v1/feedback/{job_id}
 *
 * Triggers automatic downstream action based on feedback type:
 *   - poor_animation / audio_issue (with sceneIndex) → partial regen queued
 *   - incorrect_content            → review queue + correction log
 *   - curriculum_mismatch          → review queue
 *   - others                       → logged, no automatic action
 *
 * @param projectId - UUID of the project being reviewed
 * @param payload - Feedback details (type, optional scene index, rating, comment)
 * @returns Result indicating which action was triggered
 *
 * @throws ApiError(403) project belongs to another user
 * @throws ApiError(404) project not found
 * @throws ApiError(422) validation failure (invalid rating, etc.)
 */
export async function submitFeedback(
  projectId: string,
  payload: Omit<FeedbackRequest, "jobId">
): Promise<FeedbackResult> {
  return apiPost<FeedbackResult>(`${FEEDBACK_BASE}/${projectId}`, {
    ...payload,
    jobId: projectId,
  });
}

/**
 * Fetch all feedback submitted for a specific project.
 *
 * Endpoint: GET /api/v1/feedback/{job_id}
 *
 * Returns feedback ordered newest-first.
 *
 * @param projectId - UUID of the project
 * @returns Array of feedback records
 *
 * @throws ApiError(403) project belongs to another user
 * @throws ApiError(404) project not found
 */
export async function getProjectFeedback(
  projectId: string
): Promise<Feedback[]> {
  return withRetry(() =>
    apiGet<Feedback[]>(`${FEEDBACK_BASE}/${projectId}`)
  );
}

// -------------------------------------------------------------------------- //
// Review queue (admin-only)                                                    //
// -------------------------------------------------------------------------- //

/**
 * A single item in the human review queue.
 */
export type ReviewQueueItem = {
  readonly reviewId: string;              // UUID of the Review record
  readonly jobId: string;                 // UUID of the project
  readonly projectTitle: string;
  readonly subject: string;
  readonly curriculum: string;
  readonly triggerReason: string;
  readonly priority: "low" | "normal" | "high" | "urgent";
  readonly confidenceScore: number | null;
  readonly enqueuedAt: string;            // ISO 8601
  readonly queuePosition: number;         // 1-based
};

/**
 * Paginated review queue response.
 */
export type ReviewQueueResponse = {
  readonly items: readonly ReviewQueueItem[];
  readonly total: number;
  readonly page: number;
  readonly limit: number;
};

/**
 * Query params for review queue listing.
 */
export type ReviewQueueParams = {
  page?: number;
  limit?: number;
  priority?: "low" | "normal" | "high" | "urgent";
  triggerReason?: string;
};

/**
 * Fetch the current human review queue.
 *
 * Endpoint: GET /api/v1/review/queue
 * Access: Admin only.
 *
 * @param params - Optional pagination and filter params
 * @returns Paginated review queue ordered by priority and enqueue time
 *
 * @throws ApiError(403) if not admin
 */
export async function getReviewQueue(
  params?: ReviewQueueParams
): Promise<ReviewQueueResponse> {
  return withRetry(() =>
    apiGet<ReviewQueueResponse>(
      `${REVIEW_BASE}/queue`,
      params as Record<string, unknown>
    )
  );
}

// -------------------------------------------------------------------------- //
// Reviewer actions (admin-only)                                                //
// -------------------------------------------------------------------------- //

/**
 * Payload for a reviewer's approval decision.
 */
export type ReviewDecisionRequest = {
  decision: "approved" | "rejected" | "requires_revision";
  reviewerNotes?: string;
  rejectionReason?:
    | "factual_error"
    | "curriculum_mismatch"
    | "poor_quality"
    | "inappropriate_content"
    | "other";
  correctionNotes?: string;
};

/**
 * Result of processing a review decision.
 */
export type ReviewDecisionResult = {
  readonly reviewId: string;
  readonly jobId: string;
  readonly decision: string;
  readonly jobStatusUpdatedTo: string;
  readonly correctionLogged: boolean;
};

/**
 * Submit a reviewer's decision on a queued project.
 *
 * Endpoint: POST /api/v1/review/{review_id}/decision
 * Access: Admin only.
 *
 * Decision outcomes:
 *   approved           → job.status = "done", video delivered
 *   rejected           → job.status = "failed", correction logged
 *   requires_revision  → job stays in "review", correction logged
 *
 * @param reviewId - UUID of the Review record (from ReviewQueueItem)
 * @param payload - Decision details
 * @returns Decision result confirming new job status
 *
 * @throws ApiError(403) if not admin
 * @throws ApiError(404) review record not found
 */
export async function submitReviewDecision(
  reviewId: string,
  payload: ReviewDecisionRequest
): Promise<ReviewDecisionResult> {
  return apiPost<ReviewDecisionResult>(
    `${REVIEW_BASE}/${reviewId}/decision`,
    payload
  );
}

/**
 * Fetch the full details of a specific review record.
 *
 * Endpoint: GET /api/v1/review/{review_id}
 * Access: Admin only.
 *
 * @param reviewId - UUID of the Review record
 * @returns Full review record with project details
 *
 * @throws ApiError(403) if not admin
 * @throws ApiError(404) review record not found
 */
export type ReviewDetail = {
  readonly reviewId: string;
  readonly jobId: string;
  readonly status: "pending" | "approved" | "rejected" | "requires_revision";
  readonly priority: string;
  readonly triggerReason: string;
  readonly confidenceScore: number | null;
  readonly reviewerId: string | null;
  readonly reviewerNotes: string | null;
  readonly correctionNotes: string | null;
  readonly rejectionReason: string | null;
  readonly autoApproved: boolean;
  readonly createdAt: string;             // ISO 8601
  readonly completedAt: string | null;    // ISO 8601
};

export async function getReviewDetail(reviewId: string): Promise<ReviewDetail> {
  return withRetry(() =>
    apiGet<ReviewDetail>(`${REVIEW_BASE}/${reviewId}`)
  );
}

// -------------------------------------------------------------------------- //
// Correction log (admin-only)                                                  //
// -------------------------------------------------------------------------- //

/**
 * A single correction log entry.
 */
export type CorrectionEntry = {
  readonly correctionId: string;
  readonly jobId: string;
  readonly sceneIndex: number | null;
  readonly subject: string;
  readonly curriculum: string;
  readonly errorType: string;
  readonly reportedError: string;
  readonly correctedContent: string | null;
  readonly ingestedToRag: boolean;
  readonly loggedAt: string;             // ISO 8601
  readonly source: string;
};

/**
 * Fetch recent correction log entries.
 *
 * Endpoint: GET /api/v1/review/corrections
 * Access: Admin only.
 *
 * @param limit - Number of entries to return (default 50, max 200)
 * @returns Most recent correction entries, newest first
 *
 * @throws ApiError(403) if not admin
 */
export async function getRecentCorrections(
  limit = 50
): Promise<CorrectionEntry[]> {
  return withRetry(() =>
    apiGet<CorrectionEntry[]>("/api/v1/review/corrections", { limit })
  );
}

/**
 * Fetch error type counts from the correction log.
 *
 * Endpoint: GET /api/v1/review/corrections/counts
 * Access: Admin only.
 *
 * @returns Record mapping error type to occurrence count
 *
 * @throws ApiError(403) if not admin
 */
export async function getCorrectionCounts(): Promise<Record<string, number>> {
  return withRetry(() =>
    apiGet<Record<string, number>>("/api/v1/review/corrections/counts")
  );
}
