/**
 * project.ts
 * Core project types — maps to backend Job model + layer1_input schemas.
 * "Project" is the student-facing name; backend calls it "Job".
 */

// -------------------------------------------------------------------------- //
// Enums as const objects (better tree-shaking than TypeScript enums)          //
// -------------------------------------------------------------------------- //

/**
 * Supported academic subjects.
 * Maps to backend SubjectEnum in layer1_input/schemas.py.
 */
export const SUBJECTS = {
  MATHEMATICS:      "mathematics",
  PHYSICS:          "physics",
  CHEMISTRY:        "chemistry",
  BIOLOGY:          "biology",
  HISTORY:          "history",
  GEOGRAPHY:        "geography",
  ECONOMICS:        "economics",
  LITERATURE:       "literature",
  COMPUTER_SCIENCE: "computer_science",
  LANGUAGE:         "language",
} as const;

export type Subject = (typeof SUBJECTS)[keyof typeof SUBJECTS];

/**
 * Supported curriculum frameworks.
 * Maps to backend CurriculumEnum in layer1_input/schemas.py.
 */
export const CURRICULA = {
  IB:        "IB",
  CAMBRIDGE: "Cambridge",
  AP:        "AP",
  GENERAL:   "general",
} as const;

export type Curriculum = (typeof CURRICULA)[keyof typeof CURRICULA];

/**
 * Content difficulty levels.
 * Maps to backend DifficultyEnum in layer1_input/schemas.py.
 */
export const DIFFICULTY_LEVELS = {
  BEGINNER:     "beginner",
  INTERMEDIATE: "intermediate",
  ADVANCED:     "advanced",
} as const;

export type DifficultyLevel =
  (typeof DIFFICULTY_LEVELS)[keyof typeof DIFFICULTY_LEVELS];

/**
 * Supported output languages (BCP-47 language codes).
 * Maps to backend SUPPORTED_LANGUAGES in language_localizer.py.
 */
export const LANGUAGES = {
  ENGLISH:    "en",
  INDONESIAN: "id",
  SPANISH:    "es",
  FRENCH:     "fr",
  GERMAN:     "de",
  CHINESE:    "zh",
  ARABIC:     "ar",
  JAPANESE:   "ja",
  PORTUGUESE: "pt",
  KOREAN:     "ko",
} as const;

export type Language = (typeof LANGUAGES)[keyof typeof LANGUAGES];

/**
 * Human-readable language labels for UI display.
 */
export const LANGUAGE_LABELS: Record<Language, string> = {
  en: "English",
  id: "Indonesian",
  es: "Spanish",
  fr: "French",
  de: "German",
  zh: "Chinese (Simplified)",
  ar: "Arabic",
  ja: "Japanese",
  pt: "Portuguese",
  ko: "Korean",
};

// -------------------------------------------------------------------------- //
// Project status                                                               //
// -------------------------------------------------------------------------- //

/**
 * Project lifecycle status as a discriminated union.
 * Maps to backend Job.status field.
 * Order reflects pipeline progression from creation to delivery.
 */
export type ProjectStatus =
  | "pending"       // Created, not yet queued
  | "queued"        // In Redis queue, awaiting worker
  | "orchestrating" // Layer 2: LangGraph + agents running
  | "rendering"     // Layer 5: FFmpeg + renderers running
  | "review"        // Layer 6: Awaiting human review
  | "done"          // Delivered — video available for playback
  | "failed"        // Permanent failure — see errorMessage
  | "cancelled";    // Cancelled by user before processing

/**
 * Status groups for UI filtering and conditional rendering.
 * Use these instead of comparing status strings directly.
 */
export const PROJECT_STATUS_GROUPS = {
  active:    ["pending", "queued", "orchestrating", "rendering"] as ProjectStatus[],
  review:    ["review"] as ProjectStatus[],
  completed: ["done"] as ProjectStatus[],
  terminal:  ["failed", "cancelled"] as ProjectStatus[],
} as const;

/**
 * Human-readable status labels for UI badges and notifications.
 */
export const PROJECT_STATUS_LABELS: Record<ProjectStatus, string> = {
  pending:       "Preparing",
  queued:        "In Queue",
  orchestrating: "Generating Script",
  rendering:     "Rendering Video",
  review:        "Under Review",
  done:          "Ready",
  failed:        "Failed",
  cancelled:     "Cancelled",
};

/**
 * Tailwind CSS color classes for status badges.
 */
