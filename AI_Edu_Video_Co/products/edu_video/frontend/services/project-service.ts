/**
 * project-service.ts
 * Business logic for project creation, listing, loading, and cancellation.
 * Orchestrates: lib/api/project-api → store/ → caller (hook).
 * Never imported directly by React components — always via hooks/.
 */

import {
  createProject,
  listProjects,
  getProject,
  getProjectStatus,
  cancelProject,
  getProjectScenes,
} from "@/lib/api/project-api";
import { getQuotaStatus } from "@/lib/api/billing-api";
import { CreateProjectSchema, safeValidate } from "@/lib/validators";
import { isQuotaExceededError, isApiErrorCode } from "@/lib/utils";
import type {
  CreateProjectRequest,
  Project,
  ProjectListParams,
  ProjectStatusResponse,
} from "@/types";
import type { ApiError } from "@/lib/api/client";

// -------------------------------------------------------------------------- //
// ServiceResult — the contract for all service functions                       //
// -------------------------------------------------------------------------- //

export type ServiceResult<T = void> =
  | { success: true; data: T }
  | { success: false; error: string; fieldErrors?: Record<string, string> };

// -------------------------------------------------------------------------- //
// createNewProject                                                              //
// -------------------------------------------------------------------------- //

/**
 * Orchestrate full project creation with validation, quota check, and
 * optimistic store updates.
 *
 * Flow:
 *   1. Validate form input via Zod schema
 *   2. Sanitize text input
 *   3. Set loading state in project store
 *   4. Call createProject API
 *   5. Update project store (last created)
 *   6. Optimistically decrement quota in subscription store
 *   7. Return job_id for redirect
 *
 * @param input - Raw form values from CreateProjectForm
 * @returns ServiceResult with jobId and queuePosition on success
 */
export async function createNewProject(
  input: Record<string, unknown>
): Promise<ServiceResult<{ jobId: string; queuePosition: number }>> {
  // Step 1: Validate
  const validation = safeValidate(CreateProjectSchema, input);
  if (!validation.data) {
    return {
      success: false,
      error:       "Please fix the errors below before continuing",
      fieldErrors: validation.errors ?? undefined,
    };
  }

  const validated = validation.data;

  // Step 2: Sanitize text
  const sanitizedText = validated.inputText?.trim() || null;

  if (!sanitizedText && !validated.inputImageUrl) {
    return {
      success:     false,
      error:       "Please provide a description or upload an image",
      fieldErrors: {
        inputText: "At least 20 characters required, or upload an image",
      },
    };
  }

  // Step 3: Set loading
  const { useProjectStore }      = await import("@/store");
  const { useSubscriptionStore } = await import("@/store");

  useProjectStore.getState().setCreateLoading(true);
  useProjectStore.getState().setCreateError(null);

  try {
    // Step 4: API call
    const payload: CreateProjectRequest = {
      title:           validated.title,
      subject:         validated.subject,
      curriculum:      validated.curriculum,
      difficultyLevel: validated.difficultyLevel ?? "intermediate",
      language:        validated.language ?? "en",
      inputText:       sanitizedText ?? undefined,
      inputImageUrl:   validated.inputImageUrl ?? undefined,
    };

    const response = await createProject(payload);

    // Step 5: Update project store
    useProjectStore.getState().setLastCreatedProject(response);
    useProjectStore.getState().setCreateLoading(false);

    // Step 6: Optimistic quota decrement
    useSubscriptionStore.getState().decrementQuota();

    return {
      success: true,
      data: {
        jobId:         response.jobId,
        queuePosition: response.queuePosition,
      },
    };
  } catch (error) {
    const err = error as ApiError;
    useProjectStore.getState().setCreateLoading(false);

    if (isQuotaExceededError(error)) {
      return {
        success: false,
        error:
          "You've reached your monthly video limit. Upgrade to Premium for 50 videos/month.",
      };
    }

    if (isApiErrorCode(error, "subject_not_allowed")) {
      return {
        success:     false,
        error:       "This subject is not available on your current plan. Upgrade to access all subjects.",
        fieldErrors: { subject: "Not available on Free tier" },
      };
    }

    if (isApiErrorCode(error, "curriculum_not_allowed")) {
      return {
        success:     false,
        error:       "IB, Cambridge, and AP curricula require a Premium subscription.",
        fieldErrors: { curriculum: "Premium feature — upgrade to unlock" },
      };
    }

    if (isApiErrorCode(error, "validation_error")) {
      const detail = err.response as Record<string, unknown> | undefined;
      return {
        success:     false,
        error:       "Invalid input. Please check your form and try again.",
        fieldErrors: (detail?.["detail"] as Record<string, string>) ?? undefined,
      };
    }

    const message = err.detail ?? "Failed to create project. Please try again.";
    useProjectStore.getState().setCreateError(message);
    return { success: false, error: message };
  }
}

// -------------------------------------------------------------------------- //
// loadProjectList                                                               //
// -------------------------------------------------------------------------- //

/**
 * Load the first page of projects into the project store.
 *
 * @param params - Optional filter and pagination parameters
 * @returns ServiceResult with total count and loaded count
 */
