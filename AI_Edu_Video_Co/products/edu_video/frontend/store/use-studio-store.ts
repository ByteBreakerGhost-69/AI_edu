/**
 * use-studio-store.ts
 * Zustand store for the video studio editor.
 * Owns: current project, scene list, playback state, editor UI state.
 * Does NOT own: render progress (use-render-store.ts), subscription (use-subscription-store.ts).
 */

import { create } from "zustand";
import { devtools, subscribeWithSelector } from "zustand/middleware";
import type { Project, Scene, SceneSummary } from "@/types";

// -------------------------------------------------------------------------- //
// Types                                                                         //
// -------------------------------------------------------------------------- //

/** Playback state for the studio video player. */
export type PlaybackState = {
  isPlaying:       boolean;
  currentTime:     number;   // seconds
  duration:        number;   // seconds (0 until loaded)
  volume:          number;   // 0.0–1.0
  isMuted:         boolean;
  isFullscreen:    boolean;
  playbackRate:    number;   // 0.5 | 0.75 | 1.0 | 1.25 | 1.5 | 2.0
  showSubtitles:   boolean;
  activeSceneIndex: number;  // 0-based; -1 if none
};

/** Studio editor panel visibility and layout state. */
export type StudioLayout = {
  scriptSidebarOpen:   boolean;
  assetPanelOpen:      boolean;
  sceneInspectorOpen:  boolean;
  timelineExpanded:    boolean;
  activePanel: "script" | "assets" | "inspector" | null;
};

/** Studio store state shape. */
export type StudioState = {
  // Project data
  project:        Project | null;
  scenes:         Scene[];
  sceneSummaries: SceneSummary[];
  selectedSceneIndex: number | null;  // null = no scene selected

  // Playback
  playback: PlaybackState;

  // Layout
  layout: StudioLayout;

  // Loading / error state
  isLoadingProject: boolean;
  isLoadingScenes:  boolean;
  projectError:     string | null;

  // Auto-save
  isDirty:      boolean;
  lastSavedAt:  number | null;  // unix ms
};

/** Studio store actions. */
export type StudioActions = {
  // Project
  setProject:         (project: Project | null) => void;
  setScenes:          (scenes: Scene[]) => void;
  setSceneSummaries:  (summaries: SceneSummary[]) => void;
  updateScene:        (sceneIndex: number, patch: Partial<Scene>) => void;
  selectScene:        (sceneIndex: number | null) => void;
  setProjectError:    (error: string | null) => void;
  setLoadingProject:  (loading: boolean) => void;
  setLoadingScenes:   (loading: boolean) => void;

  // Playback
  setPlaying:         (playing: boolean) => void;
  setCurrentTime:     (time: number) => void;
  setDuration:        (duration: number) => void;
  setVolume:          (volume: number) => void;
  setMuted:           (muted: boolean) => void;
  setFullscreen:      (fullscreen: boolean) => void;
  setPlaybackRate:    (rate: number) => void;
  toggleSubtitles:    () => void;
  setActiveScene:     (sceneIndex: number) => void;

  // Layout
  toggleScriptSidebar:  () => void;
  toggleAssetPanel:     () => void;
  toggleSceneInspector: () => void;
  toggleTimeline:       () => void;
  setActivePanel:       (panel: StudioLayout["activePanel"]) => void;

  // Auto-save
  markDirty:   () => void;
  markSaved:   () => void;

  // Reset
  resetStudio: () => void;
};

// -------------------------------------------------------------------------- //
// Initial state                                                                 //
// -------------------------------------------------------------------------- //

const INITIAL_PLAYBACK: PlaybackState = {
  isPlaying:        false,
  currentTime:      0,
  duration:         0,
  volume:           1.0,
  isMuted:          false,
  isFullscreen:     false,
  playbackRate:     1.0,
  showSubtitles:    true,
  activeSceneIndex: -1,
};

const INITIAL_LAYOUT: StudioLayout = {
  scriptSidebarOpen:   true,
  assetPanelOpen:      false,
  sceneInspectorOpen:  false,
  timelineExpanded:    true,
  activePanel:         "script",
};

const INITIAL_STATE: StudioState = {
  project:             null,
  scenes:              [],
  sceneSummaries:      [],
  selectedSceneIndex:  null,
  playback:            INITIAL_PLAYBACK,
  layout:              INITIAL_LAYOUT,
  isLoadingProject:    false,
  isLoadingScenes:     false,
  projectError:        null,
  isDirty:             false,
  lastSavedAt:         null,
};

// -------------------------------------------------------------------------- //
// Store                                                                         //
// -------------------------------------------------------------------------- //

