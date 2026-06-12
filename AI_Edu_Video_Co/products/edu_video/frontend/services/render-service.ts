/**
 * render-service.ts
 * Orchestrates render polling, result fetching, delivery, and subtitle loading.
 */

import { getProjectStatus } from "@/lib/api/project-api";
import {
  getRenderingResult,
  getQualityReport,
  getDeliveryResult,
  getSceneVideoUrl,
} from "@/lib/api/render-api";
import { getSubtitles } from "@/lib/api/project-api";
import { STATUS_POLL_INTERVAL_MS, STATUS_POLL_MAX_DURATION_MS } from "@/lib/constants";
import { parseSubtitleContent } from "@/lib/video/subtitle-utils";
import type {
  ProjectStatus,
  ProjectStatusResponse,
  RenderingResult,
  QualityReport,
  DeliveryResult,
} from "@/types";
import type { ApiError } from "@/lib/api/client";
import type { ServiceResult } from "./project-service";

export type { ServiceResult };

// Terminal statuses that stop polling
const TERMINAL: ProjectStatus[] = ["done", "failed", "cancelled"];

// -------------------------------------------------------------------------- //
// startRenderPolling                                                            //
// -------------------------------------------------------------------------- //

/**
 * Start polling a project's render status until it reaches a terminal state.
 *
 * Coordinates:
 *   - HTTP polling via getProjectStatus()
 *   - useRenderStore progress updates on every tick
 *   - useProjectStore status sync
 *   - Auto-fetches results when status = "done"
 *
 * @param projectId - UUID of the project to track
 * @returns ServiceResult with the final ProjectStatusResponse
 */
export async function startRenderPolling(
  projectId: string
): Promise<ServiceResult<ProjectStatusResponse>> {
  const { useRenderStore, useProjectStore } = await import("@/store");

  const renderState = useRenderStore.getState();
  if (renderState.isPolling && renderState.pollingProjectId === projectId) {
    return { success: false, error: "Already polling this project" };
  }

  useRenderStore.getState().resetForNewProject(projectId);
  useRenderStore.getState().startPolling(projectId);

  const startedAt   = Date.now();
  let lastStatus: ProjectStatusResponse | null = null;
  let consecutiveErrors = 0;
  const MAX_CONSECUTIVE_ERRORS = 5;

  return new Promise<ServiceResult<ProjectStatusResponse>>((resolve) => {
    const tick = async () => {
      // Check if polling was externally stopped
      if (!useRenderStore.getState().isPolling) {
        resolve({
          success: true,
          data:    lastStatus ?? { id: projectId, status: "cancelled" as ProjectStatus,
            updatedAt: new Date().toISOString(), errorMessage: null,
            queuePosition: null, videoUrl: null, thumbnailUrl: null,
            processingTimeSeconds: null },
        });
        return;
      }

      // Timeout guard
      if (Date.now() - startedAt > STATUS_POLL_MAX_DURATION_MS) {
        useRenderStore.getState().stopPolling();
        useRenderStore.getState().setRenderError(
          "Video generation is taking longer than expected. Please refresh the page.",
          false
        );
        resolve({
          success: false,
          error:   "Polling timeout — generation exceeded 10 minutes.",
        });
        return;
      }

      try {
        const status = await getProjectStatus(projectId);
        lastStatus       = status;
        consecutiveErrors = 0;

        // Update both stores
        useRenderStore.getState().updateFromStatusResponse(status);
        useProjectStore.getState().updateActiveProjectStatus(
          status.status,
          {
            videoUrl:     status.videoUrl     ?? undefined,
            thumbnailUrl: status.thumbnailUrl ?? undefined,
          } as Parameters<typeof useProjectStore.getState().updateActiveProjectStatus>[1]
        );

        if (TERMINAL.includes(status.status)) {
          useRenderStore.getState().stopPolling();

          if (status.status === "done") {
            // Fire-and-forget result fetch — don't block the resolve
            fetchRenderResults(projectId).catch(() => {
              /* non-fatal — results page can retry */
            });
          }

          resolve({ success: true, data: status });
          return;
        }
      } catch (error) {
        consecutiveErrors++;
        const err = error as ApiError;

        if (consecutiveErrors >= MAX_CONSECUTIVE_ERRORS) {
          useRenderStore.getState().stopPolling();
          useRenderStore.getState().setPollingError(
            err.detail ?? "Lost connection to server. Please refresh.",
            true
          );
          resolve({
            success: false,
            error:   "Too many consecutive polling errors — stopping.",
          });
          return;
        }

        useRenderStore.getState().setPollingError(
          err.detail ?? "Network error — retrying…",
          false
        );
      }

      setTimeout(tick, STATUS_POLL_INTERVAL_MS);
    };

    setTimeout(tick, 0);
  });
}

// -------------------------------------------------------------------------- //
// stopRenderPolling                                                             //
// -------------------------------------------------------------------------- //

/**
 * Manually stop the render polling loop.
 * Call when navigating away from the studio or project page.
 */
export async function stopRenderPolling(): Promise<void> {
  const { useRenderStore } = await import("@/store");
  useRenderStore.getState().stopPolling();
}

// -------------------------------------------------------------------------- //
// fetchRenderResults                                                            //
// -------------------------------------------------------------------------- //

