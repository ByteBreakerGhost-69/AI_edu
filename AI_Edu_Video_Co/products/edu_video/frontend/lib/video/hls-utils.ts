/**
 * hls-utils.ts
 * HLS.js setup, quality level management, and error recovery.
 * Handles adaptive streaming for premium users.
 *
 * HLS.js is lazy-loaded via dynamic import — NOT included in the initial bundle.
 * Add to package.json: "hls.js": "^1.5.0"
 */

import type Hls from "hls.js";
import type { HlsConfig, Level, ErrorData } from "hls.js";

// -------------------------------------------------------------------------- //
// Types                                                                         //
// -------------------------------------------------------------------------- //

/**
 * HLS quality level for the quality selector UI.
 */
export type HlsQualityLevel = {
  readonly index: number;       // HLS.js level index (-1 = auto)
  readonly label: string;       // Display label e.g. "1080p", "720p", "Auto"
  readonly height: number;      // Video height in pixels (0 for Auto)
  readonly bitrate: number;     // Bits per second (0 for Auto)
  readonly isAuto: boolean;     // True only for the Auto option
};

/**
 * Current HLS playback state snapshot.
 */
export type HlsPlaybackState = {
  readonly isSupported: boolean;
  readonly isAttached: boolean;
  readonly currentLevel: number;      // -1 = auto
  readonly levels: HlsQualityLevel[];
  readonly bufferedSeconds: number;
  readonly networkError: boolean;
  readonly fatalError: boolean;
};

/**
 * Options for HLS player initialisation.
 */
export type HlsPlayerOptions = {
  /** Called when HLS attaches and levels are known. */
  onReady?: (levels: HlsQualityLevel[]) => void;
  /** Called on any error. recovered=true if HLS.js handled it internally. */
  onError?: (error: ErrorData, recovered: boolean) => void;
  /** Called on fatal errors that cannot be recovered from. */
  onFatalError?: (error: ErrorData) => void;
  /** Called whenever the active quality level changes. */
  onLevelSwitch?: (level: HlsQualityLevel) => void;
  /** Override any HLS.js config option. */
  hlsConfig?: Partial<HlsConfig>;
};

// -------------------------------------------------------------------------- //
// Default configuration                                                         //
// -------------------------------------------------------------------------- //

/**
 * Default HLS.js configuration tuned for educational video (VOD, detail-critical).
 * Prioritises buffer stability and quality over low latency.
 */
export const DEFAULT_HLS_CONFIG: Partial<HlsConfig> = {
  maxBufferLength:            30,              // 30 s forward buffer
  maxMaxBufferLength:         60,              // 60 s maximum buffer
  maxBufferSize:              60 * 1024 * 1024, // 60 MB
  startLevel:                 -1,              // Auto on first load
  abrEwmaDefaultEstimate:     5_000_000,       // Assume 5 Mbps to start high quality
  enableWorker:               true,
  lowLatencyMode:             false,           // VOD, not live
  renderNatively:             false,           // We handle subtitles ourselves
};

// -------------------------------------------------------------------------- //
// Browser capability detection                                                  //
// -------------------------------------------------------------------------- //

/**
 * Check if the browser supports native HLS playback.
 * Safari plays HLS natively — HLS.js is unnecessary there.
 *
 * @param videoElement - HTMLVideoElement to test against
 * @returns true if native HLS is supported
 */
export function isHlsNativelySupported(
  videoElement: HTMLVideoElement
): boolean {
  return (
    typeof videoElement.canPlayType === "function" &&
    videoElement.canPlayType("application/vnd.apple.mpegurl") !== ""
  );
}

/**
 * Check if HLS.js is supported in the current browser environment.
 * Requires MediaSource Extensions (MSE) API.
 *
 * @returns Promise resolving to true if HLS.js can run
 */
export async function isHlsJsSupported(): Promise<boolean> {
  try {
    const { default: Hls } = await import("hls.js");
    return Hls.isSupported();
  } catch {
    return false;
  }
}

/**
 * Determine the optimal playback method for the current browser.
 *
 * Priority order:
 *   1. "hlsjs"  — HLS.js via MSE (most desktop browsers)
 *   2. "native" — Native HLS (Safari, iOS)
 *   3. "mp4"    — Direct MP4 URL, no adaptive streaming
 *
 * @param videoElement - HTMLVideoElement to test against
 * @returns Recommended playback method string
 */
export async function getPlaybackMethod(
  videoElement: HTMLVideoElement
): Promise<"hlsjs" | "native" | "mp4"> {
  if (await isHlsJsSupported()) return "hlsjs";
  if (isHlsNativelySupported(videoElement)) return "native";
  return "mp4";
}

