/**
 * timecode.ts
 * Timecode formatting, conversion, and frame-level math utilities.
 * Pure functions — no React, no state, no side effects.
 *
 * Used by: timeline component, video player progress bar,
 *          scene thumbnail timestamps, subtitle timing display.
 */

// -------------------------------------------------------------------------- //
// Constants                                                                    //
// -------------------------------------------------------------------------- //

/** Frames per second — backend always renders at 30fps. */
export const VIDEO_FPS = 30;

/** Seconds in one minute. */
const SECONDS_PER_MINUTE = 60;

/** Seconds in one hour. */
const SECONDS_PER_HOUR = 3_600;

/**
 * Maximum supported video duration in seconds.
 * Matches backend MAX_VIDEO_DURATION_SECONDS = 600 (10 minutes).
 */
export const MAX_VIDEO_DURATION_SECONDS = 600;

// -------------------------------------------------------------------------- //
// Core formatting                                                               //
// -------------------------------------------------------------------------- //

/**
 * Format seconds to HH:MM:SS display string.
 * Used in video player duration display and scene timestamps.
 *
 * @param seconds - Time in seconds (float or int, may be negative or NaN)
 * @returns Zero-padded string "HH:MM:SS"
 *
 * @example
 *   formatTimecode(0)       // "00:00:00"
 *   formatTimecode(65.7)    // "00:01:05"
 *   formatTimecode(3661)    // "01:01:01"
 *   formatTimecode(-5)      // "00:00:00"  (clamped to 0)
 *   formatTimecode(NaN)     // "00:00:00"
 */
export function formatTimecode(seconds: number): string {
  const safe = Math.max(0, isNaN(seconds) ? 0 : Math.floor(seconds));
  const h = Math.floor(safe / SECONDS_PER_HOUR);
  const m = Math.floor((safe % SECONDS_PER_HOUR) / SECONDS_PER_MINUTE);
  const s = safe % SECONDS_PER_MINUTE;
  return [
    String(h).padStart(2, "0"),
    String(m).padStart(2, "0"),
    String(s).padStart(2, "0"),
  ].join(":");
}

/**
 * Format seconds to MM:SS display string (omits hours).
 * Prefer this when the video is known to be under 1 hour.
 *
 * @param seconds - Time in seconds
 * @returns Formatted "MM:SS" string; minutes overflow past 59 without hours
 *
 * @example
 *   formatTimecodeShort(0)    // "00:00"
 *   formatTimecodeShort(65)   // "01:05"
 *   formatTimecodeShort(3661) // "61:01"
 */
export function formatTimecodeShort(seconds: number): string {
  const safe = Math.max(0, isNaN(seconds) ? 0 : Math.floor(seconds));
  const m = Math.floor(safe / SECONDS_PER_MINUTE);
  const s = safe % SECONDS_PER_MINUTE;
  return `${String(m).padStart(2, "0")}:${String(s).padStart(2, "0")}`;
}

/**
 * Format seconds to SRT subtitle timestamp "HH:MM:SS,mmm".
 * The comma separator is mandatory in SRT format.
 *
 * @param seconds - Time in seconds (float for sub-second precision)
 * @returns SRT timestamp string
 *
 * @example
 *   formatSrtTimestamp(1.5)     // "00:00:01,500"
 *   formatSrtTimestamp(65.123)  // "00:01:05,123"
 *   formatSrtTimestamp(0)       // "00:00:00,000"
 */
export function formatSrtTimestamp(seconds: number): string {
  const safe = Math.max(0, isNaN(seconds) ? 0 : seconds);
  const h  = Math.floor(safe / SECONDS_PER_HOUR);
  const m  = Math.floor((safe % SECONDS_PER_HOUR) / SECONDS_PER_MINUTE);
  const s  = Math.floor(safe % SECONDS_PER_MINUTE);
  const ms = Math.round((safe % 1) * 1000);
  return (
    [
      String(h).padStart(2, "0"),
      String(m).padStart(2, "0"),
      String(s).padStart(2, "0"),
    ].join(":") + `,${String(ms).padStart(3, "0")}`
  );
}