/**
 * Fetch all render results for a completed project and store them.
 * Called automatically by startRenderPolling; can also be called manually
 * when loading a completed project page.
 *
 * Fetches in parallel: RenderingResult + DeliveryResult (required) +
 * QualityReport (best-effort — may not exist for auto-approved jobs).
 *
 * @param projectId - UUID of the completed project
 * @returns ServiceResult with all three result objects
 */
export async function fetchRenderResults(
  projectId: string
): Promise<
  ServiceResult<{
    renderingResult: RenderingResult;
    qualityReport:   QualityReport | null;
    deliveryResult:  DeliveryResult;
  }>
> {
  const { useRenderStore } = await import("@/store");

  try {
    const [renderSettled, deliverySettled, qualitySettled] =
      await Promise.allSettled([
        getRenderingResult(projectId),
        getDeliveryResult(projectId),
        getQualityReport(projectId),
      ]);

    if (
      renderSettled.status  === "rejected" ||
      deliverySettled.status === "rejected"
    ) {
      const err =
        renderSettled.status === "rejected"
          ? renderSettled.reason
          : (deliverySettled as PromiseRejectedResult).reason;
      return {
        success: false,
        error:   (err as ApiError).detail ?? "Failed to load video results. Please refresh.",
      };
    }

    const rendering = (renderSettled  as PromiseFulfilledResult<RenderingResult>).value;
    const delivery  = (deliverySettled as PromiseFulfilledResult<DeliveryResult>).value;
    const quality   =
      qualitySettled.status === "fulfilled" ? qualitySettled.value : null;

    useRenderStore.getState().setRenderingResult(rendering);
    useRenderStore.getState().setDeliveryResult(delivery);
    if (quality) useRenderStore.getState().setQualityReport(quality);

    return {
      success: true,
      data:    { renderingResult: rendering, qualityReport: quality, deliveryResult: delivery },
    };
  } catch (error) {
    const err = error as ApiError;
    return { success: false, error: err.detail ?? "Failed to load video results." };
  }
}

// -------------------------------------------------------------------------- //
// refreshProjectStatus                                                          //
// -------------------------------------------------------------------------- //

/**
 * One-shot status refresh for when a user returns to the page.
 * Updates render store and project store.
 * If status is "done" and results are not loaded, fetches them too.
 *
 * @param projectId - UUID of project to refresh
 * @returns ServiceResult with current status
 */
export async function refreshProjectStatus(
  projectId: string
): Promise<ServiceResult<ProjectStatusResponse>> {
  const { useRenderStore, useProjectStore } = await import("@/store");

  try {
    const status = await getProjectStatus(projectId);

    useRenderStore.getState().updateFromStatusResponse(status);
    useProjectStore.getState().updateActiveProjectStatus(
      status.status,
      {
        videoUrl:     status.videoUrl     ?? undefined,
        thumbnailUrl: status.thumbnailUrl ?? undefined,
      } as Parameters<typeof useProjectStore.getState().updateActiveProjectStatus>[1]
    );

    if (
      status.status === "done" &&
      !useRenderStore.getState().deliveryResult
    ) {
      await fetchRenderResults(projectId);
    }

    return { success: true, data: status };
  } catch (error) {
    const err = error as ApiError;
    return {
      success: false,
      error:   err.detail ?? "Failed to refresh project status.",
    };
  }
}

// -------------------------------------------------------------------------- //
// fetchSubtitlesForStudio                                                       //
// -------------------------------------------------------------------------- //

/**
 * Fetch and parse subtitle data for the studio player.
 * Checks subscription tier before fetching.
 *
 * @param projectId - UUID of the project
 * @param format - "srt" or "vtt" (default: "vtt")
 * @returns ServiceResult with parsed SubtitleData
 */
export async function fetchSubtitlesForStudio(
  projectId: string,
  format: "srt" | "vtt" = "vtt"
): Promise<
  ServiceResult<ReturnType<typeof parseSubtitleContent>>
> {
  const { useSubscriptionStore } = await import("@/store");

  const subtitleAllowed =
    useSubscriptionStore.getState().subscription?.features.subtitleDownload ??
    false;

  if (!subtitleAllowed) {
    return {
      success: false,
      error:   "Subtitle download requires a Premium subscription.",
    };
  }

  try {
    const rawContent = await getSubtitles(projectId, format);
    const parsed     = parseSubtitleContent(rawContent);
    return { success: true, data: parsed };
  } catch (error) {
    const err = error as ApiError;
    return { success: false, error: err.detail ?? "Failed to load subtitles." };
  }
}

// -------------------------------------------------------------------------- //
// getSceneSignedUrl                                                             //
// -------------------------------------------------------------------------- //

/**
 * Get a time-limited signed URL for streaming a specific scene's video.
 *
 * @param projectId  - UUID of the project
 * @param sceneIndex - 0-based scene index
 * @returns ServiceResult with the signed URL string
 */
export async function getSceneSignedUrl(
  projectId: string,
  sceneIndex: number
): Promise<ServiceResult<{ signedUrl: string; expiresAt: string }>> {
  try {
    const meta = await getSceneVideoUrl(projectId, sceneIndex);
    return {
      success: true,
      data:    { signedUrl: meta.signedUrl, expiresAt: meta.signedExpiry },
    };
  } catch (error) {
    const err = error as ApiError;
    return {
      success: false,
      error:   err.isNotFound
        ? "This scene has not been rendered yet."
        : (err.detail ?? "Failed to load scene video."),
    };
  }
}
