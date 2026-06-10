"use client";

/**
 * websocket-provider.tsx
 * React context provider for the studio WebSocket connection.
 * Manages one WebSocket per active project — automatically reconnects on drop.
 *
 * Usage:
 *   Wrap the studio layout with <WebSocketProvider projectId={projectId}>
 *   Access via useWebSocketContext() hook in child components.
 */

import React, {
  createContext,
  useContext,
  useEffect,
  useRef,
  useCallback,
} from "react";
import { getWebSocketUrl } from "@/lib/api/render-api";
import { useRenderStore } from "@/store/use-render-store";
import type { WebSocketEvent } from "@/types";

// -------------------------------------------------------------------------- //
// Context types                                                                 //
// -------------------------------------------------------------------------- //

export type WebSocketContextValue = {
  /** Current WebSocket readyState (0=CONNECTING, 1=OPEN, 2=CLOSING, 3=CLOSED) */
  readyState: number;
  /** True if the WebSocket is open and receiving messages. */
  isConnected: boolean;
  /** Manually close the WebSocket (e.g. on project completion). */
  disconnect: () => void;
  /** Manually reconnect (e.g. after user interaction). */
  reconnect: () => void;
};

const WebSocketContext = createContext<WebSocketContextValue | null>(null);

// -------------------------------------------------------------------------- //
// Constants                                                                     //
// -------------------------------------------------------------------------- //

const RECONNECT_ATTEMPTS = 5;
const RECONNECT_BASE_DELAY_MS = 1_000;
const HEARTBEAT_INTERVAL_MS = 30_000;

// -------------------------------------------------------------------------- //
// Provider                                                                      //
// -------------------------------------------------------------------------- //

type WebSocketProviderProps = {
  children: React.ReactNode;
  /**
   * Project ID to subscribe to.
   * When null, no WebSocket connection is made.
   * When it changes, the previous connection is closed and a new one opened.
   */
  projectId: string | null;
  /**
   * Whether the project is still actively processing.
   * When false, WebSocket is not opened (e.g. project is "done" or "failed").
   */
  active?: boolean;
};

/**
 * WebSocket provider for the video studio.
 * Place this in the (studio) layout — wraps all studio pages.
 *
 * @example
 *   // app/(studio)/layout.tsx
 *   <WebSocketProvider projectId={params.project_id} active={isActive}>
 *     {children}
 *   </WebSocketProvider>
 */
export function WebSocketProvider({
  children,
  projectId,
  active = true,
}: WebSocketProviderProps): React.ReactElement {
  const wsRef              = useRef<WebSocket | null>(null);
  const reconnectCountRef  = useRef(0);
  const heartbeatRef       = useRef<ReturnType<typeof setInterval> | null>(null);
  const shouldReconnectRef = useRef(true);

  const { setWsStatus, setWsJobId, applyWebSocketEvent } = useRenderStore();

  // ---------------------------------------------------------------- //
  // WebSocket lifecycle                                                //
  // ---------------------------------------------------------------- //

  const clearHeartbeat = useCallback(() => {
    if (heartbeatRef.current) {
      clearInterval(heartbeatRef.current);
      heartbeatRef.current = null;
    }
  }, []);

  const startHeartbeat = useCallback((ws: WebSocket) => {
    clearHeartbeat();
    heartbeatRef.current = setInterval(() => {
      if (ws.readyState === WebSocket.OPEN) {
        ws.send(JSON.stringify({ type: "ping" }));
      }
    }, HEARTBEAT_INTERVAL_MS);
  }, [clearHeartbeat]);

  const connect = useCallback(() => {
    if (!projectId || !active) return;

    const url = getWebSocketUrl(projectId);
    setWsStatus("connecting");
    setWsJobId(projectId);

    const ws = new WebSocket(url);
    wsRef.current = ws;

    ws.onopen = () => {
      reconnectCountRef.current = 0;
      setWsStatus("connected");
      startHeartbeat(ws);
    };

    ws.onmessage = (event) => {
      try {
        const data = JSON.parse(event.data as string) as WebSocketEvent;
        applyWebSocketEvent(data);
      } catch {
        // Ignore malformed frames
      }
    };

    ws.onclose = (event) => {
      clearHeartbeat();
      setWsStatus("disconnected");

      // Attempt reconnect if not deliberate close
      if (
        shouldReconnectRef.current &&
        !event.wasClean &&
        reconnectCountRef.current < RECONNECT_ATTEMPTS
      ) {
        const delay =
          RECONNECT_BASE_DELAY_MS * Math.pow(2, reconnectCountRef.current);
        reconnectCountRef.current++;
        setTimeout(connect, delay);
      }
    };

    ws.onerror = () => {
      clearHeartbeat();
      setWsStatus("error");
    };
  }, [projectId, active, setWsStatus, setWsJobId, applyWebSocketEvent, startHeartbeat, clearHeartbeat]);

  const disconnect = useCallback(() => {
    shouldReconnectRef.current = false;
    clearHeartbeat();
    if (wsRef.current) {
      wsRef.current.close(1000, "Deliberate disconnect");
      wsRef.current = null;
    }
    setWsStatus("disconnected");
  }, [clearHeartbeat, setWsStatus]);

  const reconnect = useCallback(() => {
    disconnect();
    shouldReconnectRef.current = true;
    reconnectCountRef.current  = 0;
    setTimeout(connect, 100);
  }, [disconnect, connect]);

  // ---------------------------------------------------------------- //
  // Effect: connect / disconnect on projectId or active change        //
  // ---------------------------------------------------------------- //

  useEffect(() => {
    if (!projectId || !active) {
      disconnect();
      return;
    }

    shouldReconnectRef.current = true;
    reconnectCountRef.current  = 0;
    connect();

    return () => {
      shouldReconnectRef.current = false;
      clearHeartbeat();
      if (wsRef.current) {
        wsRef.current.close(1000, "Component unmounted");
        wsRef.current = null;
      }
    };
  }, [projectId, active]); // eslint-disable-line react-hooks/exhaustive-deps

  // ---------------------------------------------------------------- //
  // Context value                                                      //
  // ---------------------------------------------------------------- //

  const readyState = wsRef.current?.readyState ?? WebSocket.CLOSED;

  const value: WebSocketContextValue = {
    readyState,
    isConnected: readyState === WebSocket.OPEN,
    disconnect,
    reconnect,
  };

  return (
    <WebSocketContext.Provider value={value}>
      {children}
    </WebSocketContext.Provider>
  );
}

// -------------------------------------------------------------------------- //
// Consumer hook                                                                 //
// -------------------------------------------------------------------------- //

/**
 * Access the WebSocket context in studio child components.
 * Must be used within a <WebSocketProvider> tree.
 *
 * @throws Error if used outside WebSocketProvider
 */
export function useWebSocketContext(): WebSocketContextValue {
  const ctx = useContext(WebSocketContext);
  if (!ctx) {
    throw new Error(
      "useWebSocketContext must be used within <WebSocketProvider>"
    );
  }
  return ctx;
}