export async function loadProjectList(
  params?: ProjectListParams
): Promise<ServiceResult<{ total: number; loaded: number }>> {
  const { useProjectStore } = await import("@/store");
  const store = useProjectStore.getState();

  store.setListLoading(true);
  store.setListError(null);

  try {
    const response = await listProjects(params);
    store.setProjects(response);

    return {
      success: true,
      data:    { total: response.total, loaded: response.items.length },
    };
  } catch (error) {
    const err = error as ApiError;
    const message = err.detail ?? "Failed to load projects. Please refresh the page.";
    store.setListError(message);
    return { success: false, error: message };
  }
}

// -------------------------------------------------------------------------- //
// loadNextPage                                                                  //
// -------------------------------------------------------------------------- //

/**
 * Append the next page of projects to the store list.
 * Used for infinite scroll / "load more" in the projects grid.
 *
 * @returns ServiceResult with hasMore boolean
 */
export async function loadNextPage(): Promise<
  ServiceResult<{ hasMore: boolean }>
> {
  const { useProjectStore } = await import("@/store");
  const state = useProjectStore.getState();

  if (state.projects.length >= state.totalProjects) {
    return { success: true, data: { hasMore: false } };
  }

  const nextPage = state.currentPage + 1;
  useProjectStore.getState().setListLoading(true);

  try {
    const response = await listProjects({
      page:   nextPage,
      limit:  state.pageLimit,
      status: state.statusFilter ?? undefined,
    });

    useProjectStore.getState().appendProjects(response);

    const totalLoaded = state.projects.length + response.items.length;
    return {
      success: true,
      data:    { hasMore: totalLoaded < response.total },
    };
  } catch (error) {
    const err = error as ApiError;
    useProjectStore.getState().setListLoading(false);
    return { success: false, error: err.detail ?? "Failed to load more projects." };
  }
}

// -------------------------------------------------------------------------- //
// loadActiveProject                                                             //
// -------------------------------------------------------------------------- //

/**
 * Load a single project into the active project slot and optionally
 * populate its scenes if the project has progressed past orchestration.
 *
 * @param projectId - UUID of the project to load
 * @returns ServiceResult with the loaded Project
 */
export async function loadActiveProject(
  projectId: string
): Promise<ServiceResult<Project>> {
  const { useProjectStore } = await import("@/store");
  const store = useProjectStore.getState();

  store.setActiveProjectLoading(true);
  store.setActiveProjectError(null);

  try {
    const project = await getProject(projectId);
    store.setActiveProject(project);

    const SCENE_AVAILABLE_STATUSES = [
      "rendering", "review", "done", "failed",
    ] as const;

    if ((SCENE_AVAILABLE_STATUSES as readonly string[]).includes(project.status)) {
      try {
        const scenes = await getProjectScenes(projectId);
        store.setActiveProjectScenes(scenes);

        // Mirror into studio store if in studio context
        const { useStudioStore } = await import("@/store");
        useStudioStore.getState().setScenes(scenes);
      } catch {
        // Scenes are non-critical — swallow error, project still loaded
      }
    }

    store.setActiveProjectLoading(false);
    return { success: true, data: project };
  } catch (error) {
    const err = error as ApiError;
    const message = err.isNotFound
      ? "This project was not found. It may have been deleted."
      : (err.detail ?? "Failed to load project.");

    store.setActiveProjectError(message);
    return { success: false, error: message };
  }
}

// -------------------------------------------------------------------------- //
// cancelActiveProject                                                           //
// -------------------------------------------------------------------------- //

/**
 * Cancel a project that is still in early pipeline stages.
 * Updates both the project list and active project in the store.
 *
 * @param projectId - UUID of project to cancel
 * @returns ServiceResult<void>
 */
export async function cancelActiveProject(
  projectId: string
): Promise<ServiceResult> {
  const { useProjectStore } = await import("@/store");

  try {
    await cancelProject(projectId);
    useProjectStore.getState().updateProject(projectId, { status: "cancelled" });
    return { success: true, data: undefined };
  } catch (error) {
    const err = error as ApiError;

    if (err.statusCode === 409) {
      return {
        success: false,
        error:   "This project is already being processed and cannot be cancelled.",
      };
    }

    return {
      success: false,
      error: err.detail ?? "Failed to cancel project. Please try again.",
    };
  }
}

// -------------------------------------------------------------------------- //
// refreshQuotaAfterError                                                        //
// -------------------------------------------------------------------------- //

/**
 * Re-fetch and sync quota status after a project creation failure.
 * Reverts the optimistic decrement to restore accurate quota display.
 *
 * @returns ServiceResult<void>
 */
export async function refreshQuotaAfterError(): Promise<ServiceResult> {
  const { useSubscriptionStore } = await import("@/store");

  // Immediately undo the optimistic decrement
  useSubscriptionStore.getState().incrementQuota();

  try {
    const freshQuota = await getQuotaStatus();
    useSubscriptionStore.getState().setQuotaStatus(freshQuota);
    return { success: true, data: undefined };
  } catch {
    // Best-effort — the optimistic revert is sufficient for UI accuracy
    return { success: true, data: undefined };
  }
}