/**
 * Format seconds to VTT subtitle timestamp "HH:MM:SS.mmm".
 * Identical to SRT but uses "." as millisecond separator.
 *
 * @param seconds - Time in seconds (float for sub-second precision)
 * @returns VTT timestamp string
 *
 * @example
 *   formatVttTimestamp(1.5)    // "00:00:01.500"
 *   formatVttTimestamp(65.123) // "00:01:05.123"
 */
export function formatVttTimestamp(seconds: number): string {
  return formatSrtTimestamp(seconds).replace(",", ".");
}

/**
 * Format a duration as a human-readable string.
 * Adapts units based on duration length — omits seconds for long videos.
 *
 * @param seconds - Duration in seconds
 * @returns Human-readable string
 *
 * @example
 *   formatDuration(45)   // "45s"
 *   formatDuration(90)   // "1m 30s"
 *   formatDuration(3600) // "1h"
 *   formatDuration(3661) // "1h 1m"
 *   formatDuration(0)    // "0s"
 */
export function formatDuration(seconds: number): string {
  const safe = Math.max(0, isNaN(seconds) ? 0 : Math.floor(seconds));
  if (safe < SECONDS_PER_MINUTE) return `${safe}s`;
  if (safe < SECONDS_PER_HOUR) {
    const m = Math.floor(safe / SECONDS_PER_MINUTE);
    const s = safe % SECONDS_PER_MINUTE;
    return s > 0 ? `${m}m ${s}s` : `${m}m`;
  }
  const h = Math.floor(safe / SECONDS_PER_HOUR);
  const m = Math.floor((safe % SECONDS_PER_HOUR) / SECONDS_PER_MINUTE);
  return m > 0 ? `${h}h ${m}m` : `${h}h`;
}

// -------------------------------------------------------------------------- //
// Parsing                                                                       //
// -------------------------------------------------------------------------- //

/**
 * Parse "HH:MM:SS" or "MM:SS" timecode string to total seconds.
 * Inverse of formatTimecode().
 *
 * @param timecode - String in "HH:MM:SS" or "MM:SS" format
 * @returns Total seconds as integer; 0 on parse failure
 *
 * @example
 *   parseTimecode("00:01:05") // 65
 *   parseTimecode("01:01:01") // 3661
 *   parseTimecode("01:05")    // 65
 *   parseTimecode("invalid")  // 0
 */
export function parseTimecode(timecode: string): number {
  const parts = timecode.trim().split(":").map(Number);
  if (parts.some(isNaN)) return 0;
  if (parts.length === 3) {
    const [h, m, s] = parts as [number, number, number];
    return h * SECONDS_PER_HOUR + m * SECONDS_PER_MINUTE + s;
  }
  if (parts.length === 2) {
    const [m, s] = parts as [number, number];
    return m * SECONDS_PER_MINUTE + s;
  }
  return 0;
}

/**
 * Parse SRT timestamp "HH:MM:SS,mmm" to seconds.
 *
 * @param timestamp - SRT format timestamp (comma as millisecond separator)
 * @returns Seconds as float with millisecond precision; 0 on failure
 *
 * @example
 *   parseSrtTimestamp("00:01:05,500") // 65.5
 *   parseSrtTimestamp("00:00:00,000") // 0
 */
export function parseSrtTimestamp(timestamp: string): number {
  const [timePart, msPart] = timestamp.split(",");
  if (!timePart) return 0;
  const base = parseTimecode(timePart);
  const ms = parseInt(msPart ?? "0", 10);
  return base + (isNaN(ms) ? 0 : ms) / 1000;
}

/**
 * Parse VTT timestamp "HH:MM:SS.mmm" to seconds.
 *
 * @param timestamp - VTT format timestamp (dot as millisecond separator)
 * @returns Seconds as float with millisecond precision; 0 on failure
 *
 * @example
 *   parseVttTimestamp("00:01:05.500") // 65.5
 */
