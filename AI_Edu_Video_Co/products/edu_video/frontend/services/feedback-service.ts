/**
 * feedback-service.ts
 * Feedback submission, review queue management, and reviewer decision flows.
 */

import {
  submitFeedback,
  getProjectFeedback,
  submitReviewDecision,
  getReviewQueue,
  getReviewDetail,
  getRecentCorrections,
} from "@/lib/api/feedback-api";
import { FeedbackSchema, ApprovalSchema, safeValidate } from "@/lib/validators";
import type {
  FeedbackRequest,
  FeedbackResult,
  Feedback,
} from "@/types";
import type {
  ReviewQueueResponse,
  ReviewQueueParams,
  ReviewDecisionRequest,
  ReviewDecisionResult,
  ReviewDetail,
  CorrectionEntry,
} from "@/lib/api/feedback-api";
import type { ApiError } from "@/lib/api/client";
import type { ServiceResult } from "./project-service";

export type { ServiceResult };

// -------------------------------------------------------------------------- //
// submitProjectFeedback                                                         //
// -------------------------------------------------------------------------- //

/**
 * Submit user feedback on a delivered project or specific scene.
 * Validates feedback before sending; maps error codes to messages.
 *
 * @param projectId - UUID of the project
 * @param input - Raw feedback form values
 * @returns ServiceResult with FeedbackResult (includes triggered action)
 */
export async function submitProjectFeedback(
  projectId: string,
  input: Record<string, unknown>
): Promise<ServiceResult<FeedbackResult>> {
  const validation = safeValidate(FeedbackSchema, input);
  if (!validation.data) {
    return {
      success:     false,
      error:       "Please fix the errors in your feedback form",
      fieldErrors: validation.errors ?? undefined,
    };
  }

  const { feedbackType, sceneIndex, rating, comment } = validation.data;

  try {
    const result = await submitFeedback(projectId, {
      feedbackType,
      sceneIndex: sceneIndex ?? undefined,
      rating:     rating    ?? undefined,
      comment:    comment   || undefined,
    });

    return { success: true, data: result };
  } catch (error) {
    const err = error as ApiError;

    if (err.isForbidden) {
      return {
        success: false,
        error:   "You can only submit feedback on your own projects.",
      };
    }

    if (err.isNotFound) {
      return {
        success: false,
        error:   "This project was not found. It may have been deleted.",
      };
    }

    return {
      success: false,
      error: err.detail ?? "Failed to submit feedback. Please try again.",
    };
  }
}

// -------------------------------------------------------------------------- //
// loadProjectFeedback                                                           //
// -------------------------------------------------------------------------- //

/**
 * Load all feedback records for a project.
 * Used in the studio feedback panel and admin review detail page.
 *
 * @param projectId - UUID of the project
 * @returns ServiceResult with array of Feedback records
 */
export async function loadProjectFeedback(
  projectId: string
): Promise<ServiceResult<Feedback[]>> {
  try {
    const feedbacks = await getProjectFeedback(projectId);
    return { success: true, data: feedbacks };
  } catch (error) {
    const err = error as ApiError;

    if (err.isForbidden) {
      return {
        success: false,
        error:   "You don't have permission to view this feedback.",
      };
    }

    return {
      success: false,
      error: err.detail ?? "Failed to load feedback.",
    };
  }
}

// -------------------------------------------------------------------------- //
// loadReviewQueue                                                               //
// -------------------------------------------------------------------------- //

/**
 * Load the human review queue for admin panel.
 * Access controlled — returns 403 for non-admin users.
 *
 * @param params - Optional filter and pagination
 * @returns ServiceResult with paginated review queue
 */
export async function loadReviewQueue(
  params?: ReviewQueueParams
): Promise<ServiceResult<ReviewQueueResponse>> {
  try {
    const queue = await getReviewQueue(params);
    return { success: true, data: queue };
  } catch (error) {
    const err = error as ApiError;

    if (err.isForbidden) {
      return {
        success: false,
        error:   "Admin access required to view the review queue.",
      };
    }

    return {
      success: false,
      error: err.detail ?? "Failed to load review queue.",
    };
  }
}

// -------------------------------------------------------------------------- //
// loadReviewDetail                                                              //
// -------------------------------------------------------------------------- //

/**
 * Load full detail of a review record for the admin reviewer panel.
 *
 * @param reviewId - UUID of the review record
 * @returns ServiceResult with ReviewDetail
 */
export async function loadReviewDetail(
  reviewId: string
): Promise<ServiceResult<ReviewDetail>> {
  try {
    const detail = await getReviewDetail(reviewId);
    return { success: true, data: detail };
  } catch (error) {
    const err = error as ApiError;

    if (err.isNotFound) {
      return { success: false, error: "Review record not found." };
    }

    if (err.isForbidden) {
      return { success: false, error: "Admin access required." };
    }

    return {
      success: false,
      error: err.detail ?? "Failed to load review detail.",
    };
  }
}

// -------------------------------------------------------------------------- //
// processReviewDecision                                                         //
// -------------------------------------------------------------------------- //

/**
 * Submit a reviewer's decision (approve / reject / requires_revision).
 * Validates the decision form before sending.
 *
 * Decision outcomes:
 *   approved           → job.status = "done", video delivered
 *   rejected           → job.status = "failed", correction logged
 *   requires_revision  → job stays in "review", correction logged
 *
 * @param reviewId - UUID of the review record
 * @param input - Raw reviewer decision form values
 * @returns ServiceResult with ReviewDecisionResult
 */
export async function processReviewDecision(
  reviewId: string,
  input: Record<string, unknown>
): Promise<ServiceResult<ReviewDecisionResult>> {
  const validation = safeValidate(ApprovalSchema, input);
  if (!validation.data) {
    return {
      success:     false,
      error:       "Please fix the errors in your review form",
      fieldErrors: validation.errors ?? undefined,
    };
  }

  const { action, reviewerNotes, rejectionReason, correctionNotes } =
    validation.data;

  const payload: ReviewDecisionRequest = {
    decision:         action === "approve" ? "approved"
                    : action === "reject"  ? "rejected"
                    :                        "requires_revision",
    reviewerNotes:    reviewerNotes   || undefined,
    rejectionReason:  rejectionReason ?? undefined,
    correctionNotes:  correctionNotes  || undefined,
  };

  try {
    const result = await submitReviewDecision(reviewId, payload);
    return { success: true, data: result };
  } catch (error) {
    const err = error as ApiError;

    if (err.isForbidden) {
      return { success: false, error: "Admin access required." };
    }

    if (err.isNotFound) {
      return { success: false, error: "Review record not found or already processed." };
    }

    return {
      success: false,
      error: err.detail ?? "Failed to submit review decision.",
    };
  }
}

// -------------------------------------------------------------------------- //
// loadRecentCorrections                                                         //
// -------------------------------------------------------------------------- //

/**
 * Load recent correction log entries for the admin analytics panel.
 *
 * @param limit - Number of entries to fetch (default 50)
 * @returns ServiceResult with array of CorrectionEntry
 */
export async function loadRecentCorrections(
  limit = 50
): Promise<ServiceResult<CorrectionEntry[]>> {
  try {
    const entries = await getRecentCorrections(limit);
    return { success: true, data: entries };
  } catch (error) {
    const err = error as ApiError;

    if (err.isForbidden) {
      return { success: false, error: "Admin access required." };
    }

    return {
      success: false,
      error: err.detail ?? "Failed to load correction log.",
    };
  }
                                              }
