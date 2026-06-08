/**
 * subtitle-utils.ts
 * Subtitle parsing, cue matching, and rendering utilities.
 * All matching uses binary search — O(log n) — for 60fps player performance.
 *
 * Supports SRT and VTT subtitle formats delivered by the backend CDN.
 */

import {
  parseSrtTimestamp,
  parseVttTimestamp,
} from "./timecode";

// -------------------------------------------------------------------------- //
// Types                                                                         //
// -------------------------------------------------------------------------- //

/**
 * A single subtitle cue — one line or block of text with time bounds.
 * Maps to backend SubtitleCue in types/scene.ts.
 */
export type SubtitleCue = {
  readonly index: number;           // 1-based cue index (from SRT/VTT file)
  readonly startSeconds: number;    // Cue start time in seconds
  readonly endSeconds: number;      // Cue end time in seconds
  readonly text: string;            // Plain text content (HTML tags stripped)
  readonly rawText: string;         // Original text including any tags
};

/**
 * Parsed subtitle data — collection of sorted cues.
 */
export type SubtitleData = {
  readonly cues: readonly SubtitleCue[];
  readonly format: "srt" | "vtt";
  readonly totalCues: number;
};

/**
 * Subtitle display configuration for the video player overlay.
 */
export type SubtitleStyle = {
  fontSize: number;           // px — e.g. 20
  fontFamily: string;         // CSS font-family string
  color: string;              // CSS colour — e.g. "#FFFFFF"
  backgroundColor: string;    // CSS colour with alpha — e.g. "rgba(0,0,0,0.75)"
  bottomOffset: number;       // px from bottom of video element
  maxWidth: string;           // CSS width — e.g. "80%"
  textAlign: "center" | "left" | "right";
  lineHeight: number;         // unitless multiplier — e.g. 1.4
};

/**
 * Default subtitle style matching educational video design system.
 */
export const DEFAULT_SUBTITLE_STYLE: SubtitleStyle = {
  fontSize: 20,
  fontFamily: "system-ui, -apple-system, sans-serif",
  color: "#FFFFFF",
  backgroundColor: "rgba(0, 0, 0, 0.75)",
  bottomOffset: 40,
  maxWidth: "80%",
  textAlign: "center",
  lineHeight: 1.4,
};

// -------------------------------------------------------------------------- //
// SRT parsing                                                                   //
// -------------------------------------------------------------------------- //

/**
 * Parse SRT (SubRip Text) subtitle file content into SubtitleData.
 *
 * SRT format:
 *   1
 *   00:00:01,500 --> 00:00:03,800
 *   Text of the first cue
 *
 *   2
 *   00:00:04,200 --> 00:00:06,100
 *   Text of the second cue
 *
 * @param content - Raw SRT file content as string
 * @returns Parsed SubtitleData with cues sorted by startSeconds
 *
 * @example
 *   const data = parseSrtContent("1\n00:00:01,500 --> 00:00:03,800\nHello\n");
 *   data.cues[0]?.startSeconds // 1.5
 *   data.cues[0]?.text         // "Hello"
 */
export function parseSrtContent(content: string): SubtitleData {
  const cues: SubtitleCue[] = [];

  // Split on blank lines (handles \r\n and \n)
  const blocks = content.trim().split(/\n\s*\n/);

  for (const block of blocks) {
    const lines = block.trim().split(/\r?\n/);
    if (lines.length < 3) continue;

    const indexLine = lines[0]?.trim() ?? "";
    const timingLine = lines[1]?.trim() ?? "";
    const textLines = lines.slice(2);

    const index = parseInt(indexLine, 10);
    if (isNaN(index)) continue;

    // Parse "HH:MM:SS,mmm --> HH:MM:SS,mmm"
    const timingMatch = timingLine.match(
      /^(\d{2}:\d{2}:\d{2},\d{3})\s*-->\s*(\d{2}:\d{2}:\d{2},\d{3})/
    );
    if (!timingMatch) continue;

    const startSeconds = parseSrtTimestamp(timingMatch[1] ?? "");
    const endSeconds   = parseSrtTimestamp(timingMatch[2] ?? "");
    if (endSeconds <= startSeconds) continue;

    const rawText = textLines.join("\n");
    const text    = stripSubtitleTags(rawText);

    cues.push({ index, startSeconds, endSeconds, text, rawText });
  }

  // Guarantee sorted by startSeconds — binary search requires this
  cues.sort((a, b) => a.startSeconds - b.startSeconds);

  return { cues, format: "srt", totalCues: cues.length };
}