export function parseVttTimestamp(timestamp: string): number {
  return parseSrtTimestamp(timestamp.replace(".", ","));
}

// -------------------------------------------------------------------------- //
// Frame math                                                                    //
// -------------------------------------------------------------------------- //

/**
 * Convert time in seconds to a 0-indexed frame number.
 *
 * @param seconds - Time in seconds (negative values treated as 0)
 * @param fps - Frames per second (default: VIDEO_FPS = 30)
 * @returns Integer frame number (0-indexed)
 *
 * @example
 *   secondsToFrame(1.0)   // 30  (at 30fps)
 *   secondsToFrame(0.033) // 0
 *   secondsToFrame(0.067) // 2
 */
export function secondsToFrame(
  seconds: number,
  fps: number = VIDEO_FPS
): number {
  return Math.floor(Math.max(0, seconds) * fps);
}

/**
 * Convert a 0-indexed frame number to time in seconds.
 *
 * @param frame - Frame number (0-indexed; negative values treated as 0)
 * @param fps - Frames per second (default: VIDEO_FPS = 30)
 * @returns Time in seconds as float
 *
 * @example
 *   frameToSeconds(30) // 1.0   (at 30fps)
 *   frameToSeconds(0)  // 0.0
 *   frameToSeconds(45) // 1.5
 */
export function frameToSeconds(
  frame: number,
  fps: number = VIDEO_FPS
): number {
  return Math.max(0, frame) / fps;
}

/**
 * Get the total frame count for a video of the given duration.
 *
 * @param durationSeconds - Video duration in seconds
 * @param fps - Frames per second (default: VIDEO_FPS = 30)
 * @returns Total frame count as integer
 *
 * @example
 *   getTotalFrames(10)  // 300  (at 30fps)
 *   getTotalFrames(0)   // 0
 */
export function getTotalFrames(
  durationSeconds: number,
  fps: number = VIDEO_FPS
): number {
  return Math.floor(Math.max(0, durationSeconds) * fps);
}

/**
 * Snap a time value to the nearest frame boundary.
 * Prevents sub-frame precision that can cause display artifacts in the timeline.
 *
 * @param seconds - Time in seconds
 * @param fps - Frames per second (default: VIDEO_FPS = 30)
 * @returns Time snapped to the nearest frame, in seconds
 *
 * @example
 *   snapToFrame(1.016, 30) // 1.0    (frame 30)
 *   snapToFrame(1.034, 30) // 1.0333 (frame 31)
 */
export function snapToFrame(
  seconds: number,
  fps: number = VIDEO_FPS
): number {
  return Math.round(seconds * fps) / fps;
}

// -------------------------------------------------------------------------- //
// Timeline math                                                                 //
// -------------------------------------------------------------------------- //

/**
 * Convert playback time to percentage of total duration.
 * Used for progress bar width and timeline cursor position.
 *
 * @param currentSeconds - Current playback position in seconds
 * @param totalSeconds - Total video duration in seconds
 * @returns Percentage 0–100, clamped; returns 0 if duration is 0 or NaN
 *
 * @example
 *   timeToPercent(30, 120)  // 25
 *   timeToPercent(120, 120) // 100
 *   timeToPercent(0, 0)     // 0
 */
export function timeToPercent(
  currentSeconds: number,
  totalSeconds: number
): number {
  if (totalSeconds <= 0 || isNaN(totalSeconds)) return 0;
  return Math.min(100, Math.max(0, (currentSeconds / totalSeconds) * 100));
}

/**
 * Convert percentage of total duration to time in seconds.
 * Used for seek-on-click in the progress bar.
 *
 * @param percent - Percentage 0–100 (clamped if outside range)
 * @param totalSeconds - Total video duration in seconds
 * @returns Time in seconds
 *
 * @example
 *   percentToTime(25, 120) // 30
 *   percentToTime(100, 60) // 60
 */
