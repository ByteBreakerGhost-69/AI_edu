"use client";

/**
 * use-render-progress.ts
 * Tracks render pipeline progress via HTTP polling + WebSocket override.
 * The most stateful hook — manages the full active-rendering lifecycle.
 */

import { useEffect, useRef, useCallback } from "react";
import {
  startRenderPolling,
  refreshProjectStatus,
  stopRenderPolling,
} from "@/services/render-service";
import {
  useRenderStore,
  selectRenderProgress,
  selectRenderError,
  selectRenderResults,
  selectIsRenderComplete,
  selectIsVideoReady,
  selectElapsedSeconds,
} from "@/store";
import { toast } from "@/providers";
import type { ProjectStatus } from "@/types";

// -------------------------------------------------------------------------- //
// useRenderProgress                                                            //
// -------------------------------------------------------------------------- //

type UseRenderProgressOptions = {
  /** Auto-start polling when projectId is provided (default: true). */
  autoStart?:      boolean;
  /** Called on every status transition. */
  onStatusChange?: (status: ProjectStatus) => void;
  /** Called when video is ready for playback. */
  onVideoReady?:   (videoUrl: string) => void;
  /** Called on fatal render error. */
  onError?:        (message: string) => void;
};

/**
 * Track rendering progress for an active project.
 *
 * Strategy:
 *   1. Start HTTP polling via render-service (every 3 s)
 *   2. Page visibility API pauses polling while tab is hidden; catches up on return
 *   3. Terminal status (done/failed/cancelled) stops polling automatically
 *   4. Results fetched automatically when status = "done"
 *
 * @param projectId - UUID of project to track, or null to skip
 * @param options   - Callbacks and autoStart flag
 *
 * @example
 *   const {
 *     status, percent, message, isComplete,
 *     isVideoReady, videoUrl, qualityScore,
 *     error, elapsed, retry,
 *   } = useRenderProgress(projectId);
 */
export function useRenderProgress(
  projectId: string | null,
  options: UseRenderProgressOptions = {}
) {
  const {
    autoStart     = true,
    onStatusChange,
    onVideoReady,
    onError,
  } = options;

  const progress     = useRenderStore(selectRenderProgress);
  const renderError  = useRenderStore(selectRenderError);
  const results      = useRenderStore(selectRenderResults);
  const isComplete   = useRenderStore(selectIsRenderComplete);
  const isVideoReady = useRenderStore(selectIsVideoReady);
  const elapsed      = useRenderStore(selectElapsedSeconds);

  const prevStatusRef  = useRef<ProjectStatus | null>(null);
  const hasStartedRef  = useRef(false);

  const TERMINAL = new Set<ProjectStatus>(["done", "failed", "cancelled"]);

  // ---------------------------------------------------------------- //
  // Start polling                                                      //
  // ---------------------------------------------------------------- //

  useEffect(() => {
    if (!projectId || !autoStart)        return;
    if (hasStartedRef.current)           return;
    if (progress.status && TERMINAL.has(progress.status)) return;

    hasStartedRef.current = true;

    startRenderPolling(projectId).then((result) => {
      if (!result.success) {
        onError?.(result.error);
      }
    });

    return () => {
      stopRenderPolling();
    };
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [projectId, autoStart]);

  // ---------------------------------------------------------------- //
  // Status-change callbacks                                            //
  // ---------------------------------------------------------------- //

  useEffect(() => {
    if (!progress.status) return;
    if (progress.status === prevStatusRef.current) return;

    prevStatusRef.current = progress.status;
    onStatusChange?.(progress.status);

    if (progress.status === "failed" && renderError.error) {
      onError?.(renderError.error);
      toast.error("Video generation failed", { description: renderError.error });
    }
  }, [progress.status, renderError.error, onStatusChange, onError]);

  // ---------------------------------------------------------------- //
  // Video-ready callback                                               //
  // ---------------------------------------------------------------- //

  useEffect(() => {
    if (isVideoReady && results.deliveryResult?.publicVideoUrl) {
      onVideoReady?.(results.deliveryResult.publicVideoUrl);
    }
  }, [isVideoReady, results.deliveryResult, onVideoReady]);

  // ---------------------------------------------------------------- //
  // Page visibility — catch up after tab switch                       //
  // ---------------------------------------------------------------- //

  useEffect(() => {
    if (!projectId) return;

    const handleVisibility = () => {
      if (document.visibilityState === "visible" && !isComplete) {
        refreshProjectStatus(projectId).catch(console.error);
      }
    };

    document.addEventListener("visibilitychange", handleVisibility);
    return () => document.removeEventListener("visibilitychange", handleVisibility);
  }, [projectId, isComplete]);

  // ---------------------------------------------------------------- //
  // Retry                                                              //
  // ---------------------------------------------------------------- //

  const retry = useCallback(() => {
    if (!projectId) return;
    hasStartedRef.current = false;
    useRenderStore.getState().resetForNewProject(projectId);
    startRenderPolling(projectId).catch(console.error);
  }, [projectId]);

  return {
    status:          progress.status,
    percent:         progress.percent,
    message:         progress.message,
    queuePosition:   progress.queuePosition,
    isPolling:       progress.isPolling,
    isComplete,
    isVideoReady,
    elapsed,
    videoUrl:        results.deliveryResult?.publicVideoUrl    ?? null,
    thumbnailUrl:    results.deliveryResult?.publicThumbnailUrl ?? null,
    qualityScore:    results.qualityReport?.overallScore        ?? null,
    qualityPassed:   results.qualityReport?.passed              ?? null,
    renderingResult: results.renderingResult,
    deliveryResult:  results.deliveryResult,
    error:           renderError.error,
    isFatalError:    renderError.isFatal,
    retry,
  };
        }
