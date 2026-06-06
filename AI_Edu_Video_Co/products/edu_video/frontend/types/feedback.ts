/**
 * feedback.ts
 * User feedback types — maps to backend models/feedback.py + layer6_delivery/feedback_service.py.
 */

// -------------------------------------------------------------------------- //
// Feedback type enum                                                            //
// -------------------------------------------------------------------------- //

/**
 * Categories of user feedback on a delivered video.
 * Maps to backend FeedbackTypeEnum in models/feedback.py.
 */
export const FEEDBACK_TYPES = {
  POOR_ANIMATION:      "poor_animation",
  AUDIO_ISSUE:         "audio_issue",
  INCORRECT_CONTENT:   "incorrect_content",
  WRONG_DIFFICULTY:    "wrong_difficulty",
  CURRICULUM_MISMATCH: "curriculum_mismatch",
  OTHER:               "other",
} as const;

export type FeedbackType =
  (typeof FEEDBACK_TYPES)[keyof typeof FEEDBACK_TYPES];

/**
 * Human-readable feedback type labels.
 */
export const FEEDBACK_TYPE_LABELS: Record<FeedbackType, string> = {
  poor_animation:      "Animation Quality",
  audio_issue:         "Audio Problem",
  incorrect_content:   "Incorrect Content",
  wrong_difficulty:    "Wrong Difficulty Level",
  curriculum_mismatch: "Curriculum Mismatch",
  other:               "Other",
};

/**
 * Feedback type descriptions to help users choose correctly.
 */
export const FEEDBACK_TYPE_DESCRIPTIONS: Record<FeedbackType, string> = {
  poor_animation:
    "The visual animation was unclear, too fast, or visually incorrect.",
  audio_issue:
    "The narration audio was cut off, too quiet, or had audio gaps.",
  incorrect_content:
    "The educational content contains a factual error or wrong formula.",
  wrong_difficulty:
    "The content level was too easy or too difficult for the selected level.",
  curriculum_mismatch:
    "The content does not align with the selected curriculum requirements.",
  other:
    "A different issue not covered by the categories above.",
};

/**
 * Actions the platform automatically triggers based on feedback type.
 * Mirrors backend AUTO_REGEN_CONDITIONS and AUTO_REVIEW_CONDITIONS.
 */
export const FEEDBACK_AUTO_ACTIONS: Record<
  FeedbackType,
  { regenIfSceneProvided: boolean; triggersReview: boolean }
> = {
  poor_animation:      { regenIfSceneProvided: true,  triggersReview: false },
  audio_issue:         { regenIfSceneProvided: true,  triggersReview: false },
  incorrect_content:   { regenIfSceneProvided: false, triggersReview: true  },
  wrong_difficulty:    { regenIfSceneProvided: false, triggersReview: false },
  curriculum_mismatch: { regenIfSceneProvided: false, triggersReview: true  },
  other:               { regenIfSceneProvided: false, triggersReview: false },
};

// -------------------------------------------------------------------------- //
// Feedback action result                                                        //
// -------------------------------------------------------------------------- //

/**
 * What action the platform took in response to feedback.
 * Maps to backend FeedbackResult.action_triggered field.
 */
export type FeedbackAction =
  | "none"            // Feedback stored, no automatic action
  | "partial_regen"   // Specific scene is being re-rendered
  | "review_queue"    // Job queued for human expert review
  | "correction_log"; // Factual error logged for content team

/**
 * Human-readable descriptions of feedback actions shown to the user.
 */
export const FEEDBACK_ACTION_MESSAGES: Record<FeedbackAction, string> = {
  none:
    "Thank you for your feedback. We'll use it to improve the platform.",
  partial_regen:
    "We're regenerating the affected scene. Check back in a few minutes.",
  review_queue:
    "Your feedback has been flagged for expert review.",
  correction_log:
    "Thank you — we've logged this for content accuracy review.",
};

// -------------------------------------------------------------------------- //
// Core feedback types                                                           //
// -------------------------------------------------------------------------- //

/**
 * Payload for submitting user feedback.
 * Maps to backend FeedbackRequest in layer6_delivery/feedback_service.py.
 */
export type FeedbackRequest = {
  jobId: string;                            // UUID of the project being reviewed
  sceneIndex?: number;                      // Specific scene (0-based); omit for whole video
  feedbackType: FeedbackType;
  rating?: number;                          // 1–5 star rating; optional
  comment?: string;                         // Free-text comment; max 1000 chars
};

/**
 * Response after feedback submission.
 * Maps to backend FeedbackResult in layer6_delivery/feedback_service.py.
 */
export type FeedbackResult = {
  readonly feedbackId: string;              // UUID of the created feedback record
  readonly actionTriggered: FeedbackAction;
  readonly message: string;                 // Human-readable action confirmation
};

/**
 * Stored feedback record from the database.
 * Maps to backend Feedback model in models/feedback.py.
 */
export type Feedback = {
  readonly id: string;                      // UUID
  readonly jobId: string;                   // UUID — foreign key to Project
  readonly userId: string;                  // UUID — who submitted
  readonly sceneIndex: number | null;       // null = whole-video feedback
  readonly feedbackType: FeedbackType;
  readonly rating: number | null;           // 1–5; null if not provided
  readonly comment: string | null;
  readonly isResolved: boolean;             // True when action has been taken
  readonly createdAt: string;               // ISO 8601
};

/**
 * Rating option for the star rating component.
 */
export type RatingOption = {
  readonly value: number;                   // 1–5
  readonly label: string;                   // e.g. "Poor", "Average", "Excellent"
};

export const RATING_OPTIONS: readonly RatingOption[] = [
  { value: 1, label: "Poor" },
  { value: 2, label: "Fair" },
  { value: 3, label: "Average" },
  { value: 4, label: "Good" },
  { value: 5, label: "Excellent" },
] as const;

// -------------------------------------------------------------------------- //
// Type guards                                                                   //
// -------------------------------------------------------------------------- //

/**
 * Type guard: feedback action will trigger scene regeneration.
 */
export function willTriggerRegen(action: FeedbackAction): boolean {
  return action === "partial_regen";
}

/**
 * Type guard: feedback action requires expert review.
 */
export function requiresExpertReview(feedbackType: FeedbackType): boolean {
  return FEEDBACK_AUTO_ACTIONS[feedbackType].triggersReview;
  }
