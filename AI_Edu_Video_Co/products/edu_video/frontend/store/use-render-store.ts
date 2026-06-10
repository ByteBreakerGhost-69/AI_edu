/**
 * use-render-store.ts
 * Zustand store for render progress and quality check state.
 * Owns: WebSocket render events, per-scene progress, quality report.
 * Updated in real-time by use-render-progress.ts hook via WebSocket.
 */

import { create } from "zustand";
import { devtools } from "zustand/middleware";
import type {
  RenderProgressEvent,
  QualityReport,
  DeliveryResult,
  WebSocketEvent,
} from "@/types";

// -------------------------------------------------------------------------- //
// Types                                                                         //
// -------------------------------------------------------------------------- //

/** Per-scene render progress entry. */
export type SceneProgress = {
  sceneIndex: number;
  status: "pending" | "rendering" | "done" | "failed";
  progressPercent: number;   // 0–100
  rendererType:    string | null;
  errorMessage:    string | null;
};

/** WebSocket connection status. */
export type WsStatus =
  | "idle"         // Not yet connected
  | "connecting"   // WebSocket opening
  | "connected"    // Receiving events
  | "disconnected" // Clean close
  | "error";       // Failed or dropped

/** Render store state shape. */
export type RenderState = {
  // Connection
  wsStatus:    WsStatus;
  wsJobId:     string | null;

  // Overall progress
  stage:               string | null;   // current pipeline stage name
  overallPercent:      number;          // 0–100
  currentMessage:      string;
  lastEventAt:         number | null;   // unix ms

  // Per-scene progress
  sceneProgress:       SceneProgress[];
  totalScenes:         number;

  // Quality check
  qualityReport:       QualityReport | null;
  qualityCheckRunning: boolean;

  // Delivery
  deliveryResult:      DeliveryResult | null;

  // Error
  renderError: string | null;
  fatalError:  boolean;

  // Event history (last 50 events for debug panel)
  eventHistory: WebSocketEvent[];
};

/** Render store actions. */
export type RenderActions = {
  // WebSocket lifecycle
  setWsStatus:   (status: WsStatus) => void;
  setWsJobId:    (jobId: string | null) => void;

  // Progress updates (called from use-render-progress hook)
  applyProgressEvent:   (event: RenderProgressEvent) => void;
  applyWebSocketEvent:  (event: WebSocketEvent) => void;

  // Scene progress
  initSceneProgress:    (totalScenes: number) => void;
  updateSceneProgress:  (sceneIndex: number, patch: Partial<SceneProgress>) => void;

  // Quality check
  setQualityReport:      (report: QualityReport | null) => void;
  setQualityCheckRunning:(running: boolean) => void;

  // Delivery
  setDeliveryResult:    (result: DeliveryResult | null) => void;

  // Error
  setRenderError:  (error: string | null) => void;
  setFatalError:   (fatal: boolean) => void;

  // Reset
  resetRenderState: () => void;
};

// -------------------------------------------------------------------------- //
// Initial state                                                                 //
// -------------------------------------------------------------------------- //

const MAX_HISTORY = 50;

const INITIAL_STATE: RenderState = {
  wsStatus:            "idle",
  wsJobId:             null,
  stage:               null,
  overallPercent:      0,
  currentMessage:      "",
  lastEventAt:         null,
  sceneProgress:       [],
  totalScenes:         0,
  qualityReport:       null,
  qualityCheckRunning: false,
  deliveryResult:      null,
  renderError:         null,
  fatalError:          false,
  eventHistory:        [],
};

// -------------------------------------------------------------------------- //
// Store                                                                         //
// -------------------------------------------------------------------------- //