export const useStudioStore = create<StudioState & StudioActions>()(
  devtools(
    subscribeWithSelector((set, get) => ({
      ...INITIAL_STATE,

      // ------------------------------------------------------------------- //
      // Project actions                                                        //
      // ------------------------------------------------------------------- //

      setProject: (project) =>
        set({ project, projectError: null }, false, "setProject"),

      setScenes: (scenes) =>
        set({ scenes }, false, "setScenes"),

      setSceneSummaries: (sceneSummaries) =>
        set({ sceneSummaries }, false, "setSceneSummaries"),

      updateScene: (sceneIndex, patch) =>
        set(
          (s) => ({
            scenes: s.scenes.map((scene) =>
              scene.sceneIndex === sceneIndex
                ? { ...scene, ...patch }
                : scene
            ),
            isDirty: true,
          }),
          false,
          "updateScene"
        ),

      selectScene: (sceneIndex) =>
        set({ selectedSceneIndex: sceneIndex }, false, "selectScene"),

      setProjectError: (projectError) =>
        set({ projectError }, false, "setProjectError"),

      setLoadingProject: (isLoadingProject) =>
        set({ isLoadingProject }, false, "setLoadingProject"),

      setLoadingScenes: (isLoadingScenes) =>
        set({ isLoadingScenes }, false, "setLoadingScenes"),

      // ------------------------------------------------------------------- //
      // Playback actions                                                       //
      // ------------------------------------------------------------------- //

      setPlaying: (isPlaying) =>
        set(
          (s) => ({ playback: { ...s.playback, isPlaying } }),
          false,
          "setPlaying"
        ),

      setCurrentTime: (currentTime) =>
        set(
          (s) => ({ playback: { ...s.playback, currentTime } }),
          false,
          "setCurrentTime"
        ),

      setDuration: (duration) =>
        set(
          (s) => ({ playback: { ...s.playback, duration } }),
          false,
          "setDuration"
        ),

      setVolume: (volume) =>
        set(
          (s) => ({
            playback: {
              ...s.playback,
              volume: Math.min(1, Math.max(0, volume)),
              isMuted: volume === 0,
            },
          }),
          false,
          "setVolume"
        ),

      setMuted: (isMuted) =>
        set(
          (s) => ({ playback: { ...s.playback, isMuted } }),
          false,
          "setMuted"
        ),

      setFullscreen: (isFullscreen) =>
        set(
          (s) => ({ playback: { ...s.playback, isFullscreen } }),
          false,
          "setFullscreen"
        ),

      setPlaybackRate: (playbackRate) =>
        set(
          (s) => ({ playback: { ...s.playback, playbackRate } }),
          false,
          "setPlaybackRate"
        ),

      toggleSubtitles: () =>
        set(
          (s) => ({
            playback: {
              ...s.playback,
              showSubtitles: !s.playback.showSubtitles,
            },
          }),
          false,
          "toggleSubtitles"
        ),

      setActiveScene: (activeSceneIndex) =>
        set(
          (s) => ({ playback: { ...s.playback, activeSceneIndex } }),
          false,
          "setActiveScene"
        ),

      // ------------------------------------------------------------------- //
      // Layout actions                                                          //
      // ------------------------------------------------------------------- //

      toggleScriptSidebar: () =>
        set(
          (s) => ({
            layout: {
              ...s.layout,
              scriptSidebarOpen: !s.layout.scriptSidebarOpen,
              activePanel: !s.layout.scriptSidebarOpen ? "script" : null,
            },
          }),
          false,
          "toggleScriptSidebar"
        ),

      toggleAssetPanel: () =>
        set(
          (s) => ({
            layout: {
              ...s.layout,
              assetPanelOpen: !s.layout.assetPanelOpen,
              activePanel: !s.layout.assetPanelOpen ? "assets" : s.layout.activePanel,
            },
          }),
          false,
          "toggleAssetPanel"
        ),

      toggleSceneInspector: () =>
        set(
          (s) => ({
            layout: {
              ...s.layout,
              sceneInspectorOpen: !s.layout.sceneInspectorOpen,
              activePanel: !s.layout.sceneInspectorOpen ? "inspector" : s.layout.activePanel,
            },
          }),
          false,
          "toggleSceneInspector"
        ),

      toggleTimeline: () =>
        set(
          (s) => ({
            layout: {
              ...s.layout,
              timelineExpanded: !s.layout.timelineExpanded,
            },
          }),
          false,
          "toggleTimeline"
        ),

      setActivePanel: (activePanel) =>
        set(
          (s) => ({ layout: { ...s.layout, activePanel } }),
          false,
          "setActivePanel"
        ),

      // ------------------------------------------------------------------- //
      // Auto-save actions                                                      //
      // ------------------------------------------------------------------- //

      markDirty: () =>
        set({ isDirty: true }, false, "markDirty"),

      markSaved: () =>
        set({ isDirty: false, lastSavedAt: Date.now() }, false, "markSaved"),

      // ------------------------------------------------------------------- //
      // Reset                                                                   //
      // ------------------------------------------------------------------- //

      resetStudio: () =>
        set(INITIAL_STATE, false, "resetStudio"),
    })),
    { name: "EduVideo:Studio" }
  )
);

// -------------------------------------------------------------------------- //
// Selectors (memoised — use these instead of inline selectors)                 //
// -------------------------------------------------------------------------- //

/** Current project ID, or null. */
export const selectProjectId = (s: StudioState) => s.project?.id ?? null;

/** Currently selected scene object, or null. */
export const selectSelectedScene = (s: StudioState): Scene | null => {
  if (s.selectedSceneIndex === null) return null;
  return s.scenes.find((sc) => sc.sceneIndex === s.selectedSceneIndex) ?? null;
};

/** All scenes sorted by sceneIndex. */
export const selectSortedScenes = (s: StudioState): Scene[] =>
  [...s.scenes].sort((a, b) => a.sceneIndex - b.sceneIndex);

/** True if the project has a playable video. */
export const selectIsDelivered = (s: StudioState): boolean =>
  s.project?.status === "done" && s.project.videoUrl !== null;

/** Array of per-scene durations in order. */
export const selectSceneDurations = (s: StudioState): number[] =>
  [...s.scenes]
    .sort((a, b) => a.sceneIndex - b.sceneIndex)
    .map((sc) => sc.durationSeconds ?? 0);
