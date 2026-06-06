/**
 * render.ts
 * Rendering pipeline types — maps to backend layer5_rendering schemas.
 * Covers compositor output, quality check reports, and delivery results.
 */

import type { RendererType } from "./scene";

// -------------------------------------------------------------------------- //
// Scene-level render results                                                   //
// -------------------------------------------------------------------------- //

/**
 * Result of rendering a single scene in Layer 5.
 * Maps to backend SceneRenderResult in layer5_rendering/compositor.py.
 */
export type SceneRenderResult = {
  readonly sceneIndex: number;
  readonly renderSuccess: boolean;          // True even if fallback renderer used
  readonly rendererUsed: RendererType;      // Actual renderer (may differ from requested)
  readonly durationSeconds: number;
  readonly ttsCostUsd: number;              // Google Cloud TTS cost (USD)
  readonly renderCostUsd: number;           // Renderer-specific cost (USD)
  readonly error: string | null;            // Error message if renderSuccess=false
  readonly usedFallback: boolean;           // True if primary renderer failed
};

/**
 * Complete rendering output for an entire project.
 * Maps to backend RenderingResult in layer5_rendering/compositor.py.
 */
export type RenderingResult = {
  readonly jobId: string;
  readonly finalVideoUrl: string;           // GCS or CDN URL for the composed video
  readonly thumbnailUrl: string;            // GCS URL for the video thumbnail
  readonly subtitleSrtUrl: string;          // GCS URL for the .srt subtitle file
  readonly subtitleVttUrl: string;          // GCS URL for the .vtt subtitle file
  readonly totalDurationSeconds: number;
  readonly sceneRenderResults: readonly SceneRenderResult[];
  readonly qualityPassed: boolean;          // Result of quality_check_orchestrator.run()
  readonly totalCostUsd: number;            // Sum of all TTS + render costs (USD)
  readonly processingTimeSeconds: number;
};

// -------------------------------------------------------------------------- //
// Quality check types                                                          //
// -------------------------------------------------------------------------- //

/**
 * Quality issue severity levels.
 * Maps to backend QualityIssueSeverity in layer5_rendering/quality_check/__init__.py.
 */
export const QUALITY_ISSUE_SEVERITIES = {
  CRITICAL: "critical", // Must fix — blocks delivery
  WARNING:  "warning",  // Should fix — delivered with flag
  INFO:     "info",     // Log only — no action required
} as const;

export type QualityIssueSeverity =
  (typeof QUALITY_ISSUE_SEVERITIES)[keyof typeof QUALITY_ISSUE_SEVERITIES];

/**
 * Individual quality issue found during validation.
 * Maps to backend QualityIssue in layer5_rendering/quality_check/__init__.py.
 */
export type QualityIssue = {
  readonly severity: QualityIssueSeverity;
  readonly validator: "audio" | "timing" | "completeness";
  readonly sceneIndex: number | null;       // null means job-level issue
  readonly code: string;                    // Machine-readable e.g. "audio_cutoff"
  readonly message: string;                 // Human-readable description
  readonly metricValue: number | null;      // Actual measured value
  readonly thresholdValue: number | null;   // Expected threshold value
};

/**
 * Audio validation report for all scenes.
 * Maps to backend AudioValidationReport in quality_check/audio_validator.py.
 */
export type AudioValidationReport = {
  readonly passed: boolean;
  readonly scenesChecked: number;
  readonly issues: readonly QualityIssue[];
  readonly avgVolumeLufs: number;           // Target: -16.0 LUFS (EBU R128)
  readonly silenceGapCount: number;         // Number of silence gaps detected
  readonly cutoffSceneIndices: readonly number[]; // Scenes with possible audio cutoff
};

/**
 * Timing synchronisation validation report.
 * Maps to backend TimingValidationReport in quality_check/timing_validator.py.
 */
export type TimingValidationReport = {
  readonly passed: boolean;
  readonly scenesChecked: number;
  readonly issues: readonly QualityIssue[];
  readonly totalDurationSeconds: number;    // Actual total video duration
  readonly expectedDurationSeconds: number; // Sum of per-scene estimates
  readonly durationDriftSeconds: number;    // actual - expected
  readonly maxSceneDriftSeconds: number;    // Worst single-scene drift
  readonly syncMethodCounts: Readonly<Record<string, number>>; // e.g. {no_change: 4}
};

/**
 * Content completeness validation report.
 * Maps to backend CompletenessReport in quality_check/content_completeness.py.
 */
export type CompletenessReport = {
  readonly passed: boolean;
  readonly expectedSceneCount: number;
  readonly actualSceneCount: number;
  readonly missingSceneIndices: readonly number[];
  readonly failedSceneIndices: readonly number[];  // Rendered but with renderSuccess=false
  readonly issues: readonly QualityIssue[];
  readonly finalVideoValid: boolean;
  readonly subtitleFilesPresent: boolean;
  readonly finalVideoDurationSeconds: number;
};

