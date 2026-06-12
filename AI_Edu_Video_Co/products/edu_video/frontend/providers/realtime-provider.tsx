"use client";

/**
 * realtime-provider.tsx
 * Real-time WebSocket provider for live project status updates.
 * Scoped to a single active project — connect when on studio or project page,
 * disconnect when navigating away.
 *
 * Graceful degradation: if WebSocket is unavailable or disabled,
 * the app falls back to polling via useRenderProgress hook.
 */

import {
  createContext,
  useContext,
  useEffect,
  useRef,
  useCallback,
  useState,
  type ReactNode,
} from "react";
import { getWebSocketUrl } from "@/lib/api/render-api";
import { FEATURES } from "@/lib/constants";
import type { WebSocketEvent, ProjectStatus } from "@/types";

// -------------------------------------------------------------------------- //
// Types                                                                         //
// -------------------------------------------------------------------------- //

export type RealtimeStatus =
  | "idle"
  | "connecting"
  | "connected"
  | "reconnecting"
  | "disconnected"
  | "error"
  | "disabled";

export type RealtimeContextValue = {
  /** Current WebSocket connection status. */
  status:      RealtimeStatus;
  /** True if receiving live events. */
  isConnected: boolean;
  /** True if WebSocket feature is disabled via feature flag. */
  isDisabled:  boolean;
  /** Manually close the connection (e.g. when video finishes). */
  disconnect:  () => void;
  /** Manually reconnect (e.g. after user action). */
  reconnect:   () => void;
  /** The project ID currently being tracked. */
  projectId:   string | null;
};

// -------------------------------------------------------------------------- //
// Constants                                                                     //
// -------------------------------------------------------------------------- //

const MAX_RETRIES           = 5;
const BASE_RECONNECT_DELAY  = 1_000;  // ms
const HEARTBEAT_INTERVAL    = 30_000; // ms
const TERMINAL_STATUSES: ProjectStatus[] = ["done", "failed", "cancelled"];

// -------------------------------------------------------------------------- //
// Context                                                                       //
// -------------------------------------------------------------------------- //

const RealtimeContext = createContext<RealtimeContextValue | null>(null);

// -------------------------------------------------------------------------- //
// Provider                                                                      //
// -------------------------------------------------------------------------- //

type RealtimeProviderProps = {
  children:  ReactNode;
  /**
   * UUID of the project to track.
   * Pass null to keep the provider mounted but disconnected.
   */
  projectId: string | null;
  /**
   * Whether the project is still in an active processing state.
   * Set to false once terminal status is reached to avoid reconnecting.
   */
  active?:   boolean;
};

/**
 * WebSocket real-time update provider for a single active project.
 *
 * Place in the (studio) layout or project detail page layout.
 * Child components receive live status events via the render store.
 *
 * @example
 *   // app/(studio)/studio/[project_id]/layout.tsx
 *   <RealtimeProvider projectId={projectId} active={isActiveStatus}>
 *     {children}
 *   </RealtimeProvider>
 */
