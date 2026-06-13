"use client";

/**
 * use-video-player.ts
 * HTML5 video + HLS.js integration for the studio player.
 * Connects the DOM video element to the Zustand studio store.
 */

import { useEffect, useRef, useCallback, useState } from "react";
import type Hls from "hls.js";
import {
  initHlsPlayer,
  destroyHlsPlayer,
  setQualityLevel,
  getBufferedAhead,
} from "@/lib/video/hls-utils";
import { findActiveCue, parseSubtitleContent } from "@/lib/video/subtitle-utils";
import {
  snapToFrame,
  getSceneAtTime,
  VIDEO_FPS,
} from "@/lib/video/timecode";
import {
  useStudioStore,
  selectPlayback,
  selectSubtitles,
  selectCurrentScene,
  selectQuality,
} from "@/store";
import type { SubtitleCue } from "@/types";

// -------------------------------------------------------------------------- //
// Types                                                                        //
// -------------------------------------------------------------------------- //

export type VideoPlayerOptions = {
  /** HLS manifest (.m3u8) URL — enables adaptive streaming. null = skip. */
  hlsManifestUrl?:  string | null;
  /** Direct MP4 URL — used when HLS not supported or hlsManifestUrl is null. */
  mp4Url:           string;
  /** Pre-parsed subtitle cues for overlay rendering. */
  subtitleCues?:    SubtitleCue[];
  /** Per-scene durations (seconds) — for timeline scene tracking. */
  sceneDurations?:  number[];
  /** Called once video metadata is loaded. */
  onReady?:         (duration: number) => void;
  /** Called on non-recoverable playback error. */
  onError?:         (message: string) => void;
};

// -------------------------------------------------------------------------- //
// useVideoPlayer                                                               //
// -------------------------------------------------------------------------- //

/**
 * Manages the HTML5 video element + HLS.js for the studio player.
 * Syncs all playback events into the studio store.
 *
 * @param options - Player initialisation options
 * @returns videoRef (attach to <video>) + imperative controls
 *
 * @example
 *   const { videoRef, play, pause, seek, setVolume } =
 *     useVideoPlayer({ mp4Url: project.videoUrl! });
 *   return <video ref={videoRef} />;
 */
