/**
 * use-studio-store.ts
 * Video player, scene selection, subtitle display, and studio UI panel state.
 * The most interaction-heavy store — updated on every animation frame
 * during playback (currentTimeSeconds).
 */

import { create } from "zustand";
import { devtools, subscribeWithSelector } from "zustand/middleware";
import type { Scene, SubtitleCue, RendererType } from "@/types";

// -------------------------------------------------------------------------- //
// Valid playback rates                                                          //
// -------------------------------------------------------------------------- //

export const PLAYBACK_RATES = [0.5, 0.75, 1.0, 1.25, 1.5, 2.0] as const;
export type PlaybackRate = (typeof PLAYBACK_RATES)[number];

// -------------------------------------------------------------------------- //
// State + Actions types                                                         //
// -------------------------------------------------------------------------- //

type QualityOption = { label: string; index: number };

type StudioState = {
  // Video player
  isPlaying:            boolean;
  currentTimeSeconds:   number;
  durationSeconds:      number;
  volume:               number;          // 0.0–1.0
  isMuted:              boolean;
  playbackRate:         PlaybackRate;
  isFullscreen:         boolean;
  isBuffering:          boolean;
  hasError:             boolean;
  errorMessage:         string | null;

  // Quality
  currentQualityLabel:  string;
  availableQualities:   QualityOption[];

  // Subtitles
  subtitlesEnabled:     boolean;
  currentCue:           SubtitleCue | null;
  subtitleFontSize:     number;           // px

  // Scene navigation
  currentSceneIndex:    number;           // 0-based; scene currently playing
  scenes:               Scene[];
  selectedSceneIndex:   number | null;    // Scene selected in the inspector

  // Studio UI panels
  scriptPanelOpen:      boolean;
  assetPanelOpen:       boolean;
  inspectorPanelOpen:   boolean;
  timelineExpanded:     boolean;
  activePanel:          "script" | "assets" | "inspector" | null;

  // Auto-save
  isDirty:      boolean;
  lastSavedAt:  number | null;            // unix ms
};

type StudioActions = {
  // Player: playback
  setPlaying:       (playing: boolean) => void;
  setCurrentTime:   (seconds: number) => void;
  setDuration:      (seconds: number) => void;
  seekTo:           (seconds: number) => void;

  // Player: audio
  setVolume:        (volume: number) => void;
  toggleMute:       () => void;
  setMuted:         (muted: boolean) => void;

  // Player: other
  setPlaybackRate:  (rate: PlaybackRate) => void;
  setFullscreen:    (fs: boolean) => void;
  setBuffering:     (buffering: boolean) => void;
  setPlayerError:   (message: string | null) => void;

  // Quality
  setCurrentQuality:      (label: string) => void;
  setAvailableQualities:  (qualities: QualityOption[]) => void;

  // Subtitles
  toggleSubtitles:      () => void;
  setCurrentCue:        (cue: SubtitleCue | null) => void;
  setSubtitleFontSize:  (size: number) => void;

  // Scene navigation
  setCurrentSceneIndex:  (index: number) => void;
  setScenes:             (scenes: Scene[]) => void;
  selectScene:           (index: number | null) => void;
  /** Navigate to a scene — sets both currentSceneIndex and selectedSceneIndex. */
  goToScene:             (index: number) => void;

  // Panels
  toggleScriptPanel:    () => void;
  toggleAssetPanel:     () => void;
  toggleInspectorPanel: () => void;
  toggleTimeline:       () => void;
  setActivePanel:       (panel: StudioState["activePanel"]) => void;

  // Auto-save
  markDirty:   () => void;
  markSaved:   () => void;

  // Reset
  reset:             () => void;
  resetPlayer:       () => void;
};

// -------------------------------------------------------------------------- //
// Initial state                                                                 //
// -------------------------------------------------------------------------- //

