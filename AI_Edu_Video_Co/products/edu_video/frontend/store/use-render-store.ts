/**
 * use-render-store.ts
 * Rendering pipeline progress, polling lifecycle, quality report,
 * and delivery state for the active project.
 */

import { create } from "zustand";
import { devtools } from "zustand/middleware";
import type {
  ProjectStatus,
  ProjectStatusResponse,
  RenderingResult,
  QualityReport,
  DeliveryResult,
} from "@/types";

// -------------------------------------------------------------------------- //
// Helpers                                                                       //
// -------------------------------------------------------------------------- //

/** Return a smooth estimated progress percentage for a pipeline status. */
function computeProgress(status: ProjectStatus): number {
  const map: Partial<Record<ProjectStatus, number>> = {
    pending:       5,
    queued:        10,
    orchestrating: 35,
    rendering:     70,
    review:        90,
    done:          100,
    failed:        0,
    cancelled:     0,
  };
  return map[status] ?? 0;
}

/** Return a user-facing progress message. */
function computeProgressMessage(
  status: ProjectStatus,
  queuePosition: number | null
): string {
  if (status === "queued" && queuePosition !== null) {
    return queuePosition === 1
      ? "You're next in queue!"
      : `Position ${queuePosition} in queue`;
  }
  const map: Record<ProjectStatus, string> = {
    pending:       "Preparing your project…",
    queued:        "Waiting for a worker to pick up your job…",
    orchestrating: "AI is generating your script and visual plan…",
    rendering:     "Rendering scenes and adding narration…",
    review:        "An expert is reviewing your video…",
    done:          "Your video is ready!",
    failed:        "Something went wrong during generation",
    cancelled:     "Project was cancelled",
  };
  return map[status] ?? "Processing…";
}

const TERMINAL_STATUSES: ProjectStatus[] = ["done", "failed", "cancelled"];

// -------------------------------------------------------------------------- //
// State + Actions types                                                         //
// -------------------------------------------------------------------------- //

type RenderState = {
  // Polling
  isPolling:          boolean;
  pollingProjectId:   string | null;
  pollIntervalId:     ReturnType<typeof setInterval> | null;
  consecutiveErrors:  number;

  // Pipeline progress
  currentStatus:              ProjectStatus | null;
  estimatedProgressPercent:   number;
  progressMessage:            string;
  queuePosition:              number | null;

  // Final pipeline results
  renderingResult: RenderingResult | null;
  qualityReport:   QualityReport | null;
  deliveryResult:  DeliveryResult | null;

  // Error
  renderError:  string | null;
  isFatalError: boolean;

  // Timing
  startedAt:    string | null;  // ISO 8601
  completedAt:  string | null;  // ISO 8601
};

type RenderActions = {
  // Polling control
  /** Begin polling — idempotent if same projectId already polling. */
  startPolling:      (projectId: string) => void;
  /** Stop polling and clear the interval. */
  stopPolling:       () => void;
  /** Record a polling error; increments consecutive error count. */
  setPollingError:   (error: string, isFatal?: boolean) => void;

  // Status updates
  /** Apply a status response from the polling endpoint. */
  updateFromStatusResponse: (response: ProjectStatusResponse) => void;
  /** Manually override status (e.g. from WebSocket event). */
  setManualStatus:          (status: ProjectStatus, message?: string) => void;

  // Results
  setRenderingResult: (result: RenderingResult) => void;
  setQualityReport:   (report: QualityReport) => void;
  setDeliveryResult:  (result: DeliveryResult) => void;

  // Error
  setRenderError: (error: string | null, isFatal?: boolean) => void;
  clearError:     () => void;

  // Reset
  reset:              () => void;
  resetForNewProject: (projectId: string) => void;
};

// -------------------------------------------------------------------------- //
// Initial state                                                                 //
// -------------------------------------------------------------------------- //

const INITIAL_STATE: RenderState = {
  isPolling:                 false,
  pollingProjectId:          null,
  pollIntervalId:            null,
  consecutiveErrors:         0,
  currentStatus:             null,
  estimatedProgressPercent:  0,
  progressMessage:           "",
  queuePosition:             null,
  renderingResult:           null,
  qualityReport:             null,
  deliveryResult:            null,
  renderError:               null,
  isFatalError:              false,
  startedAt:                 null,
  completedAt:               null,
};

// -------------------------------------------------------------------------- //
// Store                                                                         //
// -------------------------------------------------------------------------- //