export function RealtimeProvider({
  children,
  projectId,
  active = true,
}: RealtimeProviderProps) {
  const [status, setStatus]   = useState<RealtimeStatus>(
    FEATURES.websocket ? "idle" : "disabled"
  );

  const wsRef           = useRef<WebSocket | null>(null);
  const retriesRef      = useRef(0);
  const heartbeatRef    = useRef<ReturnType<typeof setInterval> | null>(null);
  const shouldConnRef   = useRef(true);
  const projectIdRef    = useRef(projectId);

  // Keep ref in sync so callbacks always see latest projectId
  useEffect(() => { projectIdRef.current = projectId; }, [projectId]);

  // ---------------------------------------------------------------- //
  // Store helpers (lazy imported to avoid circular deps)              //
  // ---------------------------------------------------------------- //

  const applyEvent = useCallback(async (event: WebSocketEvent) => {
    const { useRenderStore, useProjectStore } = await import("@/store");
    useRenderStore.getState().applyWebSocketEvent(event);

    if (event.type === "status_update") {
      const newStatus = event.newStatus as ProjectStatus;
      useProjectStore.getState().updateActiveProjectStatus(newStatus, {
        videoUrl: event.videoUrl ?? undefined,
      });
    }
  }, []);

  // ---------------------------------------------------------------- //
  // Heartbeat                                                          //
  // ---------------------------------------------------------------- //

  const stopHeartbeat = useCallback(() => {
    if (heartbeatRef.current) {
      clearInterval(heartbeatRef.current);
      heartbeatRef.current = null;
    }
  }, []);

  const startHeartbeat = useCallback((ws: WebSocket) => {
    stopHeartbeat();
    heartbeatRef.current = setInterval(() => {
      if (ws.readyState === WebSocket.OPEN) {
        ws.send(JSON.stringify({ type: "ping" }));
      }
    }, HEARTBEAT_INTERVAL);
  }, [stopHeartbeat]);

  // ---------------------------------------------------------------- //
  // Connection                                                         //
  // ---------------------------------------------------------------- //

  const connect = useCallback(() => {
    const pid = projectIdRef.current;
    if (!pid || !shouldConnRef.current || !FEATURES.websocket) return;

    setStatus("connecting");
    const url = getWebSocketUrl(pid);
    const ws  = new WebSocket(url);
    wsRef.current = ws;

    ws.onopen = () => {
      retriesRef.current = 0;
      setStatus("connected");
      startHeartbeat(ws);
    };

    ws.onmessage = (evt) => {
      try {
        const event = JSON.parse(evt.data as string) as WebSocketEvent;

        // Stop reconnecting if project reached terminal state
        if (
          event.type === "status_update" &&
          TERMINAL_STATUSES.includes(event.newStatus as ProjectStatus)
        ) {
          shouldConnRef.current = false;
        }

        applyEvent(event).catch(console.error);
      } catch {
        // Ignore malformed frames
      }
    };

    ws.onclose = (evt) => {
      stopHeartbeat();

      if (!shouldConnRef.current || evt.wasClean) {
        setStatus("disconnected");
        return;
      }

      if (retriesRef.current < MAX_RETRIES) {
        setStatus("reconnecting");
        const delay = BASE_RECONNECT_DELAY * Math.pow(2, retriesRef.current);
        retriesRef.current++;
        setTimeout(connect, delay);
      } else {
        setStatus("error");
      }
    };

    ws.onerror = () => {
      stopHeartbeat();
      setStatus("error");
    };
  }, [applyEvent, startHeartbeat, stopHeartbeat]);

  const disconnect = useCallback(() => {
    shouldConnRef.current = false;
    stopHeartbeat();
    if (wsRef.current) {
      wsRef.current.close(1000, "Deliberate disconnect");
      wsRef.current = null;
    }
    setStatus("disconnected");
  }, [stopHeartbeat]);

  const reconnect = useCallback(() => {
    disconnect();
    shouldConnRef.current = true;
    retriesRef.current    = 0;
    setTimeout(connect, 100);
  }, [disconnect, connect]);

  // ---------------------------------------------------------------- //
  // Effect: connect / disconnect on projectId or active changes       //
  // ---------------------------------------------------------------- //

  useEffect(() => {
    if (!projectId || !active || !FEATURES.websocket) {
      disconnect();
      return;
    }

    shouldConnRef.current = true;
    retriesRef.current    = 0;
    connect();

    return () => {
      shouldConnRef.current = false;
      stopHeartbeat();
      if (wsRef.current) {
        wsRef.current.close(1000, "Component unmounted");
        wsRef.current = null;
      }
    };
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [projectId, active]);

  // ---------------------------------------------------------------- //
  // Context value                                                      //
  // ---------------------------------------------------------------- //

  const value: RealtimeContextValue = {
    status,
    isConnected: status === "connected",
    isDisabled:  !FEATURES.websocket,
    disconnect,
    reconnect,
    projectId,
  };

  return (
    <RealtimeContext.Provider value={value}>
      {children}
    </RealtimeContext.Provider>
  );
}

// -------------------------------------------------------------------------- //
// Hook                                                                          //
// -------------------------------------------------------------------------- //

/**
 * Access the realtime connection context.
 * @throws Error if used outside RealtimeProvider.
 */
export function useRealtime(): RealtimeContextValue {
  const ctx = useContext(RealtimeContext);
  if (!ctx) throw new Error("useRealtime must be used within RealtimeProvider");
  return ctx;
}

/**
 * Check realtime connection status without throwing.
 * Returns null outside RealtimeProvider (e.g. pages without live updates).
 */
export function useRealtimeStatus(): RealtimeStatus | null {
  return useContext(RealtimeContext)?.status ?? null;
      }
