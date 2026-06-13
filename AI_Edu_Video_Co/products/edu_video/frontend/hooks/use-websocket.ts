"use client";

/**
 * use-websocket.ts
 * Low-level WebSocket hook for direct connection management.
 * Use for WebSocket connections outside the studio context,
 * or for testing and admin real-time features.
 *
 * For studio render tracking, prefer useRenderProgress() which
 * combines polling + the realtime-provider context automatically.
 */

import { useEffect, useRef, useCallback, useState } from "react";
import type { WebSocketEvent } from "@/types";

// -------------------------------------------------------------------------- //
// Types                                                                        //
// -------------------------------------------------------------------------- //

export type WsReadyState = 0 | 1 | 2 | 3;

export type UseWebSocketOptions = {
  /** Called when connection opens. */
  onOpen?:         () => void;
  /** Called on every parsed WebSocket event. */
  onMessage?:      (event: WebSocketEvent) => void;
  /** Called on connection error (before close). */
  onError?:        (event: Event) => void;
  /** Called when connection closes. */
  onClose?:        (event: CloseEvent) => void;
  /** Auto-reconnect on unexpected close (default: true). */
  autoReconnect?:  boolean;
  /** Max reconnect attempts (default: 5). */
  maxRetries?:     number;
};

export type UseWebSocketReturn = {
  readyState:  WsReadyState;
  isConnected: boolean;
  disconnect:  () => void;
  reconnect:   () => void;
  /** Send a string or serialisable object. No-op if not connected. */
  send:        (data: string | Record<string, unknown>) => void;
};

const MAX_RETRIES_DEFAULT      = 5;
const BASE_RECONNECT_DELAY_MS  = 1_000;

// -------------------------------------------------------------------------- //
// useWebSocket                                                                //
// -------------------------------------------------------------------------- //

/**
 * Generic WebSocket hook with auto-reconnect and typed event parsing.
 *
 * @param url     - WebSocket URL (null = no connection)
 * @param options - Callbacks and reconnect configuration
 * @returns Connection state and imperative controls
 *
 * @example
 *   const { isConnected, send } = useWebSocket(wsUrl, {
 *     onMessage: (event) => applyEvent(event),
 *     autoReconnect: true,
 *   });
 */
export function useWebSocket(
  url:     string | null,
  options: UseWebSocketOptions = {}
): UseWebSocketReturn {
  const {
    onOpen,
    onMessage,
    onError,
    onClose,
    autoReconnect = true,
    maxRetries    = MAX_RETRIES_DEFAULT,
  } = options;

  const [readyState, setReadyState] = useState<WsReadyState>(WebSocket.CLOSED as WsReadyState);

  const wsRef             = useRef<WebSocket | null>(null);
  const retriesRef        = useRef(0);
  const shouldConnectRef  = useRef(true);
  const urlRef            = useRef(url);

  // Keep url ref fresh so reconnect callback sees latest URL
  useEffect(() => { urlRef.current = url; }, [url]);

  const connect = useCallback(() => {
    const wsUrl = urlRef.current;
    if (!wsUrl || !shouldConnectRef.current) return;

    setReadyState(WebSocket.CONNECTING as WsReadyState);
    const ws = new WebSocket(wsUrl);
    wsRef.current = ws;

    ws.onopen = () => {
      retriesRef.current = 0;
      setReadyState(WebSocket.OPEN as WsReadyState);
      onOpen?.();
    };

    ws.onmessage = (evt) => {
      try {
        const parsed = JSON.parse(evt.data as string) as WebSocketEvent;
        onMessage?.(parsed);
      } catch {
        // Skip unparseable frames (pong responses, plain-text pings)
      }
    };

    ws.onerror = (evt) => {
      onError?.(evt);
    };

    ws.onclose = (evt) => {
      setReadyState(WebSocket.CLOSED as WsReadyState);
      onClose?.(evt);

      if (
        autoReconnect &&
        shouldConnectRef.current &&
        !evt.wasClean &&
        retriesRef.current < maxRetries
      ) {
        const delay = BASE_RECONNECT_DELAY_MS * Math.pow(2, retriesRef.current);
        retriesRef.current++;
        setTimeout(connect, delay);
      }
    };
  }, [onOpen, onMessage, onError, onClose, autoReconnect, maxRetries]);

  // Connect / disconnect when url changes
  useEffect(() => {
    if (!url) {
      wsRef.current?.close(1000, "URL removed");
      wsRef.current = null;
      setReadyState(WebSocket.CLOSED as WsReadyState);
      return;
    }

    shouldConnectRef.current = true;
    retriesRef.current = 0;
    connect();

    return () => {
      shouldConnectRef.current = false;
      wsRef.current?.close(1000, "Component unmounted");
      wsRef.current = null;
    };
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [url]);

  const disconnect = useCallback(() => {
    shouldConnectRef.current = false;
    wsRef.current?.close(1000, "Deliberate disconnect");
    wsRef.current = null;
    setReadyState(WebSocket.CLOSED as WsReadyState);
  }, []);

  const reconnect = useCallback(() => {
    disconnect();
    shouldConnectRef.current = true;
    retriesRef.current = 0;
    setTimeout(connect, 100);
  }, [disconnect, connect]);

  const send = useCallback((data: string | Record<string, unknown>) => {
    if (wsRef.current?.readyState !== WebSocket.OPEN) return;
    wsRef.current.send(
      typeof data === "string" ? data : JSON.stringify(data)
    );
  }, []);

  return {
    readyState,
    isConnected: readyState === WebSocket.OPEN,
    disconnect,
    reconnect,
    send,
  };
        }
