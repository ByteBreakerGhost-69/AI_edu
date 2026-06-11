/**
 * store/index.ts
 * Central re-export for all Zustand stores and their selectors.
 *
 * Usage:
 *   import { useProjectStore, selectActiveProject } from "@/store";
 *   import { useRenderStore, selectRenderProgress } from "@/store";
 */

// -------------------------------------------------------------------------- //
// Project store                                                                 //
// -------------------------------------------------------------------------- //

export { useProjectStore } from "./use-project-store";
export type { } from "./use-project-store"; // types inferred from create()

export {
  selectProjectList,
  selectProjectListStatus,
  selectPagination,
  selectActiveProject,
  selectCreateFlow,
  selectProjectFilters,
  selectProjectById,
  selectHasMorePages,
} from "./use-project-store";

// -------------------------------------------------------------------------- //
// Render store                                                                  //
// -------------------------------------------------------------------------- //

export { useRenderStore } from "./use-render-store";

export {
  selectRenderProgress,
  selectRenderError,
  selectRenderResults,
  selectIsRenderComplete,
  selectIsVideoReady,
  selectElapsedSeconds,
} from "./use-render-store";

// -------------------------------------------------------------------------- //
// Studio store                                                                  //
// -------------------------------------------------------------------------- //

export { useStudioStore, PLAYBACK_RATES } from "./use-studio-store";
export type { PlaybackRate } from "./use-studio-store";

export {
  selectPlayback,
  selectAudio,
  selectSubtitles,
  selectCurrentScene,
  selectSelectedScene,
  selectPanels,
  selectQuality,
  selectPlayerReady,
  selectSortedScenes,
  selectAutoSave,
} from "./use-studio-store";

// -------------------------------------------------------------------------- //
// Subscription store                                                            //
// -------------------------------------------------------------------------- //

export { useSubscriptionStore } from "./use-subscription-store";

export {
  selectTier,
  selectQuotaMeter,
  selectSubscription,
  selectBillingModals,
  selectIsQuotaExceeded,
  selectIsTrialing,
} from "./use-subscription-store";
