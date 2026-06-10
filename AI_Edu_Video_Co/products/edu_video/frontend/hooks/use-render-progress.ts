"use client";

/**
 * use-render-progress.ts
 * Hook that drives the render progress UI.
 * Polls project status AND subscribes to WebSocket events —
 * the two sources are reconciled into the render store.
 *
 * Polling is used as a reliable fallback when WebSocket drops.
 * WebSocket provides real-time updates when available.
 */

import { useEffect, useRef, useCallback } from "react";
import { useQuery } from "@tanstack/react-query";
import { getProjectStatus } from "@/lib/api/project-api";
import { getWebSocketUrl } from "@/lib/api/render-api";
import { useRenderStore } from "@/store/use-render-store";
import { useStudioStore } from "@/store/use-studio-store";
import type { ProjectStatus, WebSocketEvent } from "@/types";

// -------------------------------------------------------------------------- //
// Constants                                                                     //
// -------------------------------------------------------------------------- //

/** Active statuses that should trigger polling. */
const ACTIVE_STATUSES: ProjectStatus[] = [
  "queued",
  "orchestrating",
  "rendering",
];

/** Poll interval while project is active (ms). */
const POLL_INTERVAL_MS = 3_000;

/** Stop polling once project reaches one of these statuses. */
const TERMINAL_STATUSES: ProjectStatus[] = [
  "done", "failed", "cancelled",
];

// -------------------------------------------------------------------------- //
// Hook types                                                                     //
// -------------------------------------------------------------------------- //

export type RenderProgressHookReturn = {
  /** Overall render progress 0–100. */
  overallPercent: number;
  /** Current pipeline stage label. */
  stage: string | null;
  /** Human-readable progress message. */
  message: string;
  /** True if WebSocket is actively receiving events. */
  isLive: boolean;
  /** True if project has completed (done or failed). */
  isTerminal: boolean;
  /** True if project failed. */
  isFailed: boolean;
  /** Error message if failed. */
  errorMessage: string | null;
};

// -------------------------------------------------------------------------- //
// Hook                                                                           //
// -------------------------------------------------------------------------- //

/**
 * Manages render progress for an active project.
 * Combines WebSocket real-time updates with polling fallback.
 *
 * @param projectId - UUID of the project to track (null = inactive)
 *
 * @example
 *   const { overallPercent, stage, isLive } = useRenderProgress(projectId);
 */
export function useRenderProgress(
  projectId: string | null
): RenderProgressHookReturn {
  const wsRef             = useRef<WebSocket | null>(null);
  const retriesRef        = useRef(0);
  const MAX_WS_RETRIES    = 5;

  const {
    overallPercent,
    stage,
    currentMessage,
    wsStatus,
    renderError,
    setWsStatus,
    setWsJobId,
    applyWebSocketEvent,
    initSceneProgress,
    resetRenderState,
  } = useRenderStore();

  const { setProject, setLoadingProject } = useStudioStore();

  // ---------------------------------------------------------------- //
  // Status polling (fallback + initial load)                          //
  // ---------------------------------------------------------------- //

  const projectQuery = useQuery({
    queryKey:  ["project-status", projectId],
    queryFn:   () => getProjectStatus(projectId!),
    enabled:   Boolean(projectId),
    refetchInterval: (query) => {
      const status = query.state.data?.status;
      if (!status) return POLL_INTERVAL_MS;
      if (TERMINAL_STATUSES.includes(status)) return false;
      if (wsStatus === "connected") return false; // WS handles updates
      return POLL_INTERVAL_MS;
    },
    staleTime: 0, // Always re-fetch for status
  });

  // Sync poll results into studio store
  useEffect(() => {
    const data = projectQuery.data;
    if (!data) return;

    // Update project status in studio store
    setProject((prev) =>
      prev ? { ...prev, status: data.status, videoUrl: data.videoUrl ?? prev.videoUrl } : null
    );

    // When project transitions to rendering, initialise per-scene progress
    if (data.status === "rendering") {
      const sceneCount = useStudioStore.getState().scenes.length;
      if (sceneCount > 0) {
        initSceneProgress(sceneCount);
      }
    }
  }, [projectQuery.data, setProject, initSceneProgress]);

  // ---------------------------------------------------------------- //
  // WebSocket connection                                               //
  // ---------------------------------------------------------------- //

  const connectWs = useCallback(() => {
    if (!projectId) return;

    const url = getWebSocketUrl(projectId);
    setWsStatus("connecting");
    setWsJobId(projectId);

    const ws = new WebSocket(url);
    wsRef.current = ws;

    ws.onopen = () => {
      retriesRef.current = 0;
      setWsStatus("connected");
    };

    ws.onmessage = (evt) => {
      try {
        const event = JSON.parse(evt.data as string) as WebSocketEvent;
        applyWebSocketEvent(event);
      } catch {
        // Ignore malformed frames
      }
    };

    ws.onclose = (evt) => {
      setWsStatus("disconnected");
      // Reconnect on unexpected close while project is active
      const currentStatus = projectQuery.data?.status;
      const isActive = currentStatus && ACTIVE_STATUSES.includes(currentStatus);
      if (!evt.wasClean && isActive && retriesRef.current < MAX_WS_RETRIES) {
        const delay = 1_000 * Math.pow(2, retriesRef.current);
        retriesRef.current++;
        setTimeout(connectWs, delay);
      }
    };

    ws.onerror = () => setWsStatus("error");
  }, [
    projectId,
    setWsStatus,
    setWsJobId,
    applyWebSocketEvent,
    projectQuery.data?.status,
  ]);

  // Open WS when projectId changes and project is in an active state
  useEffect(() => {
    const status = projectQuery.data?.status;
    const shouldConnect = Boolean(
      projectId && status && ACTIVE_STATUSES.includes(status)
    );

    if (shouldConnect) {
      connectWs();
    }

    return () => {
      wsRef.current?.close(1000, "Hook cleanup");
      wsRef.current = null;
    };
  }, [projectId, projectQuery.data?.status]); // eslint-disable-line react-hooks/exhaustive-deps

  // Close WS when project reaches terminal state
  useEffect(() => {
    const status = projectQuery.data?.status;
    if (status && TERMINAL_STATUSES.includes(status)) {
      wsRef.current?.close(1000, "Project completed");
      wsRef.current = null;
      setWsStatus("disconnected");
    }
  }, [projectQuery.data?.status, setWsStatus]);

  // Reset render state when projectId changes
  useEffect(() => {
    return () => {
      resetRenderState();
    };
  }, [projectId, resetRenderState]);

  // ---------------------------------------------------------------- //
  // Derived values                                                     //
  // ---------------------------------------------------------------- //

  const status     = projectQuery.data?.status;
  const isTerminal = Boolean(status && TERMINAL_STATUSES.includes(status));
  const isFailed   = status === "failed";

  return {
    overallPercent,
    stage,
    message:      currentMessage || projectQuery.data?.status ?? "",
    isLive:       wsStatus === "connected",
    isTerminal,
    isFailed,
    errorMessage: renderError ?? projectQuery.data?.errorMessage ?? null,
  };
    }