export const PROJECT_STATUS_COLORS: Record<ProjectStatus, string> = {
  pending:       "bg-gray-100 text-gray-600",
  queued:        "bg-blue-100 text-blue-700",
  orchestrating: "bg-indigo-100 text-indigo-700",
  rendering:     "bg-violet-100 text-violet-700",
  review:        "bg-amber-100 text-amber-700",
  done:          "bg-green-100 text-green-700",
  failed:        "bg-red-100 text-red-700",
  cancelled:     "bg-gray-100 text-gray-500",
};

// -------------------------------------------------------------------------- //
// Core project type                                                             //
// -------------------------------------------------------------------------- //

/**
 * Core project type.
 * Maps to backend Job model + JobResponse Pydantic schema.
 *
 * Field notes:
 *   - All monetary amounts in USD (floating-point)
 *   - All datetime fields as ISO 8601 strings (never Date objects)
 *   - readonly enforced — mutate via API calls, not local state
 */
export type Project = {
  readonly id: string;                          // UUID
  readonly userId: string;                      // UUID of owning user
  readonly title: string;
  readonly subject: Subject;
  readonly curriculum: Curriculum;
  readonly difficultyLevel: DifficultyLevel;
  readonly language: Language;
  readonly inputText: string | null;
  readonly inputImageUrl: string | null;        // GCS URL, null if text-only
  readonly status: ProjectStatus;
  readonly errorMessage: string | null;         // Present when status="failed"
  readonly totalCostUsd: number;                // USD float — pipeline total cost
  readonly durationSeconds: number | null;      // Final video duration; null until done
  readonly videoUrl: string | null;             // CDN URL; null until status="done"
  readonly thumbnailUrl: string | null;         // CDN URL; null until status="done"
  readonly sceneCount: number;                  // Total scenes generated
  readonly metadata: Record<string, unknown>;   // Pipeline metadata
  readonly createdAt: string;                   // ISO 8601
  readonly updatedAt: string;                   // ISO 8601
  readonly completedAt: string | null;          // ISO 8601; null until done
};

// -------------------------------------------------------------------------- //
// API request / response types                                                  //
// -------------------------------------------------------------------------- //

/**
 * Payload for creating a new project.
 * Maps to backend VideoJobRequest schema in layer1_input/schemas.py.
 *
 * Constraint: at least one of inputText or inputImageUrl must be provided.
 */
export type CreateProjectRequest = {
  title: string;                          // 3–200 characters
  subject?: Subject;                      // Auto-detected from input if omitted
  curriculum?: Curriculum;                // Auto-selected if omitted
  difficultyLevel?: DifficultyLevel;      // Defaults to "intermediate"
  language?: Language;                    // Defaults to "en"
  inputText?: string;                     // Minimum 20 characters
  inputImageUrl?: string;                 // GCS URL from prior upload step
};

/**
 * Response from successful project creation.
 * Maps to backend VideoJobResponse in layer1_input/schemas.py.
 */
export type CreateProjectResponse = {
  readonly jobId: string;                       // UUID — use as projectId in all calls
  readonly status: ProjectStatus;
  readonly title: string;
  readonly subject: Subject;
  readonly curriculum: Curriculum;
  readonly estimatedDurationSeconds: number;
  readonly queuePosition: number;               // Position in queue (1 = next)
  readonly createdAt: string;                   // ISO 8601
  readonly message: string;                     // Human-readable confirmation
};

/**
 * Lightweight status check response.
 * Used by polling hook: GET /api/v1/jobs/{job_id}/status
 */
export type ProjectStatusResponse = {
  readonly id: string;
  readonly status: ProjectStatus;
  readonly updatedAt: string;                   // ISO 8601
  readonly errorMessage: string | null;
  readonly queuePosition: number | null;        // Only present when status="queued"
  readonly videoUrl: string | null;             // Present when status="done"
  readonly thumbnailUrl: string | null;
  readonly processingTimeSeconds: number | null;
};

/**
 * Paginated project list response.
 * Maps to backend JobListResponse.
 */
export type ProjectListResponse = {
  readonly items: readonly Project[];
  readonly total: number;
  readonly page: number;
  readonly limit: number;
};

/**
 * Query parameters for project list endpoint.
 */
export type ProjectListParams = {
  page?: number;
  limit?: number;
  status?: ProjectStatus;
  subject?: Subject;
};

// -------------------------------------------------------------------------- //
// Subject UI metadata                                                           //
// -------------------------------------------------------------------------- //

/**
 * Subject display metadata for subject selector and project cards.
 */
export type SubjectMeta = {
  readonly value: Subject;
  readonly label: string;
  readonly icon: string;              // Lucide icon component name
  readonly color: string;             // Tailwind text color class
  readonly bgColor: string;           // Tailwind bg color class
  readonly availableOnFree: boolean;  // Whether free tier can access this subject
};