export const useRenderStore = create<RenderState & RenderActions>()(
  devtools(
    (set, get) => ({
      ...INITIAL_STATE,

      startPolling: (projectId) => {
        const s = get();
        if (s.isPolling && s.pollingProjectId === projectId) return;
        set(
          {
            isPolling:         true,
            pollingProjectId:  projectId,
            consecutiveErrors: 0,
            renderError:       null,
            isFatalError:      false,
            startedAt:         new Date().toISOString(),
            completedAt:       null,
          },
          false,
          "startPolling"
        );
      },

      stopPolling: () => {
        const { pollIntervalId } = get();
        if (pollIntervalId) clearInterval(pollIntervalId);
        set({ isPolling: false, pollIntervalId: null }, false, "stopPolling");
      },

      setPollingError: (error, isFatal = false) =>
        set(
          (s) => ({
            consecutiveErrors: s.consecutiveErrors + 1,
            renderError:       error,
            isFatalError:      isFatal,
            isPolling:         isFatal ? false : s.isPolling,
          }),
          false,
          "setPollingError"
        ),

      updateFromStatusResponse: (response) =>
        set(
          (s) => {
            const isTerminal = TERMINAL_STATUSES.includes(response.status);
            return {
              currentStatus:             response.status,
              estimatedProgressPercent:  computeProgress(response.status),
              progressMessage:           computeProgressMessage(
                response.status,
                response.queuePosition ?? null
              ),
              queuePosition:     response.queuePosition ?? null,
              consecutiveErrors: 0,
              isPolling:         isTerminal ? false : s.isPolling,
              completedAt:       isTerminal
                ? (s.completedAt ?? new Date().toISOString())
                : s.completedAt,
              renderError:
                response.status === "failed"
                  ? (response.errorMessage ?? "Generation failed")
                  : null,
              isFatalError: response.status === "failed",
            };
          },
          false,
          "updateFromStatusResponse"
        ),

      setManualStatus: (status, message) =>
        set(
          {
            currentStatus:            status,
            estimatedProgressPercent: computeProgress(status),
            progressMessage:          message ?? computeProgressMessage(status, null),
          },
          false,
          "setManualStatus"
        ),

      setRenderingResult: (result) =>
        set({ renderingResult: result }, false, "setRenderingResult"),

      setQualityReport: (report) =>
        set({ qualityReport: report }, false, "setQualityReport"),

      setDeliveryResult: (result) =>
        set({ deliveryResult: result }, false, "setDeliveryResult"),

      setRenderError: (error, isFatal = false) =>
        set({ renderError: error, isFatalError: isFatal }, false, "setRenderError"),

      clearError: () =>
        set({ renderError: null, isFatalError: false }, false, "clearError"),

      reset: () => {
        const { pollIntervalId } = get();
        if (pollIntervalId) clearInterval(pollIntervalId);
        set(INITIAL_STATE, false, "reset");
      },

      resetForNewProject: (projectId) => {
        const { pollIntervalId } = get();
        if (pollIntervalId) clearInterval(pollIntervalId);
        set(
          { ...INITIAL_STATE, pollingProjectId: projectId },
          false,
          "resetForNewProject"
        );
      },
    }),
    { name: "EduVideo:Render" }
  )
);

// -------------------------------------------------------------------------- //
// Selectors                                                                     //
// -------------------------------------------------------------------------- //

type S = RenderState & RenderActions;

/** Progress bar data. */
export const selectRenderProgress = (s: S) => ({
  isPolling:     s.isPolling,
  status:        s.currentStatus,
  percent:       s.estimatedProgressPercent,
  message:       s.progressMessage,
  queuePosition: s.queuePosition,
});

/** Error state. */
export const selectRenderError = (s: S) => ({
  error:   s.renderError,
  isFatal: s.isFatalError,
});

/** All result data available after pipeline completion. */
export const selectRenderResults = (s: S) => ({
  renderingResult: s.renderingResult,
  qualityReport:   s.qualityReport,
  deliveryResult:  s.deliveryResult,
});

/** True if pipeline has finished (any terminal state). */
export const selectIsRenderComplete = (s: S): boolean =>
  s.currentStatus !== null && TERMINAL_STATUSES.includes(s.currentStatus);

/** True if video is fully ready for playback. */
export const selectIsVideoReady = (s: S): boolean =>
  s.currentStatus === "done" &&
  s.deliveryResult !== null &&
  s.deliveryResult.publicVideoUrl.length > 0;

/** Elapsed processing time in seconds since polling started. */
export const selectElapsedSeconds = (s: S): number => {
  if (!s.startedAt) return 0;
  const end = s.completedAt
    ? new Date(s.completedAt).getTime()
    : Date.now();
  return Math.floor((end - new Date(s.startedAt).getTime()) / 1_000);
};