export function percentToTime(
  percent: number,
  totalSeconds: number
): number {
  return (Math.min(100, Math.max(0, percent)) / 100) * totalSeconds;
}

/**
 * Get the start time offset of a scene within the full video.
 * Used for scene navigation and timeline rendering.
 *
 * @param sceneIndex - 0-based index of the target scene
 * @param sceneDurations - Array of each scene's duration in seconds
 * @returns Start time of the scene in seconds; 0 for scene 0 or empty array
 *
 * @example
 *   getSceneOffset(2, [30, 45, 30, 25]) // 75  (30 + 45)
 *   getSceneOffset(0, [30, 45])          // 0
 *   getSceneOffset(0, [])               // 0
 */
export function getSceneOffset(
  sceneIndex: number,
  sceneDurations: readonly number[]
): number {
  return sceneDurations
    .slice(0, Math.max(0, sceneIndex))
    .reduce((sum, d) => sum + (d ?? 0), 0);
}

/**
 * Determine which scene index corresponds to a given playback time.
 * Used to highlight the current scene in the studio timeline.
 *
 * @param currentSeconds - Current playback position in seconds
 * @param sceneDurations - Array of each scene's duration in seconds
 * @returns 0-based scene index; -1 if time is beyond all scenes or array is empty
 *
 * @example
 *   getSceneAtTime(35, [30, 45, 30]) // 1  (scene 1 spans 30–75 s)
 *   getSceneAtTime(0, [30, 45])      // 0
 *   getSceneAtTime(200, [30, 45])    // -1
 */
export function getSceneAtTime(
  currentSeconds: number,
  sceneDurations: readonly number[]
): number {
  let elapsed = 0;
  for (let i = 0; i < sceneDurations.length; i++) {
    const dur = sceneDurations[i] ?? 0;
    if (currentSeconds < elapsed + dur) return i;
    elapsed += dur;
  }
  return -1;
}

/**
 * Clamp a time value to the valid range [0, duration].
 *
 * @param seconds - Time to clamp
 * @param durationSeconds - Maximum allowed time
 * @returns Clamped time in seconds
 *
 * @example
 *   clampTime(-5, 120)  // 0
 *   clampTime(150, 120) // 120
 *   clampTime(60, 120)  // 60
 */
export function clampTime(
  seconds: number,
  durationSeconds: number
): number {
  return Math.min(Math.max(0, seconds), Math.max(0, durationSeconds));
}

/**
 * Check if a time value falls within valid video bounds [0, duration].
 *
 * @param seconds - Time to validate
 * @param durationSeconds - Total video duration
 * @returns true if time is within [0, duration] and not NaN
 *
 * @example
 *   isValidTime(60, 120)  // true
 *   isValidTime(-1, 120)  // false
 *   isValidTime(NaN, 120) // false
 */
export function isValidTime(
  seconds: number,
  durationSeconds: number
): boolean {
  return !isNaN(seconds) && seconds >= 0 && seconds <= durationSeconds;
}

/**
 * Compute per-scene time ranges from an array of durations.
 * Useful for rendering timeline tracks without repeated summation.
 *
 * @param sceneDurations - Array of scene durations in seconds
 * @returns Array of {startSeconds, endSeconds} objects, one per scene
 *
 * @example
 *   getSceneTimeRanges([30, 45, 25])
 *   // [{startSeconds: 0, endSeconds: 30},
 *   //  {startSeconds: 30, endSeconds: 75},
 *   //  {startSeconds: 75, endSeconds: 100}]
 */
export function getSceneTimeRanges(
  sceneDurations: readonly number[]
): { startSeconds: number; endSeconds: number }[] {
  const ranges: { startSeconds: number; endSeconds: number }[] = [];
  let cursor = 0;
  for (const dur of sceneDurations) {
    const d = dur ?? 0;
    ranges.push({ startSeconds: cursor, endSeconds: cursor + d });
    cursor += d;
  }
  return ranges;
    }
