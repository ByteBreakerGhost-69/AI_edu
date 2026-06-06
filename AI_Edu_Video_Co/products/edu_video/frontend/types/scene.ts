/**
 * scene.ts
 * Scene-level types — maps to backend Scene model + layer4_script_visual schemas.
 */

import type { Subject, Curriculum, DifficultyLevel, Language } from "./project";

// -------------------------------------------------------------------------- //
// Renderer types                                                               //
// -------------------------------------------------------------------------- //

/**
 * Available renderer types for scene visual generation.
 * Maps to backend renderer_type field in Scene model and renderers/ package.
 */
export const RENDERER_TYPES = {
  MANIM:     "manim",
  LOTTIE:    "lottie",
  FLUX_SDXL: "flux_sdxl",
  KLING:     "kling",
  TIMELINE:  "timeline",
  DIAGRAM:   "diagram",
  GRAPH:     "graph",
  CODE:      "code",
} as const;

export type RendererType = (typeof RENDERER_TYPES)[keyof typeof RENDERER_TYPES];

/**
 * Human-readable renderer labels for admin/debug display.
 */
export const RENDERER_LABELS: Record<RendererType, string> = {
  manim:     "Mathematical Animation",
  lottie:    "Motion Graphics",
  flux_sdxl: "AI Illustration",
  kling:     "AI Video Clip",
  timeline:  "Historical Timeline",
  diagram:   "Flowchart / Diagram",
  graph:     "Chart / Graph",
  code:      "Code Animation",
};

/**
 * Renderer icon names (Lucide) for visual indicators.
 */
export const RENDERER_ICONS: Record<RendererType, string> = {
  manim:     "FunctionSquare",
  lottie:    "Sparkles",
  flux_sdxl: "Image",
  kling:     "Video",
  timeline:  "GitCommitHorizontal",
  diagram:   "Network",
  graph:     "BarChart2",
  code:      "Code2",
};

// -------------------------------------------------------------------------- //
// Scene status                                                                 //
// -------------------------------------------------------------------------- //

/**
 * Individual scene processing status.
 * Maps to backend Scene.status field in models/scene.py.
 */
export type SceneStatus =
  | "pending"   // Not yet rendered
  | "rendering" // Currently being processed by renderer
  | "done"      // Rendered successfully — animationUrl available
  | "failed";   // Render failed (black-screen fallback may have been used)

/**
 * Human-readable scene status labels.
 */
export const SCENE_STATUS_LABELS: Record<SceneStatus, string> = {
  pending:   "Pending",
  rendering: "Rendering",
  done:      "Complete",
  failed:    "Failed",
};

// -------------------------------------------------------------------------- //
// TTS and visual configuration                                                  //
// -------------------------------------------------------------------------- //

/**
 * TTS voice configuration for a scene's narration.
 * Maps to backend TTSInstructions in layer4_script_visual/schemas.py.
 */
export type TTSInstructions = {
  readonly speakingRate: number;                // 0.8–1.2; 1.0 = normal speed
  readonly pitch: "low" | "medium" | "high";
  readonly emphasisWords: readonly string[];    // Words to receive SSML emphasis
  readonly pauseAfterSentences: readonly number[]; // 0-based sentence indices
  readonly languageCode: string;               // e.g. "en-US", "id-ID", "fr-FR"
};

/**
 * Visual specification passed to the renderer for a scene.
 * Maps to backend VisualSpec in layer4_script_visual/schemas.py.
 */
export type VisualSpec = {
  readonly rendererType: RendererType;
  readonly primaryContent: string;             // LaTeX array / Mermaid / code / prompt
  readonly secondaryContent: string | null;    // Supplementary content if needed
  readonly colorPalette: readonly string[];    // Hex colors e.g. ["#1F2937", "#3B82F6"]
  readonly dimensions: {
    readonly width: number;                    // Always 1920
    readonly height: number;                   // Always 1080
  };
  readonly animationConfig: Record<string, unknown>; // Renderer-specific config dict
  readonly assetReferences: readonly string[]; // Reusable GCS asset URLs
  readonly generationPrompt: string | null;    // For flux_sdxl and kling only
};

/**
 * Fully processed and polished narration script for a scene.
 * Maps to backend RefinedScript in layer4_script_visual/schemas.py.
 */
export type RefinedScript = {
  readonly sceneIndex: number;
  readonly title: string;
  readonly narrationText: string;              // Plain text (for UI display)
  readonly narrationSsml: string;              // SSML markup (sent to TTS engine)
  readonly hookSentence: string;               // Opening sentence of the scene
  readonly keyTerms: readonly string[];        // 3–5 vocabulary/concept terms
  readonly estimatedWordCount: number;
  readonly estimatedDurationSeconds: number;
  readonly ttsInstructions: TTSInstructions;
};

// -------------------------------------------------------------------------- //
// Core scene types                                                              //
// -------------------------------------------------------------------------- //

/**
 * Individual scene within a project.
 * Maps to backend Scene model + SceneResponse Pydantic schema in models/scene.py.
 *
 * Field notes:
 *   - sceneIndex is 0-based
 *   - All cost fields in USD floating-point
 *   - All datetime fields as ISO 8601 strings
 */