export function useVideoPlayer(options: VideoPlayerOptions) {
  const {
    hlsManifestUrl = null,
    mp4Url,
    subtitleCues    = [],
    sceneDurations  = [],
    onReady,
    onError,
  } = options;

  const videoRef     = useRef<HTMLVideoElement | null>(null);
  const hlsRef       = useRef<Hls | null>(null);
  const rafRef       = useRef<number | null>(null);
  const sortedCues   = useRef<SubtitleCue[]>([]);
  const [buffered, setBuffered] = useState(0);

  const store          = useStudioStore();
  const playback       = useStudioStore(selectPlayback);
  const { enabled: subtitlesEnabled } = useStudioStore(selectSubtitles);
  const quality        = useStudioStore(selectQuality);

  // Keep sorted cues in ref for O(log n) binary search in rAF loop
  useEffect(() => {
    sortedCues.current = [...subtitleCues].sort(
      (a, b) => a.startSeconds - b.startSeconds
    );
  }, [subtitleCues]);

  // ---------------------------------------------------------------- //
  // Initialise player                                                  //
  // ---------------------------------------------------------------- //

  useEffect(() => {
    const video = videoRef.current;
    if (!video) return;

    store.setBuffering(true);

    const init = async () => {
      try {
        if (hlsManifestUrl) {
          const hls = await initHlsPlayer(video, hlsManifestUrl, {
            onReady: (levels) => store.setAvailableQualities(levels),
            onLevelSwitch: (level) => store.setCurrentQuality(level.label),
            onFatalError: () => {
              store.setPlayerError("Video playback failed. Please refresh.");
              onError?.("Video playback failed");
              // Try MP4 fallback
              video.src = mp4Url;
            },
          });
          hlsRef.current = hls;
        } else {
          video.src = mp4Url;
        }
      } catch {
        store.setPlayerError("Failed to initialise video player.");
        onError?.("Failed to initialise video player");
      }
    };

    init();

    return () => {
      destroyHlsPlayer(hlsRef.current);
      hlsRef.current = null;
      if (rafRef.current) cancelAnimationFrame(rafRef.current);
    };
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [mp4Url, hlsManifestUrl]);

  // ---------------------------------------------------------------- //
  // Video element event listeners                                      //
  // ---------------------------------------------------------------- //

  useEffect(() => {
    const video = videoRef.current;
    if (!video) return;

    const onLoadedMetadata = () => {
      store.setDuration(video.duration);
      store.setBuffering(false);
      onReady?.(video.duration);
    };
    const onPlay        = () => store.setPlaying(true);
    const onPause       = () => store.setPlaying(false);
    const onEnded       = () => store.setPlaying(false);
    const onWaiting     = () => store.setBuffering(true);
    const onCanPlay     = () => store.setBuffering(false);
    const onVolumeChange = () => {
      store.setVolume(video.muted ? 0 : video.volume);
      store.setMuted(video.muted);
    };
    const onRateChange  = () => {
      // Zustand store only accepts valid playback rates; ignore invalid values
    };
    const onError       = () => {
      store.setPlayerError("Playback error. Please try again.");
      onError?.("Playback error");
    };

    video.addEventListener("loadedmetadata", onLoadedMetadata);
    video.addEventListener("play",           onPlay);
    video.addEventListener("pause",          onPause);
    video.addEventListener("ended",          onEnded);
    video.addEventListener("waiting",        onWaiting);
    video.addEventListener("canplay",        onCanPlay);
    video.addEventListener("volumechange",   onVolumeChange);
    video.addEventListener("ratechange",     onRateChange);
    video.addEventListener("error",          onError);

    return () => {
      video.removeEventListener("loadedmetadata", onLoadedMetadata);
      video.removeEventListener("play",           onPlay);
      video.removeEventListener("pause",          onPause);
      video.removeEventListener("ended",          onEnded);
      video.removeEventListener("waiting",        onWaiting);
      video.removeEventListener("canplay",        onCanPlay);
      video.removeEventListener("volumechange",   onVolumeChange);
      video.removeEventListener("ratechange",     onRateChange);
      video.removeEventListener("error",          onError);
    };
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  // ---------------------------------------------------------------- //
  // rAF loop: currentTime + subtitle cue + scene index + buffered     //
  // ---------------------------------------------------------------- //

  useEffect(() => {
    const tick = () => {
      const video = videoRef.current;
      if (!video) {
        rafRef.current = requestAnimationFrame(tick);
        return;
      }

      const t = snapToFrame(video.currentTime, VIDEO_FPS);
      store.setCurrentTime(t);

      // Subtitle cue lookup (O log n)
      if (subtitlesEnabled && sortedCues.current.length > 0) {
        const cue = findActiveCue(sortedCues.current, t);
        store.setCurrentCue(cue);
      } else {
        store.setCurrentCue(null);
      }

      // Scene tracking
      if (sceneDurations.length > 0) {
        const sceneIdx = getSceneAtTime(t, sceneDurations);
        if (sceneIdx >= 0 && sceneIdx !== store.currentSceneIndex) {
          store.setCurrentSceneIndex(sceneIdx);
        }
      }

      // Buffer health
      if (hlsRef.current === null) {
        setBuffered(getBufferedAhead(video));
      }

      rafRef.current = requestAnimationFrame(tick);
    };

    rafRef.current = requestAnimationFrame(tick);
    return () => {
      if (rafRef.current) cancelAnimationFrame(rafRef.current);
    };
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [subtitlesEnabled, sceneDurations]);

  // ---------------------------------------------------------------- //
  // Sync store → DOM (play/pause/volume/rate/fullscreen)              //
  // ---------------------------------------------------------------- //

  useEffect(() => {
    const video = videoRef.current;
    if (!video) return;
    if (playback.isPlaying) {
      video.play().catch(() => store.setPlaying(false));
    } else {
      video.pause();
    }
  }, [playback.isPlaying]); // eslint-disable-line react-hooks/exhaustive-deps

  useEffect(() => {
    const video = videoRef.current;
    if (!video) return;
    video.volume = playback.volume;
    video.muted  = playback.isMuted;
  }, [playback.volume, playback.isMuted]);

  useEffect(() => {
    const video = videoRef.current;
    if (!video) return;
    video.playbackRate = playback.playbackRate;
  }, [playback.playbackRate]);

  // ---------------------------------------------------------------- //
  // Imperative controls                                                //
  // ---------------------------------------------------------------- //

  const play = useCallback(() => {
    videoRef.current?.play().catch(() => store.setPlaying(false));
  }, [store]);

  const pause = useCallback(() => {
    videoRef.current?.pause();
  }, []);

  const seek = useCallback((seconds: number) => {
    const video = videoRef.current;
    if (!video) return;
    const clamped = Math.min(Math.max(0, seconds), video.duration || 0);
    video.currentTime = snapToFrame(clamped, VIDEO_FPS);
    store.seekTo(clamped);
  }, [store]);

  const setVolume = useCallback((vol: number) => {
    const video = videoRef.current;
    if (!video) return;
    video.volume = Math.min(1, Math.max(0, vol));
    video.muted  = vol === 0;
    store.setVolume(vol);
  }, [store]);

  const toggleMute = useCallback(() => {
    const video = videoRef.current;
    if (!video) return;
    video.muted = !video.muted;
    store.toggleMute();
  }, [store]);

  const setPlaybackRate = useCallback(
    (rate: 0.5 | 0.75 | 1.0 | 1.25 | 1.5 | 2.0) => {
      const video = videoRef.current;
      if (!video) return;
      video.playbackRate = rate;
      store.setPlaybackRate(rate);
    },
    [store]
  );

  const toggleFullscreen = useCallback(() => {
    const video = videoRef.current;
    if (!video) return;
    if (!document.fullscreenElement) {
      video.requestFullscreen().catch(console.error);
      store.setFullscreen(true);
    } else {
      document.exitFullscreen().catch(console.error);
      store.setFullscreen(false);
    }
  }, [store]);

  const switchQuality = useCallback((levelIndex: number) => {
    if (hlsRef.current) {
      setQualityLevel(hlsRef.current, levelIndex);
    }
  }, []);

  return {
    videoRef,
    // State
    isPlaying:     playback.isPlaying,
    currentTime:   playback.currentTimeSeconds,
    duration:      playback.durationSeconds,
    volume:        playback.volume,
    isMuted:       playback.isMuted,
    playbackRate:  playback.playbackRate,
    isFullscreen:  playback.isFullscreen,
    isBuffering:   playback.isBuffering,
    hasError:      playback.hasError,
    errorMessage:  playback.errorMessage,
    bufferedSeconds: buffered,
    currentQuality: quality.current,
    availableQualities: quality.available,
    // Controls
    play,
    pause,
    seek,
    setVolume,
    toggleMute,
    setPlaybackRate,
    toggleFullscreen,
    switchQuality,
  };
    }