// -------------------------------------------------------------------------- //
// VTT parsing                                                                   //
// -------------------------------------------------------------------------- //

/**
 * Parse WebVTT subtitle file content into SubtitleData.
 *
 * VTT format:
 *   WEBVTT
 *
 *   1
 *   00:00:01.500 --> 00:00:03.800
 *   Hello world
 *
 * @param content - Raw VTT file content as string
 * @returns Parsed SubtitleData with cues sorted by startSeconds
 *
 * @example
 *   const data = parseVttContent("WEBVTT\n\n1\n00:00:01.500 --> 00:00:03.800\nHello\n");
 *   data.cues[0]?.startSeconds // 1.5
 */
export function parseVttContent(content: string): SubtitleData {
  const cues: SubtitleCue[] = [];

  // Remove WEBVTT header and any NOTE / STYLE blocks
  const body = content
    .replace(/^WEBVTT[^\n]*\n/, "")
    .replace(/NOTE[^\n]*\n(.*\n)*/gm, "")
    .replace(/STYLE[^\n]*\n(.*\n)*/gm, "")
    .trim();

  const blocks = body.split(/\n\s*\n/);
  let autoIndex = 1;

  for (const block of blocks) {
    const lines = block.trim().split(/\r?\n/);
    if (lines.length < 2) continue;

    let timingLineIdx = 0;
    let cueIndex = autoIndex;

    // Cue may optionally start with an identifier line
    if (lines[0] && !lines[0].includes("-->")) {
      const parsed = parseInt(lines[0].trim(), 10);
      cueIndex = isNaN(parsed) ? autoIndex : parsed;
      timingLineIdx = 1;
    }

    const timingLine = lines[timingLineIdx]?.trim() ?? "";

    // Parse "HH:MM:SS.mmm --> HH:MM:SS.mmm [cue settings]"
    const timingMatch = timingLine.match(
      /^(\d{2}:\d{2}:\d{2}\.\d{3})\s*-->\s*(\d{2}:\d{2}:\d{2}\.\d{3})/
    );
    if (!timingMatch) continue;

    const startSeconds = parseVttTimestamp(timingMatch[1] ?? "");
    const endSeconds   = parseVttTimestamp(timingMatch[2] ?? "");
    if (endSeconds <= startSeconds) continue;

    const textLines = lines.slice(timingLineIdx + 1);
    const rawText   = textLines.join("\n");
    const text      = stripSubtitleTags(rawText);

    cues.push({ index: cueIndex, startSeconds, endSeconds, text, rawText });
    autoIndex++;
  }

  cues.sort((a, b) => a.startSeconds - b.startSeconds);
  return { cues, format: "vtt", totalCues: cues.length };
}

// -------------------------------------------------------------------------- //
// Cue matching — O(log n) binary search                                        //
// -------------------------------------------------------------------------- //

/**
 * Find the active subtitle cue for the given playback time.
 * Uses binary search — O(log n) — safe for 60fps player loops.
 *
 * Assumes cues are sorted by startSeconds (guaranteed by parseSrtContent
 * and parseVttContent).
 *
 * @param cues - Sorted array of SubtitleCue (ascending by startSeconds)
 * @param currentSeconds - Current playback time in seconds
 * @returns The active cue, or null if no cue is active at this time
 *
 * @example
 *   const cue = findActiveCue(data.cues, 2.0);
 *   // Returns cue spanning 1.5–3.8 s for time 2.0 s
 *   cue?.text // "Hello world"
 */
