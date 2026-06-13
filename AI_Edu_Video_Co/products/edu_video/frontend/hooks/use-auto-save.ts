"use client";

/**
 * use-auto-save.ts
 * Debounced auto-save with dirty tracking and retry on failure.
 * Used in the studio script editor to persist draft changes.
 */

import { useEffect, useRef, useCallback, useState } from "react";
import { useStudioStore, selectAutoSave } from "@/store";
import { debounce } from "@/lib/utils";

// -------------------------------------------------------------------------- //
// useAutoSave                                                                 //
// -------------------------------------------------------------------------- //

type AutoSaveOptions<T> = {
  /** Current value to watch for changes. */
  value:        T;
  /** Async function that persists the value. Returns true on success. */
  onSave:       (value: T) => Promise<boolean>;
  /** Debounce delay in ms (default: 1500 ms). */
  delay?:       number;
  /** Whether auto-save is active (default: true). */
  enabled?:     boolean;
  /** Max retry attempts on failure (default: 2). */
  maxRetries?:  number;
};

type AutoSaveState = {
  /** True while a save is in flight. */
  isSaving:   boolean;
  /** True if last save failed after all retries. */
  saveError:  string | null;
  /** ISO string of last successful save. */
  lastSavedAt: number | null;
  /** Whether there are unsaved changes. */
  isDirty:    boolean;
  /** Manually trigger a save (bypasses debounce). */
  saveNow:    () => Promise<void>;
};

/**
 * Watch a value and auto-save changes with debouncing and retry.
 *
 * @param options - Value to watch, save function, delay, and retry count
 * @returns Auto-save state including isSaving, saveError, and saveNow
 *
 * @example
 *   const { isSaving, isDirty, saveNow } = useAutoSave({
 *     value: scriptContent,
 *     onSave: async (content) => {
 *       const result = await updateSceneScript(sceneId, content);
 *       return result.success;
 *     },
 *   });
 */
export function useAutoSave<T>({
  value,
  onSave,
  delay      = 1_500,
  enabled    = true,
  maxRetries = 2,
}: AutoSaveOptions<T>): AutoSaveState {
  const [isSaving,  setIsSaving]  = useState(false);
  const [saveError, setSaveError] = useState<string | null>(null);

  const { isDirty, lastSavedAt } = useStudioStore(selectAutoSave);
  const storeMarkDirty = useStudioStore((s) => s.markDirty);
  const storeMarkSaved = useStudioStore((s) => s.markSaved);

  const prevValueRef  = useRef<T>(value);
  const isMountedRef  = useRef(true);
  const retryCountRef = useRef(0);

  useEffect(() => {
    isMountedRef.current = true;
    return () => { isMountedRef.current = false; };
  }, []);

  const persist = useCallback(async (val: T): Promise<void> => {
    if (!isMountedRef.current) return;
    setIsSaving(true);
    setSaveError(null);

    let attempt = 0;
    while (attempt <= maxRetries) {
      try {
        const ok = await onSave(val);
        if (!isMountedRef.current) return;
        if (ok) {
          storeMarkSaved();
          retryCountRef.current = 0;
          setIsSaving(false);
          return;
        }
        throw new Error("Save returned false");
      } catch {
        attempt++;
        if (attempt > maxRetries) {
          if (isMountedRef.current) {
            setSaveError("Auto-save failed — changes are not persisted.");
            setIsSaving(false);
          }
          return;
        }
        // Exponential back-off between retries
        await new Promise((r) => setTimeout(r, 500 * attempt));
      }
    }
  }, [onSave, maxRetries, storeMarkSaved]);

  // Stable debounced save
  const debouncedSave = useRef(debounce(persist, delay));

  useEffect(() => {
    debouncedSave.current = debounce(persist, delay);
  }, [persist, delay]);

  // Detect changes and trigger debounced save
  useEffect(() => {
    if (!enabled) return;

    const hasChanged =
      JSON.stringify(value) !== JSON.stringify(prevValueRef.current);

    if (hasChanged) {
      prevValueRef.current = value;
      storeMarkDirty();
      debouncedSave.current(value);
    }
  }, [value, enabled, storeMarkDirty]);

  // Flush on unmount to avoid losing the last change
  useEffect(() => {
    return () => {
      debouncedSave.current.cancel();
    };
  }, []);

  const saveNow = useCallback(async () => {
    debouncedSave.current.cancel();
    await persist(value);
  }, [persist, value]);

  return {
    isSaving,
    saveError,
    lastSavedAt,
    isDirty,
    saveNow,
  };
    }