/**
 * Aggregated quality report from all three validators.
 * Maps to backend QualityReport in layer5_rendering/quality_check/__init__.py.
 */
export type QualityReport = {
  readonly jobId: string;
  readonly passed: boolean;                 // True only if ALL validators pass
  readonly overallScore: number;            // 0.0–1.0 weighted quality score
  readonly audioReport: AudioValidationReport;
  readonly timingReport: TimingValidationReport;
  readonly completenessReport: CompletenessReport;
  readonly issues: readonly QualityIssue[]; // All issues from all validators, flattened
  readonly recommendations: readonly string[]; // Actionable fix suggestions
  readonly checkedAt: string;               // ISO 8601
  readonly checkDurationSeconds: number;
};

// -------------------------------------------------------------------------- //
// Delivery result                                                               //
// -------------------------------------------------------------------------- //

/**
 * Final delivery status options.
 * Subset of ProjectStatus focused on post-rendering outcomes.
 */
export type DeliveryStatus = "delivered" | "review_required" | "failed";

/**
 * CDN delivery result from Layer 6.
 * Maps to backend DeliveryResult in layer6_delivery/cdn_service.py.
 */
export type DeliveryResult = {
  readonly jobId: string;
  readonly publicVideoUrl: string;          // CDN URL (or GCS if CDN not configured)
  readonly publicThumbnailUrl: string;
  readonly subtitleSrtUrl: string;
  readonly subtitleVttUrl: string;
  readonly signedVideoUrl: string;          // Time-limited signed URL for secure access
  readonly signedExpiry: string;            // ISO 8601 expiry datetime
  readonly cdnHeaders: Readonly<Record<string, string>>;
  readonly deliveryStatus: DeliveryStatus;
  readonly reviewRequired: boolean;
  readonly deliveredAt: string;             // ISO 8601
};

// -------------------------------------------------------------------------- //
// Render progress (WebSocket real-time updates)                                //
// -------------------------------------------------------------------------- //

/**
 * Real-time render progress event received via WebSocket.
 * Frontend subscribes to ws://api/ws/{job_id} for these updates.
 */
export type RenderProgressEvent = {
  readonly type: "render_progress";
  readonly jobId: string;
  readonly stage:
    | "orchestrating"
    | "script_generation"
    | "visual_generation"
    | "tts_synthesis"
    | "rendering"
    | "quality_check"
    | "delivery";
  readonly overallPercent: number;          // 0–100
  readonly currentScene: number | null;     // 0-based; null for non-scene stages
  readonly totalScenes: number | null;
  readonly message: string;                 // Human-readable progress description
  readonly timestamp: string;               // ISO 8601
};

/**
 * WebSocket status update event.
 * Sent when job status changes (e.g. rendering → review).
 */
export type StatusUpdateEvent = {
  readonly type: "status_update";
  readonly jobId: string;
  readonly previousStatus: string;
  readonly newStatus: string;
  readonly videoUrl: string | null;
  readonly message: string;
  readonly timestamp: string;               // ISO 8601
};

/**
 * WebSocket error event.
 */
export type ErrorEvent = {
  readonly type: "error";
  readonly jobId: string;
  readonly code: string;
  readonly message: string;
  readonly timestamp: string;               // ISO 8601
};

/**
 * Discriminated union of all WebSocket event types.
 * Use `event.type` to narrow in switch/if blocks.
 */
export type WebSocketEvent =
  | RenderProgressEvent
  | StatusUpdateEvent
  | ErrorEvent;

// -------------------------------------------------------------------------- //
// Type guards                                                                   //
// -------------------------------------------------------------------------- //

/**
 * Type guard: quality report has no critical issues.
 */
export function hasNoCriticalIssues(report: QualityReport): boolean {
  return !report.issues.some((i) => i.severity === "critical");
}

/**
 * Type guard: delivery succeeded and video is publicly accessible.
 */
export function isDeliverySuccessful(
  result: DeliveryResult
): result is DeliveryResult & { deliveryStatus: "delivered" } {
  return result.deliveryStatus === "delivered";
}

/**
 * Type guard: WebSocket event is a render progress update.
 */
export function isRenderProgressEvent(
  event: WebSocketEvent
): event is RenderProgressEvent {
  return event.type === "render_progress";
}

/**
 * Type guard: WebSocket event is a status update.
 */
export function isStatusUpdateEvent(
  event: WebSocketEvent
): event is StatusUpdateEvent {
  return event.type === "status_update";
}

/**
 * Get critical issues from a quality report.
 */
export function getCriticalIssues(report: QualityReport): QualityIssue[] {
  return report.issues.filter((i) => i.severity === "critical");
  }