const INITIAL_STATE: StudioState = {
  isPlaying:            false,
  currentTimeSeconds:   0,
  durationSeconds:      0,
  volume:               1.0,
  isMuted:              false,
  playbackRate:         1.0,
  isFullscreen:         false,
  isBuffering:          false,
  hasError:             false,
  errorMessage:         null,
  currentQualityLabel:  "Auto",
  availableQualities:   [],
  subtitlesEnabled:     true,
  currentCue:           null,
  subtitleFontSize:     20,
  currentSceneIndex:    0,
  scenes:               [],
  selectedSceneIndex:   null,
  scriptPanelOpen:      true,
  assetPanelOpen:       false,
  inspectorPanelOpen:   false,
  timelineExpanded:     true,
  activePanel:          "script",
  isDirty:              false,
  lastSavedAt:          null,
};

const PLAYER_RESET: Partial<StudioState> = {
  isPlaying:          false,
  currentTimeSeconds: 0,
  durationSeconds:    0,
  isBuffering:        false,
  hasError:           false,
  errorMessage:       null,
  currentCue:         null,
};

// -------------------------------------------------------------------------- //
// Store                                                                         //
// -------------------------------------------------------------------------- //

export const useStudioStore = create<StudioState & StudioActions>()(
  devtools(
    subscribeWithSelector((set, get) => ({
      ...INITIAL_STATE,

      // ------------------------------------------------------------------- //
      // Playback                                                               //
      // ------------------------------------------------------------------- //

      setPlaying: (isPlaying) =>
        set({ isPlaying }, false, "setPlaying"),

      setCurrentTime: (currentTimeSeconds) =>
        set({ currentTimeSeconds }, false, "setCurrentTime"),

      setDuration: (durationSeconds) =>
        set({ durationSeconds }, false, "setDuration"),

      seekTo: (seconds) =>
        set(
          (s) => ({
            currentTimeSeconds: Math.max(
              0,
              Math.min(seconds, s.durationSeconds)
            ),
          }),
          false,
          "seekTo"
        ),

      // ------------------------------------------------------------------- //
      // Audio                                                                  //
      // ------------------------------------------------------------------- //

      setVolume: (volume) =>
        set(
          { volume: Math.min(1, Math.max(0, volume)), isMuted: volume === 0 },
          false,
          "setVolume"
        ),

      toggleMute: () =>
        set((s) => ({ isMuted: !s.isMuted }), false, "toggleMute"),

      setMuted: (isMuted) =>
        set({ isMuted }, false, "setMuted"),

      // ------------------------------------------------------------------- //
      // Other player controls                                                  //
      // ------------------------------------------------------------------- //

      setPlaybackRate: (playbackRate) =>
        set({ playbackRate }, false, "setPlaybackRate"),

      setFullscreen: (isFullscreen) =>
        set({ isFullscreen }, false, "setFullscreen"),

      setBuffering: (isBuffering) =>
        set({ isBuffering }, false, "setBuffering"),

      setPlayerError: (message) =>
        set(
          { hasError: message !== null, errorMessage: message },
          false,
          "setPlayerError"
        ),

      // ------------------------------------------------------------------- //
      // Quality                                                                //
      // ------------------------------------------------------------------- //

      setCurrentQuality: (currentQualityLabel) =>
        set({ currentQualityLabel }, false, "setCurrentQuality"),

      setAvailableQualities: (availableQualities) =>
        set({ availableQualities }, false, "setAvailableQualities"),

      // ------------------------------------------------------------------- //
      // Subtitles                                                              //
      // ------------------------------------------------------------------- //

      toggleSubtitles: () =>
        set(
          (s) => ({ subtitlesEnabled: !s.subtitlesEnabled }),
          false,
          "toggleSubtitles"
        ),

      setCurrentCue: (currentCue) =>
        set({ currentCue }, false, "setCurrentCue"),

      setSubtitleFontSize: (subtitleFontSize) =>
        set(
          { subtitleFontSize: Math.min(40, Math.max(12, subtitleFontSize)) },
          false,
          "setSubtitleFontSize"
        ),

      // ------------------------------------------------------------------- //
      // Scene navigation                                                       //
      // ------------------------------------------------------------------- //

      setCurrentSceneIndex: (currentSceneIndex) =>
        set({ currentSceneIndex }, false, "setCurrentSceneIndex"),

      setScenes: (scenes) =>
        set({ scenes }, false, "setScenes"),

      selectScene: (selectedSceneIndex) =>
        set({ selectedSceneIndex }, false, "selectScene"),

      goToScene: (index) =>
        set(
          { currentSceneIndex: index, selectedSceneIndex: index },
          false,
          "goToScene"
        ),

      // ------------------------------------------------------------------- //
      // Panels                                                                 //
      // ------------------------------------------------------------------- //

      toggleScriptPanel: () =>
        set(
          (s) => ({
            scriptPanelOpen: !s.scriptPanelOpen,
            activePanel:     !s.scriptPanelOpen ? "script" : s.activePanel,
          }),
          false,
          "toggleScriptPanel"
        ),

      toggleAssetPanel: () =>
        set(
          (s) => ({
            assetPanelOpen: !s.assetPanelOpen,
            activePanel:    !s.assetPanelOpen ? "assets" : s.activePanel,
          }),
          false,
          "toggleAssetPanel"
        ),

      toggleInspectorPanel: () =>
        set(
          (s) => ({
            inspectorPanelOpen: !s.inspectorPanelOpen,
            activePanel:        !s.inspectorPanelOpen ? "inspector" : s.activePanel,
          }),
          false,
          "toggleInspectorPanel"
        ),

      toggleTimeline: () =>
        set(
          (s) => ({ timelineExpanded: !s.timelineExpanded }),
          false,
          "toggleTimeline"
        ),

      setActivePanel: (activePanel) =>
        set({ activePanel }, false, "setActivePanel"),

      // ------------------------------------------------------------------- //
      // Auto-save                                                              //
      // ------------------------------------------------------------------- //

      markDirty: () =>
        set({ isDirty: true }, false, "markDirty"),

      markSaved: () =>
        set({ isDirty: false, lastSavedAt: Date.now() }, false, "markSaved"),

      // ------------------------------------------------------------------- //
      // Reset                                                                  //
      // ------------------------------------------------------------------- //

      reset: () => set(INITIAL_STATE, false, "reset"),

      resetPlayer: () =>
        set(PLAYER_RESET, false, "resetPlayer"),
    })),
    { name: "EduVideo:Studio" }
  )
);