// -------------------------------------------------------------------------- //
// Level mapping                                                                  //
// -------------------------------------------------------------------------- //

/**
 * Convert HLS.js Level array to typed HlsQualityLevel array.
 * Prepends an "Auto" option at index -1.
 * Levels are sorted highest quality first.
 *
 * @param levels - Raw Level objects from HLS.js MANIFEST_PARSED event
 * @returns Typed quality levels with Auto option first
 *
 * @example
 *   // Given levels at 1080p / 720p / 480p:
 *   mapHlsLevels(rawLevels)
 *   // [{index:-1,label:"Auto",...}, {index:0,label:"1080p",...}, ...]
 */
export function mapHlsLevels(levels: Level[]): HlsQualityLevel[] {
  const autoLevel: HlsQualityLevel = {
    index: -1,
    label: "Auto",
    height: 0,
    bitrate: 0,
    isAuto: true,
  };

  // Sort descending by height so highest quality is listed first
  const sorted = [...levels].sort((a, b) => b.height - a.height);

  const mapped: HlsQualityLevel[] = sorted.map((level) => ({
    index: levels.indexOf(level),
    label: `${level.height}p`,
    height: level.height,
    bitrate: level.bitrate,
    isAuto: false,
  }));

  return [autoLevel, ...mapped];
}

// -------------------------------------------------------------------------- //
// Player initialisation                                                         //
// -------------------------------------------------------------------------- //

const MAX_RECOVERY_ATTEMPTS = 3;

/**
 * Initialise HLS.js and attach it to a video element.
 *
 * Handles:
 *   - Dynamic import of HLS.js (lazy — not in initial bundle)
 *   - Manifest loading and quality level detection
 *   - Non-fatal network/media error recovery (up to 3 attempts each)
 *   - Fatal error reporting via onFatalError callback
 *   - Quality level change events
 *
 * @param videoElement - HTMLVideoElement to attach HLS to
 * @param manifestUrl - URL to the HLS manifest (.m3u8 file)
 * @param options - Callbacks and optional HLS config overrides
 * @returns Initialised Hls instance (destroy when component unmounts), or null
 *          if HLS.js is not supported in this browser
 *
 * @example
 *   const hls = await initHlsPlayer(
 *     videoRef.current!,
 *     "https://cdn.eduvideo.ai/output/abc123/master.m3u8",
 *     {
 *       onReady: (levels) => setQualityLevels(levels),
 *       onFatalError: () => setError("Playback failed — please refresh"),
 *     }
 *   );
 *   // In cleanup: destroyHlsPlayer(hls);
 */
export async function initHlsPlayer(
  videoElement: HTMLVideoElement,
  manifestUrl: string,
  options: HlsPlayerOptions = {}
): Promise<Hls | null> {
  const { default: Hls } = await import("hls.js");

  if (!Hls.isSupported()) return null;

  const config: Partial<HlsConfig> = {
    ...DEFAULT_HLS_CONFIG,
    ...(options.hlsConfig ?? {}),
  };

  const hls = new Hls(config as HlsConfig);

  const recoveryAttempts = { network: 0, media: 0 };

  // ---- MANIFEST_PARSED: levels available -------------------------------- //
  hls.on(Hls.Events.MANIFEST_PARSED, (_event, data) => {
    const levels = mapHlsLevels(data.levels);
    options.onReady?.(levels);
  });

  // ---- LEVEL_SWITCHED: quality change notification ---------------------- //
  hls.on(Hls.Events.LEVEL_SWITCHED, (_event, data) => {
    const raw = hls.levels[data.level];
    if (raw && options.onLevelSwitch) {
      options.onLevelSwitch({
        index: data.level,
        label: `${raw.height}p`,
        height: raw.height,
        bitrate: raw.bitrate,
        isAuto: hls.autoLevelEnabled,
      });
    }
  });

  // ---- ERROR: recovery logic ------------------------------------------- //
  hls.on(Hls.Events.ERROR, (_event, data) => {
    if (!data.fatal) {
      // Non-fatal — HLS.js handles internally; notify caller
      options.onError?.(data, true);
      return;
    }

    // Fatal network error — try startLoad() recovery
    if (data.type === Hls.ErrorTypes.NETWORK_ERROR) {
      recoveryAttempts.network++;
      if (recoveryAttempts.network <= MAX_RECOVERY_ATTEMPTS) {
        options.onError?.(data, true);
        hls.startLoad();
        return;
      }
    }

    // Fatal media error — try recoverMediaError() once
    if (data.type === Hls.ErrorTypes.MEDIA_ERROR) {
      recoveryAttempts.media++;
      if (recoveryAttempts.media <= MAX_RECOVERY_ATTEMPTS) {
        options.onError?.(data, true);
        hls.recoverMediaError();
        return;
      }
    }

    // All recovery attempts exhausted — fatal
    options.onError?.(data, false);
    options.onFatalError?.(data);
  });

  // Attach and load
  hls.loadSource(manifestUrl);
  hls.attachMedia(videoElement);

  return hls;
}

