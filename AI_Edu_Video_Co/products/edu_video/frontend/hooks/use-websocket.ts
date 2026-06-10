"use client";

/**
 * use-websocket.ts
 * Low-level WebSocket hook for direct connection management.
 * Used by components that need WebSocket outside the studio context,
 * or for testing purposes.
 *
 * For studio use, prefer useWebSocketContext() from websocket-provider.tsx.
 */

import { useEffect, useRef, useCallback, useState } from "react";
import type { WebSocketEvent } from "@/types";

// -------------------------------------------------------------------------- //
// Types                                                                         //
// -------------------------------------------------------------------------- //

export type WebSocketHookOptions = {
  /** Called when connection opens. */
  onOpen?:    () => void;
  /** Called on every parsed message event. */
  onMessage?: (event: WebSocketEvent) => void;
  /** Called on connection error. */
  onError?:   (error: Event) => void;
  /** Called when connection closes. */
  onClose?:   (event: CloseEvent) => void;
  /** Auto-reconnect on unexpected close (default: true). */
  autoReconnect?: boolean;
  /** Max reconnect attempts (default: 5). */
  maxRetries?: number;
};

export type WebSocketHookReturn = {
  readyState:  number;
  isConnected: boolean;
  disconnect:  () => void;
  reconnect:   () => void;
  send:        (data: string | object) => void;
};

// -------------------------------------------------------------------------- //
// Hook                                                                          //
// -------------------------------------------------------------------------- //

const DEFAULT_MAX_RETRIES      = 5;
const BASE_RECONNECT_DELAY_MS  = 1_000;

/**
 * Generic WebSocket hook with auto-reconnect and message parsing.
 *
 * @param url - WebSocket URL (null = no connection)
 * @param options - Callbacks and reconnect config
 * @returns Connection state and control functions
 *
 * @example
 *   const { isConnected, disconnect } = useWebSocket(wsUrl, {
 *     onMessage: (event) => console.log(event),
 *     autoReconnect: true,
 *   });
 */
export function useWebSocket(
  url: string | null,
  options: WebSocketHookOptions = {}
): WebSocketHookReturn {
  const {
    onOpen,
    onMessage,
    onError,
    onClose,
    autoReconnect = true,
    maxRetries    = DEFAULT_MAX_RETRIES,
  } = options;

  const wsRef             = useRef<WebSocket | null>(null);
  const retriesRef        = useRef(0);
  const shouldConnectRef  = useRef(true);

  const [readyState, setReadyState] = useState<number>(WebSocket.CLOSED);

  const connect = useCallback(() => {
    if (!url || !shouldConnectRef.current) return;

    setReadyState(WebSocket.CONNECTING);
    const ws = new WebSocket(url);
    wsRef.current = ws;

    ws.onopen = () => {
      retriesRef.current = 0;
      setReadyState(WebSocket.OPEN);
      onOpen?.();
    };

    ws.onmessage = (evt) => {
      try {
        const parsed = JSON.parse(evt.data as string) as WebSocketEvent;
        onMessage?.(parsed);
      } catch {
        // Skip unparseable frames (e.g. pong responses)
      }
    };

    ws.onerror = (evt) => {
      onError?.(evt);
    };

    ws.onclose = (evt) => {
      setReadyState(WebSocket.CLOSED);
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
  }, [url, onOpen, onMessage, onError, onClose, autoReconnect, maxRetries]);

  useEffect(() => {
    if (!url) return;
    shouldConnectRef.current = true;
    retriesRef.current = 0;
    connect();

    return () => {
      shouldConnectRef.current = false;
      wsRef.current?.close(1000, "Component unmounted");
      wsRef.current = null;
    };
  }, [url]); // eslint-disable-line react-hooks/exhaustive-deps

  const disconnect = useCallback(() => {
    shouldConnectRef.current = false;
    wsRef.current?.close(1000, "Deliberate disconnect");
    wsRef.current = null;
    setReadyState(WebSocket.CLOSED);
  }, []);

  const reconnect = useCallback(() => {
    disconnect();
    shouldConnectRef.current = true;
    retriesRef.current = 0;
    setTimeout(connect, 100);
  }, [disconnect, connect]);

  const send = useCallback((data: string | object) => {
    if (wsRef.current?.readyState === WebSocket.OPEN) {
      wsRef.current.send(
        typeof data === "string" ? data : JSON.stringify(data)
      );
    }
  }, []);

  return {
    readyState,
    isConnected: readyState === WebSocket.OPEN,
    disconnect,
    reconnect,
    send,
  };
}