export function findActiveCue(
  cues: readonly SubtitleCue[],
  currentSeconds: number
): SubtitleCue | null {
  if (cues.length === 0 || isNaN(currentSeconds)) return null;

  // Binary search for the rightmost cue whose startSeconds <= currentSeconds
  let lo = 0;
  let hi = cues.length - 1;
  let candidate = -1;

  while (lo <= hi) {
    const mid = (lo + hi) >>> 1;
    const cue = cues[mid]!;
    if (cue.startSeconds <= currentSeconds) {
      candidate = mid;
      lo = mid + 1;
    } else {
      hi = mid - 1;
    }
  }

  if (candidate === -1) return null;

  const activeCue = cues[candidate]!;
  return activeCue.endSeconds > currentSeconds ? activeCue : null;
}

/**
 * Find all cues that overlap a given time range.
 * Used for subtitle preview in the timeline editor.
 *
 * @param cues - Sorted array of SubtitleCue
 * @param startSeconds - Range start in seconds
 * @param endSeconds - Range end in seconds
 * @returns Array of cues whose time ranges overlap [startSeconds, endSeconds]
 *
 * @example
 *   findCuesInRange(cues, 0, 10) // All cues starting before 10s and ending after 0s
 */
export function findCuesInRange(
  cues: readonly SubtitleCue[],
  startSeconds: number,
  endSeconds: number
): SubtitleCue[] {
  if (cues.length === 0 || endSeconds < startSeconds) return [];

  return cues.filter(
    (c) => c.endSeconds > startSeconds && c.startSeconds < endSeconds
  );
}

/**
 * Get adjacent cues (previous and next) relative to the current time.
 * Used for subtitle lookahead in the player controls.
 *
 * @param cues - Sorted array of SubtitleCue
 * @param currentSeconds - Current playback time
 * @returns Object with prev and next cue (each may be null)
 */
export function getAdjacentCues(
  cues: readonly SubtitleCue[],
  currentSeconds: number
): { prev: SubtitleCue | null; next: SubtitleCue | null } {
  if (cues.length === 0) return { prev: null, next: null };

  // Binary search for insertion point
  let lo = 0;
  let hi = cues.length - 1;
  let insertAt = 0;

  while (lo <= hi) {
    const mid = (lo + hi) >>> 1;
    const cue = cues[mid]!;
    if (cue.startSeconds <= currentSeconds) {
      insertAt = mid + 1;
      lo = mid + 1;
    } else {
      hi = mid - 1;
    }
  }

  const prev = insertAt > 0 ? (cues[insertAt - 1] ?? null) : null;
  const next = insertAt < cues.length ? (cues[insertAt] ?? null) : null;

  return { prev, next };
}

// -------------------------------------------------------------------------- //
// Text utilities                                                                //
// -------------------------------------------------------------------------- //

/**
 * Strip HTML-like tags from subtitle text.
 * SRT/VTT files sometimes include <b>, <i>, <u>, <c>, <v> tags.
 *
 * @param text - Raw subtitle text possibly containing tags
 * @returns Plain text with all tags removed
 *
 * @example
 *   stripSubtitleTags("<b>Hello</b> <i>world</i>") // "Hello world"
 *   stripSubtitleTags("<c.yellow>Text</c>")         // "Text"
 */
export function stripSubtitleTags(text: string): string {
  return text
    .replace(/<[^>]*>/g, "")  // Remove all HTML-like tags
    .replace(/&amp;/g,  "&")
    .replace(/&lt;/g,   "<")
    .replace(/&gt;/g,   ">")
    .replace(/&nbsp;/g, " ")
    .trim();
}

/**
 * Normalise subtitle text for display:
 *   - Collapse multiple consecutive blank lines to one
 *   - Trim leading/trailing whitespace from each line
 *   - Remove empty lines at start and end
 *
 * @param text - Raw subtitle cue text
 * @returns Normalised display text
 */
export function normaliseSubtitleText(text: string): string {
  return text
    .split("\n")
    .map((line) => line.trim())
    .filter((line, index, arr) => {
      // Keep non-empty lines; collapse consecutive empty lines to one
      if (line.length > 0) return true;
      const prev = arr[index - 1];
      return prev !== undefined && prev.length > 0;
    })
    .join("\n")
    .trim();
}