// -------------------------------------------------------------------------- //
// Selectors                                                                     //
// -------------------------------------------------------------------------- //

type S = StudioState & StudioActions;

/** Playback state for the video player controls bar. */
export const selectPlayback = (s: S) => ({
  isPlaying:          s.isPlaying,
  currentTimeSeconds: s.currentTimeSeconds,
  durationSeconds:    s.durationSeconds,
  playbackRate:       s.playbackRate,
  isFullscreen:       s.isFullscreen,
  isBuffering:        s.isBuffering,
});

/** Audio state. */
export const selectAudio = (s: S) => ({
  volume:  s.volume,
  isMuted: s.isMuted,
});

/** Subtitle state for the overlay component. */
export const selectSubtitles = (s: S) => ({
  enabled:  s.subtitlesEnabled,
  cue:      s.currentCue,
  fontSize: s.subtitleFontSize,
});

/** Currently playing scene object, or null if index is out of range. */
export const selectCurrentScene = (s: S): Scene | null =>
  s.scenes[s.currentSceneIndex] ?? null;

/** Scene selected in the inspector panel. */
export const selectSelectedScene = (s: S): Scene | null =>
  s.selectedSceneIndex !== null ? (s.scenes[s.selectedSceneIndex] ?? null) : null;

/** All panel visibility flags. */
export const selectPanels = (s: S) => ({
  scriptPanelOpen:    s.scriptPanelOpen,
  assetPanelOpen:     s.assetPanelOpen,
  inspectorPanelOpen: s.inspectorPanelOpen,
  timelineExpanded:   s.timelineExpanded,
  activePanel:        s.activePanel,
});

/** Quality selector data. */
export const selectQuality = (s: S) => ({
  current:   s.currentQualityLabel,
  available: s.availableQualities,
});

/** True if the player has a playable video loaded. */
export const selectPlayerReady = (s: S): boolean =>
  s.durationSeconds > 0 && !s.hasError;

/** Scenes array sorted by sceneIndex. */
export const selectSortedScenes = (s: S): Scene[] =>
  [...s.scenes].sort((a, b) => a.sceneIndex - b.sceneIndex);

/** Auto-save state. */
export const selectAutoSave = (s: S) => ({
  isDirty:     s.isDirty,
  lastSavedAt: s.lastSavedAt,
});
