"use client";

/**
 * use-hotkeys.ts
 * Keyboard shortcut registry for the studio editor.
 * Supports modifier keys, input field exclusion, and dynamic enable/disable.
 */

import { useEffect, useRef, useCallback } from "react";

// -------------------------------------------------------------------------- //
// Types                                                                        //
// -------------------------------------------------------------------------- //

export type HotkeyModifiers = {
  ctrl?:  boolean;
  meta?:  boolean;  // Cmd on macOS
  shift?: boolean;
  alt?:   boolean;
};

export type HotkeyDefinition = {
  /** Key code string e.g. "KeyK", "Space", "ArrowLeft" */
  key:         string;
  modifiers?:  HotkeyModifiers;
  /** Called when key combo fires. */
  handler:     (event: KeyboardEvent) => void;
  /** Description for keyboard shortcut legend. */
  description: string;
  /** Whether to call event.preventDefault() (default: true). */
  preventDefault?: boolean;
  /** Whether this hotkey is currently active (default: true). */
  enabled?:    boolean;
};

// -------------------------------------------------------------------------- //
// Input element detection                                                      //
// -------------------------------------------------------------------------- //

function isTypingTarget(target: EventTarget | null): boolean {
  if (!(target instanceof HTMLElement)) return false;
  const tag = target.tagName.toLowerCase();
  return (
    tag === "input" ||
    tag === "textarea" ||
    tag === "select" ||
    target.isContentEditable
  );
}

function modifiersMatch(
  event: KeyboardEvent,
  mods: HotkeyModifiers = {}
): boolean {
  return (
    Boolean(mods.ctrl)  === event.ctrlKey  &&
    Boolean(mods.meta)  === event.metaKey  &&
    Boolean(mods.shift) === event.shiftKey &&
    Boolean(mods.alt)   === event.altKey
  );
}

// -------------------------------------------------------------------------- //
// useHotkeys                                                                  //
// -------------------------------------------------------------------------- //

/**
 * Register one or more keyboard shortcuts.
 * Automatically de-registers on unmount.
 * Ignores events when focus is inside text inputs.
 *
 * @param hotkeys - Array of hotkey definitions
 * @param options - Global options
 *
 * @example
 *   useHotkeys([
 *     {
 *       key: "Space",
 *       handler: () => togglePlay(),
 *       description: "Play / Pause",
 *     },
 *     {
 *       key: "KeyK",
 *       modifiers: { ctrl: true },
 *       handler: () => seek(0),
 *       description: "Go to start",
 *     },
 *   ]);
 */
export function useHotkeys(
  hotkeys: HotkeyDefinition[],
  options: {
    /** Allow firing inside inputs (default: false). */
    allowInInputs?: boolean;
    /** Target element (default: document). */
    target?:        EventTarget | null;
  } = {}
) {
  const { allowInInputs = false, target } = options;
  const hotkeysRef = useRef<HotkeyDefinition[]>(hotkeys);

  // Keep ref fresh without re-attaching listener
  useEffect(() => {
    hotkeysRef.current = hotkeys;
  }, [hotkeys]);

  const handleKeyDown = useCallback(
    (event: Event) => {
      const kbEvent = event as KeyboardEvent;

      if (!allowInInputs && isTypingTarget(kbEvent.target)) return;

      for (const hk of hotkeysRef.current) {
        if (hk.enabled === false) continue;
        if (kbEvent.code !== hk.key)  continue;
        if (!modifiersMatch(kbEvent, hk.modifiers)) continue;

        if (hk.preventDefault !== false) kbEvent.preventDefault();
        hk.handler(kbEvent);
        return; // First match wins
      }
    },
    [allowInInputs]
  );

  useEffect(() => {
    const el = target ?? document;
    if (!el) return;

    el.addEventListener("keydown", handleKeyDown);
    return () => el.removeEventListener("keydown", handleKeyDown);
  }, [handleKeyDown, target]);
}

// -------------------------------------------------------------------------- //
// useStudioHotkeys                                                            //
// -------------------------------------------------------------------------- //

/**
 * Studio-specific keyboard shortcuts.
 * Pre-wired to the studio store.
 *
 * Shortcuts:
 *   Space            → Play / Pause
 *   ArrowLeft        → Seek -5 s
 *   ArrowRight       → Seek +5 s
 *   Shift+ArrowLeft  → Previous scene
 *   Shift+ArrowRight → Next scene
 *   KeyM             → Toggle mute
 *   KeyF             → Toggle fullscreen
 *   KeyS             → Toggle subtitles
 *
 * @param enabled - Master switch (set false in modals, text editing)
 */
export function useStudioHotkeys(enabled = true) {
  const { useStudioStore } = require("@/store") as typeof import("@/store");
  const store = useStudioStore();

  useHotkeys(
    [
      {
        key:         "Space",
        description: "Play / Pause",
        enabled,
        handler: () => {
          const { isPlaying } = useStudioStore.getState().playback ?? {};
          if (isPlaying) {
            store.setPlaying(false);
          } else {
            store.setPlaying(true);
          }
        },
      },
      {
        key:         "ArrowLeft",
        description: "Seek -5 seconds",
        enabled,
        handler: () => {
          const t = useStudioStore.getState().currentTimeSeconds ?? 0;
          store.seekTo(Math.max(0, t - 5));
        },
      },
      {
        key:         "ArrowRight",
        description: "Seek +5 seconds",
        enabled,
        handler: () => {
          const s = useStudioStore.getState();
          store.seekTo(Math.min(s.durationSeconds, (s.currentTimeSeconds ?? 0) + 5));
        },
      },
      {
        key:         "ArrowLeft",
        modifiers:   { shift: true },
        description: "Previous scene",
        enabled,
        handler: () => {
          const idx = useStudioStore.getState().currentSceneIndex;
          if (idx > 0) store.goToScene(idx - 1);
        },
      },
      {
        key:         "ArrowRight",
        modifiers:   { shift: true },
        description: "Next scene",
        enabled,
        handler: () => {
          const s = useStudioStore.getState();
          if (s.currentSceneIndex < s.scenes.length - 1) {
            store.goToScene(s.currentSceneIndex + 1);
          }
        },
      },
      {
        key:         "KeyM",
        description: "Toggle mute",
        enabled,
        handler: () => store.toggleMute(),
      },
      {
        key:         "KeyF",
        description: "Toggle fullscreen",
        enabled,
        handler: () => {
          if (!document.fullscreenElement) {
            document.documentElement.requestFullscreen().catch(console.error);
            store.setFullscreen(true);
          } else {
            document.exitFullscreen().catch(console.error);
            store.setFullscreen(false);
          }
        },
      },
      {
        key:         "KeyS",
        description: "Toggle subtitles",
        enabled,
        handler: () => store.toggleSubtitles(),
      },
    ],
    { allowInInputs: false }
  );
          }
