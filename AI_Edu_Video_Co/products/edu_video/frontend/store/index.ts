/**
 * store/index.ts
 * Central re-export for all Zustand stores.
 */

export { useStudioStore } from "./use-studio-store";
export type { StudioState, StudioActions, PlaybackState, StudioLayout } from "./use-studio-store";
export {
  selectProjectId,
  selectSelectedScene,
  selectSortedScenes,
  selectIsDelivered,
  selectSceneDurations,
} from "./use-studio-store";

export { useRenderStore } from "./use-render-store";
export type { RenderState, RenderActions, SceneProgress, WsStatus } from "./use-render-store";
export {
  selectCompletedSceneCount,
  selectAllScenesComplete,
  selectQualityPassed,
} from "./use-render-store";
