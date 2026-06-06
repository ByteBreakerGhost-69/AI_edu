/**
 * index.ts
 * Central re-export for all frontend types.
 *
 * Import pattern:
 *   import type { Project, Subject, CreateProjectRequest } from "@/types";
 *   import { SUBJECTS, SUBJECT_META, isProjectDelivered } from "@/types";
 *
 * Never import directly from individual type files in component code —
 * always import from "@/types" so refactors stay centralised.
 */

// -------------------------------------------------------------------------- //
// project.ts                                                                   //
// -------------------------------------------------------------------------- //

export type {
  Subject,
  Curriculum,
  DifficultyLevel,
  Language,
  ProjectStatus,
  Project,
  CreateProjectRequest,
  CreateProjectResponse,
  ProjectStatusResponse,
  ProjectListResponse,
  ProjectListParams,
  SubjectMeta,
  CurriculumMeta,
} from "./project";

export {
  SUBJECTS,
  CURRICULA,
  DIFFICULTY_LEVELS,
  LANGUAGES,
  LANGUAGE_LABELS,
  PROJECT_STATUS_GROUPS,
  PROJECT_STATUS_LABELS,
  PROJECT_STATUS_COLORS,
  SUBJECT_META,
  CURRICULUM_META,
  isProjectActive,
  isProjectDelivered,
  isProjectTerminal,
  isProjectUnderReview,
  getProjectProgressPercent,
} from "./project";

// -------------------------------------------------------------------------- //
// scene.ts                                                                     //
// -------------------------------------------------------------------------- //

export type {
  RendererType,
  SceneStatus,
  TTSInstructions,
  VisualSpec,
  RefinedScript,
  Scene,
  SceneSummary,
  FinalScenePackage,
  SceneRegenRequest,
  SubtitleCue,
} from "./scene";

export {
  RENDERER_TYPES,
  RENDERER_LABELS,
  RENDERER_ICONS,
  SCENE_STATUS_LABELS,
  isSceneRendered,
  isSceneFailed,
  getTotalDuration,
  getScenesTotalCost,
  getScenesCompletionPercent,
  sortScenesByIndex,
} from "./scene";

// -------------------------------------------------------------------------- //
// render.ts                                                                    //
// -------------------------------------------------------------------------- //

export type {
  SceneRenderResult,
  RenderingResult,
  QualityIssueSeverity,
  QualityIssue,
  AudioValidationReport,
  TimingValidationReport,
  CompletenessReport,
  QualityReport,
  DeliveryStatus,
  DeliveryResult,
  RenderProgressEvent,
  StatusUpdateEvent,
  ErrorEvent,
  WebSocketEvent,
} from "./render";

export {
  QUALITY_ISSUE_SEVERITIES,
  hasNoCriticalIssues,
  isDeliverySuccessful,
  isRenderProgressEvent,
  isStatusUpdateEvent,
  getCriticalIssues,
} from "./render";

// -------------------------------------------------------------------------- //
// feedback.ts                                                                  //
// -------------------------------------------------------------------------- //

export type {
  FeedbackType,
  FeedbackAction,
  FeedbackRequest,
  FeedbackResult,
  Feedback,
  RatingOption,
} from "./feedback";

export {
  FEEDBACK_TYPES,
  FEEDBACK_TYPE_LABELS,
  FEEDBACK_TYPE_DESCRIPTIONS,
  FEEDBACK_AUTO_ACTIONS,
  FEEDBACK_ACTION_MESSAGES,
  RATING_OPTIONS,
  willTriggerRegen,
  requiresExpertReview,
} from "./feedback";

// -------------------------------------------------------------------------- //
// subscription.ts                                                              //
// -------------------------------------------------------------------------- //

export type {
  Tier,
  SubscriptionStatus,
  TierFeatures,
  FeatureGateResult,
  Subscription,
  QuotaStatus,
  InvoiceStatus,
  InvoiceSummary,
  InvoiceListResponse,
  UpgradeRequest,
  CancelSubscriptionRequest,
  CheckoutSessionResponse,
  SetupIntentResponse,
  PaymentMethod,
  PlanDisplayConfig,
} from "./subscription";

export {
  TIERS,
  PLAN_DISPLAY_CONFIG,
  isPremiumActive,
  isTrialing,
  isCancelledWithAccess,
  getDaysUntilReset,
  formatUsd,
} from "./subscription";