export type Scene = {
  readonly id: string;                         // UUID
  readonly jobId: string;                      // UUID — foreign key to Project.id
  readonly sceneIndex: number;                 // 0-based position in final video
  readonly title: string;
  readonly narrationText: string;              // Plain text narration
  readonly visualDescription: string;          // Human-readable visual description
  readonly rendererType: RendererType;
  readonly animationUrl: string | null;        // GCS URL; null until status="done"
  readonly audioUrl: string | null;            // GCS URL for TTS audio file
  readonly subtitleSrt: string | null;         // SRT subtitle file content
  readonly durationSeconds: number | null;     // Actual rendered duration
  readonly status: SceneStatus;
  readonly renderMetadata: Record<string, unknown>; // Renderer-specific output data
  readonly llmCostUsd: number;                 // LLM cost for this scene (USD)
  readonly renderCostUsd: number;              // Rendering cost (TTS + renderer) (USD)
  readonly errorMessage: string | null;        // Populated when status="failed"
  readonly factChecked: boolean;               // Whether fact-checker approved
  readonly createdAt: string;                  // ISO 8601
  readonly updatedAt: string;                  // ISO 8601
};

/**
 * Lightweight scene summary for project detail and timeline views.
 * Does not include full narration text or metadata — optimises list rendering.
 */
export type SceneSummary = {
  readonly id: string;
  readonly sceneIndex: number;
  readonly title: string;
  readonly rendererType: RendererType;
  readonly durationSeconds: number | null;
  readonly status: SceneStatus;
  readonly thumbnailUrl: string | null;        // First frame screenshot if available
  readonly narrationPreview: string;           // First 100 chars of narrationText
};

/**
 * Final packaged scene combining script + visual spec + metadata.
 * Maps to backend FinalScenePackage in layer4_script_visual/schemas.py.
 * Used by studio editor for detailed scene inspection.
 */
export type FinalScenePackage = {
  readonly sceneIndex: number;
  readonly title: string;
  readonly refinedScript: RefinedScript;
  readonly visualSpec: VisualSpec;
  readonly rendererType: RendererType;
  readonly estimatedDurationSeconds: number;
  readonly subject: Subject;
  readonly curriculum: Curriculum;
  readonly difficultyLevel: DifficultyLevel;
  readonly language: Language;
  readonly metadata: {
    readonly jobId: string;
    readonly userId: string;
    readonly createdAt: string;               // ISO 8601
  };
};

/**
 * Scene update payload for partial regeneration.
 * Maps to backend PartialRegenRequest in layer6_delivery/partial_regen.py.
 */
export type SceneRegenRequest = {
  readonly jobId: string;
  readonly sceneIndices: readonly number[];    // Which scenes to re-render
  readonly reason: string;                     // Reason for regeneration
};

// -------------------------------------------------------------------------- //
// Subtitle types                                                               //
// -------------------------------------------------------------------------- //

/**
 * Parsed subtitle cue for video player overlay.
 * Parsed from SRT/VTT format by lib/video/subtitle-utils.ts.
 */
export type SubtitleCue = {
  readonly index: number;
  readonly startSeconds: number;
  readonly endSeconds: number;
  readonly text: string;
};

// -------------------------------------------------------------------------- //
// Type guards and utility functions                                             //
// -------------------------------------------------------------------------- //

/**
 * Type guard: scene has been successfully rendered with a video file.
 */
export function isSceneRendered(
  scene: Scene
): scene is Scene & { animationUrl: string; durationSeconds: number } {
  return (
    scene.status === "done" &&
    scene.animationUrl !== null &&
    scene.durationSeconds !== null
  );
}

/**
 * Type guard: scene failed to render.
 */
export function isSceneFailed(
  scene: Scene
): scene is Scene & { errorMessage: string } {
  return scene.status === "failed" && scene.errorMessage !== null;
}

/**
 * Calculate total duration across all scenes.
 * Returns 0 for scenes without a rendered duration.
 */
export function getTotalDuration(scenes: readonly Scene[]): number {
  return scenes.reduce((sum, s) => sum + (s.durationSeconds ?? 0), 0);
}

/**
 * Calculate total LLM + render cost across all scenes.
 * Returns amount in USD.
 */
export function getScenesTotalCost(scenes: readonly Scene[]): number {
  return scenes.reduce((sum, s) => sum + s.llmCostUsd + s.renderCostUsd, 0);
}

/**
 * Get completion percentage for a list of scenes.
 * Returns 0–100 based on how many scenes are in "done" status.
 */
export function getScenesCompletionPercent(scenes: readonly Scene[]): number {
  if (scenes.length === 0) return 0;
  const done = scenes.filter((s) => s.status === "done").length;
  return Math.round((done / scenes.length) * 100);
}

/**
 * Sort scenes by sceneIndex ascending.
 * Returns new array — does not mutate input.
 */
export function sortScenesByIndex(scenes: readonly Scene[]): Scene[] {
  return [...scenes].sort((a, b) => a.sceneIndex - b.sceneIndex);
}