// -------------------------------------------------------------------------- //
// Subtitle overlay CSS generation                                              //
// -------------------------------------------------------------------------- //

/**
 * Generate inline CSS style object for the subtitle overlay element.
 * Returns a React-compatible CSSProperties object.
 *
 * @param style - Subtitle style configuration
 * @returns CSS properties object for use in React style prop
 *
 * @example
 *   <div style={getSubtitleStyles(DEFAULT_SUBTITLE_STYLE)}>
 *     {activeCue?.text}
 *   </div>
 */
export function getSubtitleStyles(
  style: SubtitleStyle
): Record<string, string | number> {
  return {
    position:        "absolute",
    bottom:          `${style.bottomOffset}px`,
    left:            "50%",
    transform:       "translateX(-50%)",
    maxWidth:        style.maxWidth,
    width:           "max-content",
    fontSize:        `${style.fontSize}px`,
    fontFamily:      style.fontFamily,
    color:           style.color,
    backgroundColor: style.backgroundColor,
    textAlign:       style.textAlign,
    lineHeight:      style.lineHeight,
    padding:         "4px 12px",
    borderRadius:    "4px",
    pointerEvents:   "none",   // Don't block video click events
    userSelect:      "none",
    zIndex:          10,
    whiteSpace:      "pre-wrap",
  };
}

/**
 * Scale subtitle font size relative to video element dimensions.
 * Ensures subtitles are readable regardless of player size.
 *
 * Base: 20px at 1920px width. Scales linearly, min 12px, max 32px.
 *
 * @param playerWidth - Current video element width in pixels
 * @param baseSize - Base font size in px (default: 20)
 * @returns Scaled font size in px
 *
 * @example
 *   scaleFontSize(960)   // 10  → clamped to 12
 *   scaleFontSize(1920)  // 20
 *   scaleFontSize(3840)  // 40 → clamped to 32
 */
export function scaleFontSize(
  playerWidth: number,
  baseSize = 20
): number {
  const BASE_WIDTH = 1920;
  const scaled = (playerWidth / BASE_WIDTH) * baseSize;
  return Math.min(32, Math.max(12, Math.round(scaled)));
}

// -------------------------------------------------------------------------- //
// Format detection                                                              //
// -------------------------------------------------------------------------- //

/**
 * Detect subtitle format from raw file content.
 *
 * @param content - Raw subtitle file content
 * @returns "srt" or "vtt"
 *
 * @example
 *   detectSubtitleFormat("WEBVTT\n\n1\n...")  // "vtt"
 *   detectSubtitleFormat("1\n00:00:01,500...")// "srt"
 */
export function detectSubtitleFormat(content: string): "srt" | "vtt" {
  return content.trimStart().startsWith("WEBVTT") ? "vtt" : "srt";
}

/**
 * Parse subtitle content automatically — detects SRT vs VTT.
 *
 * @param content - Raw subtitle file content (SRT or VTT)
 * @returns Parsed SubtitleData
 *
 * @example
 *   const data = parseSubtitleContent(rawContent);
 *   // Works regardless of whether rawContent is SRT or VTT
 */
export function parseSubtitleContent(content: string): SubtitleData {
  const format = detectSubtitleFormat(content);
  return format === "vtt"
    ? parseVttContent(content)
    : parseSrtContent(content);
}

// -------------------------------------------------------------------------- //
// Empty state helpers                                                           //
// -------------------------------------------------------------------------- //

/**
 * Create an empty SubtitleData object.
 * Use as initial state before subtitles finish loading.
 *
 * @param format - Subtitle format hint (default "srt")
 * @returns Empty SubtitleData
 */
export function emptySubtitleData(
  format: "srt" | "vtt" = "srt"
): SubtitleData {
  return { cues: [], format, totalCues: 0 };
}

/**
 * Check whether a SubtitleData object has any cues.
 *
 * @param data - SubtitleData to check
 * @returns true if there is at least one cue
 */
export function hasSubtitles(data: SubtitleData): boolean {
  return data.totalCues > 0;
}