/**
 * Complete subject metadata for all 10 subjects.
 * availableOnFree matches billing/tier_config.py TIER_DEFINITIONS.free.allowed_subjects.
 */
export const SUBJECT_META: Record<Subject, SubjectMeta> = {
  mathematics: {
    value: "mathematics", label: "Mathematics",
    icon: "Calculator", color: "text-blue-500", bgColor: "bg-blue-50",
    availableOnFree: true,
  },
  physics: {
    value: "physics", label: "Physics",
    icon: "Zap", color: "text-orange-500", bgColor: "bg-orange-50",
    availableOnFree: true,
  },
  chemistry: {
    value: "chemistry", label: "Chemistry",
    icon: "FlaskConical", color: "text-emerald-500", bgColor: "bg-emerald-50",
    availableOnFree: true,
  },
  biology: {
    value: "biology", label: "Biology",
    icon: "Leaf", color: "text-green-500", bgColor: "bg-green-50",
    availableOnFree: true,
  },
  history: {
    value: "history", label: "History",
    icon: "Scroll", color: "text-red-500", bgColor: "bg-red-50",
    availableOnFree: false,
  },
  geography: {
    value: "geography", label: "Geography",
    icon: "Globe", color: "text-sky-500", bgColor: "bg-sky-50",
    availableOnFree: false,
  },
  economics: {
    value: "economics", label: "Economics",
    icon: "TrendingUp", color: "text-purple-500", bgColor: "bg-purple-50",
    availableOnFree: false,
  },
  literature: {
    value: "literature", label: "Literature",
    icon: "BookOpen", color: "text-amber-500", bgColor: "bg-amber-50",
    availableOnFree: false,
  },
  computer_science: {
    value: "computer_science", label: "Computer Science",
    icon: "Code2", color: "text-cyan-500", bgColor: "bg-cyan-50",
    availableOnFree: false,
  },
  language: {
    value: "language", label: "Language",
    icon: "Languages", color: "text-pink-500", bgColor: "bg-pink-50",
    availableOnFree: false,
  },
};

/**
 * Curriculum display metadata.
 */
export type CurriculumMeta = {
  readonly value: Curriculum;
  readonly label: string;
  readonly description: string;
  readonly availableOnFree: boolean;
};

export const CURRICULUM_META: Record<Curriculum, CurriculumMeta> = {
  general: {
    value: "general", label: "General",
    description: "No specific curriculum — broad educational coverage",
    availableOnFree: true,
  },
  IB: {
    value: "IB", label: "IB Diploma",
    description: "International Baccalaureate Diploma Programme (2023–2025)",
    availableOnFree: false,
  },
  Cambridge: {
    value: "Cambridge", label: "Cambridge (CAIE)",
    description: "Cambridge IGCSE, AS Level, and A Level (2023–2025)",
    availableOnFree: false,
  },
  AP: {
    value: "AP", label: "AP (College Board)",
    description: "Advanced Placement Program (2023–2025 CEDs)",
    availableOnFree: false,
  },
};

// -------------------------------------------------------------------------- //
// Type guards and utility functions                                             //
// -------------------------------------------------------------------------- //

/**
 * Type guard: project is in an active processing state.
 * Use to show progress indicators and disable user actions.
 */
export function isProjectActive(project: Project): boolean {
  return (PROJECT_STATUS_GROUPS.active as readonly ProjectStatus[]).includes(
    project.status
  );
}

/**
 * Type guard: project has a deliverable video ready for playback.
 */
export function isProjectDelivered(
  project: Project
): project is Project & { videoUrl: string; thumbnailUrl: string } {
  return project.status === "done" && project.videoUrl !== null;
}

/**
 * Type guard: project is in a terminal state (no further processing).
 */
export function isProjectTerminal(project: Project): boolean {
  return (PROJECT_STATUS_GROUPS.terminal as readonly ProjectStatus[]).includes(
    project.status
  );
}

/**
 * Type guard: project needs human review before delivery.
 */
export function isProjectUnderReview(project: Project): boolean {
  return project.status === "review";
}

/**
 * Estimate pipeline progress percentage for progress bars.
 * Returns 0–100. Not precise — intended for UI feedback only.
 */
export function getProjectProgressPercent(project: Project): number {
  const progression: Record<ProjectStatus, number> = {
    pending:       5,
    queued:        10,
    orchestrating: 30,
    rendering:     65,
    review:        85,
    done:          100,
    failed:        0,
    cancelled:     0,
  };
  return progression[project.status];
  }