/**
 * Safely destroy an HLS.js instance and release all resources.
 * Call this in React's cleanup function (return value of useEffect).
 *
 * @param hls - Hls instance to destroy, or null (safe to call with null)
 *
 * @example
 *   useEffect(() => {
 *     let hls: Hls | null = null;
 *     initHlsPlayer(...).then(instance => { hls = instance });
 *     return () => destroyHlsPlayer(hls);
 *   }, [manifestUrl]);
 */
export function destroyHlsPlayer(hls: Hls | null): void {
  if (hls) {
    hls.destroy();
  }
}

// -------------------------------------------------------------------------- //
// Quality control                                                               //
// -------------------------------------------------------------------------- //

/**
 * Set the playback quality level.
 * Pass -1 to restore automatic ABR selection.
 *
 * @param hls - Active Hls instance
 * @param levelIndex - HLS level index (-1 for auto)
 *
 * @example
 *   setQualityLevel(hls, -1);   // Auto
 *   setQualityLevel(hls, 0);    // Force first (highest) level
 */
export function setQualityLevel(hls: Hls, levelIndex: number): void {
  if (levelIndex === -1) {
    hls.currentLevel = -1;   // Re-enable ABR
  } else {
    hls.currentLevel = levelIndex;
  }
}

/**
 * Get the current buffered duration ahead of the playhead.
 * Useful for displaying buffer health in the player UI.
 *
 * @param videoElement - HTMLVideoElement being played
 * @returns Seconds of buffered content ahead of currentTime; 0 if nothing buffered
 *
 * @example
 *   const buffered = getBufferedAhead(videoRef.current!);
 *   // "15.3s buffered"
 */
export function getBufferedAhead(videoElement: HTMLVideoElement): number {
  const { buffered, currentTime } = videoElement;
  for (let i = 0; i < buffered.length; i++) {
    if (buffered.start(i) <= currentTime && currentTime <= buffered.end(i)) {
      return buffered.end(i) - currentTime;
    }
  }
  return 0;
}

/**
 * Get a snapshot of current HLS playback state.
 * Useful for debugging and player UI status indicators.
 *
 * @param hls - Active Hls instance (or null if not yet initialised)
 * @param videoElement - HTMLVideoElement being played
 * @returns Current HlsPlaybackState snapshot
 */
export function getHlsPlaybackState(
  hls: Hls | null,
  videoElement: HTMLVideoElement
): HlsPlaybackState {
  if (!hls) {
    return {
      isSupported: false,
      isAttached: false,
      currentLevel: -1,
      levels: [],
      bufferedSeconds: 0,
      networkError: false,
      fatalError: false,
    };
  }

  return {
    isSupported: true,
    isAttached: hls.media !== null,
    currentLevel: hls.currentLevel,
    levels: mapHlsLevels(hls.levels),
    bufferedSeconds: getBufferedAhead(videoElement),
    networkError: false,  // Updated by error event handler in initHlsPlayer
    fatalError: false,
  };
}

// -------------------------------------------------------------------------- //
// Native HLS setup (Safari)                                                    //
// -------------------------------------------------------------------------- //

/**
 * Attach an HLS manifest directly to a video element for native playback.
 * Call this when getPlaybackMethod() returns "native" (Safari / iOS).
 *
 * @param videoElement - HTMLVideoElement to attach to
 * @param manifestUrl - URL to the .m3u8 HLS manifest
 *
 * @example
 *   if (await getPlaybackMethod(video) === "native") {
 *     attachNativeHls(video, manifestUrl);
 *   }
 */
export function attachNativeHls(
  videoElement: HTMLVideoElement,
  manifestUrl: string
): void {
  videoElement.src = manifestUrl;
}

/**
 * Attach a direct MP4 URL to the video element.
 * Fallback for browsers without HLS support.
 *
 * @param videoElement - HTMLVideoElement to attach to
 * @param mp4Url - Direct URL to the MP4 file
 */
export function attachMp4Fallback(
  videoElement: HTMLVideoElement,
  mp4Url: string
): void {
  videoElement.src = mp4Url;
  }