export const useRenderStore = create<RenderState & RenderActions>()(
  devtools(
    (set, get) => ({
      ...INITIAL_STATE,

      setWsStatus: (wsStatus) =>
        set({ wsStatus }, false, "setWsStatus"),

      setWsJobId: (wsJobId) =>
        set({ wsJobId }, false, "setWsJobId"),

      applyProgressEvent: (event) =>
        set(
          (s) => {
            const sceneProgress = [...s.sceneProgress];

            // Update per-scene entry if event references a specific scene
            if (event.currentScene !== null && event.currentScene !== undefined) {
              const idx = sceneProgress.findIndex(
                (p) => p.sceneIndex === event.currentScene
              );
              if (idx >= 0) {
                sceneProgress[idx] = {
                  ...sceneProgress[idx]!,
                  status: "rendering",
                  progressPercent: Math.min(
                    event.overallPercent,
                    sceneProgress[idx]!.progressPercent + 5
                  ),
                };
              }
            }

            const history = [
              event,
              ...s.eventHistory,
            ].slice(0, MAX_HISTORY) as WebSocketEvent[];

            return {
              stage:          event.stage,
              overallPercent: event.overallPercent,
              currentMessage: event.message,
              lastEventAt:    Date.now(),
              sceneProgress,
              eventHistory:   history,
            };
          },
          false,
          "applyProgressEvent"
        ),

      applyWebSocketEvent: (event) => {
        const { applyProgressEvent, setDeliveryResult, setRenderError, setFatalError } = get();

        if (event.type === "render_progress") {
          applyProgressEvent(event);
          return;
        }

        if (event.type === "status_update") {
          set(
            (s) => ({
              currentMessage: event.message,
              lastEventAt:    Date.now(),
              eventHistory:   [event, ...s.eventHistory].slice(0, MAX_HISTORY),
            }),
            false,
            "applyStatusUpdate"
          );
          return;
        }

        if (event.type === "error") {
          setRenderError(event.message);
          setFatalError(true);
          set(
            (s) => ({
              eventHistory: [event, ...s.eventHistory].slice(0, MAX_HISTORY),
            }),
            false,
            "applyErrorEvent"
          );
        }
      },

      initSceneProgress: (totalScenes) =>
        set(
          {
            totalScenes,
            sceneProgress: Array.from({ length: totalScenes }, (_, i) => ({
              sceneIndex:      i,
              status:          "pending",
              progressPercent: 0,
              rendererType:    null,
              errorMessage:    null,
            })),
          },
          false,
          "initSceneProgress"
        ),

      updateSceneProgress: (sceneIndex, patch) =>
        set(
          (s) => ({
            sceneProgress: s.sceneProgress.map((p) =>
              p.sceneIndex === sceneIndex ? { ...p, ...patch } : p
            ),
          }),
          false,
          "updateSceneProgress"
        ),

      setQualityReport: (qualityReport) =>
        set({ qualityReport }, false, "setQualityReport"),

      setQualityCheckRunning: (qualityCheckRunning) =>
        set({ qualityCheckRunning }, false, "setQualityCheckRunning"),

      setDeliveryResult: (deliveryResult) =>
        set({ deliveryResult }, false, "setDeliveryResult"),

      setRenderError: (renderError) =>
        set({ renderError }, false, "setRenderError"),

      setFatalError: (fatalError) =>
        set({ fatalError }, false, "setFatalError"),

      resetRenderState: () =>
        set(INITIAL_STATE, false, "resetRenderState"),
    }),
    { name: "EduVideo:Render" }
  )
);

// -------------------------------------------------------------------------- //
// Selectors                                                                     //
// -------------------------------------------------------------------------- //

/** Number of scenes that have completed rendering. */
export const selectCompletedSceneCount = (s: RenderState): number =>
  s.sceneProgress.filter((p) => p.status === "done").length;

/** True if every scene has status="done". */
export const selectAllScenesComplete = (s: RenderState): boolean =>
  s.totalScenes > 0 &&
  s.sceneProgress.every((p) => p.status === "done");

/** True if the quality report passed and has no critical issues. */
export const selectQualityPassed = (s: RenderState): boolean =>
  s.qualityReport?.passed === true;
