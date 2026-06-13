"use client";

/**
 * use-project-data.ts
 * Hooks for fetching, creating, and managing project data.
 * TanStack Query owns server cache; project store owns UI state.
 */

import { useCallback } from "react";
import { useRouter } from "next/navigation";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import {
  loadProjectList,
  loadActiveProject,
  cancelActiveProject,
  createNewProject,
  loadNextPage,
} from "@/services/project-service";
import {
  useProjectStore,
  selectProjectList,
  selectProjectListStatus,
  selectPagination,
  selectActiveProject,
  selectCreateFlow,
  selectProjectFilters,
} from "@/store";
import { QUERY_KEYS, ROUTES } from "@/lib/constants";
import { toast } from "@/providers";
import type { ProjectListParams, ProjectStatus } from "@/types";

// -------------------------------------------------------------------------- //
// useProjectList                                                               //
// -------------------------------------------------------------------------- //

/**
 * Fetch and manage the paginated project list with client-side filtering.
 *
 * Combines TanStack Query (server cache + background refresh) with the
 * project store (status filter, search query, pagination).
 *
 * @returns Projects, pagination state, filter setters, and load-more action
 *
 * @example
 *   const {
 *     projects, total, isLoading, hasMore,
 *     statusFilter, setStatusFilter,
 *     searchQuery, setSearchQuery,
 *     loadMore,
 *   } = useProjectList();
 */
export function useProjectList() {
  const queryClient   = useQueryClient();
  const store         = useProjectStore();
  const { statusFilter, searchQuery } = useProjectStore(selectProjectFilters);
  const projects      = useProjectStore(selectProjectList);
  const listStatus    = useProjectStore(selectProjectListStatus);
  const pagination    = useProjectStore(selectPagination);

  const params: ProjectListParams = {
    page:   1,
    limit:  pagination.pageLimit,
    status: statusFilter ?? undefined,
  };

  const { isLoading, error, refetch } = useQuery({
    queryKey: QUERY_KEYS.projects.list(params as Record<string, unknown>),
    queryFn:  () => loadProjectList(params),
    staleTime: 2 * 60 * 1_000,
  });

  // Client-side search filter (title + subject match)
  const filteredProjects = searchQuery.trim()
    ? projects.filter(
        (p) =>
          p.title.toLowerCase().includes(searchQuery.toLowerCase()) ||
          p.subject.toLowerCase().includes(searchQuery.toLowerCase())
      )
    : projects;

  const setStatusFilter = useCallback(
    (status: ProjectStatus | null) => {
      store.setStatusFilter(status);
      queryClient.invalidateQueries({ queryKey: QUERY_KEYS.projects.all() });
    },
    [store, queryClient]
  );

  const setSearchQuery = useCallback(
    (query: string) => store.setSearchQuery(query),
    [store]
  );

  const handleLoadMore = useCallback(async () => {
    if (pagination.currentPage >= pagination.totalPages) return;
    await loadNextPage();
  }, [pagination.currentPage, pagination.totalPages]);

  return {
    projects:       filteredProjects,
    total:          pagination.totalProjects,
    currentPage:    pagination.currentPage,
    totalPages:     pagination.totalPages,
    hasMore:        pagination.currentPage < pagination.totalPages,
    isLoading:      isLoading || listStatus.loading,
    error:          error?.message ?? listStatus.error,
    hasLoadedOnce:  listStatus.hasLoadedOnce,
    statusFilter,
    searchQuery,
    setStatusFilter,
    setSearchQuery,
    loadMore:       handleLoadMore,
    refetch,
  };
}

// -------------------------------------------------------------------------- //
// useActiveProject                                                             //
// -------------------------------------------------------------------------- //

/**
 * Load and track a single project by ID.
 * Hydrates scenes when project has progressed past orchestration.
 *
 * @param projectId - UUID of the project to load, or undefined to skip
 * @returns Project data, scenes, loading state, cancel action
 *
 * @example
 *   const { project, scenes, isLoading, cancel } =
 *     useActiveProject(params.id);
 */
export function useActiveProject(projectId: string | undefined) {
  const queryClient = useQueryClient();
  const { project, scenes, loading, error } = useProjectStore(selectActiveProject);

  const { isLoading, refetch } = useQuery({
    queryKey: QUERY_KEYS.projects.detail(projectId ?? ""),
    queryFn:  () => loadActiveProject(projectId!),
    enabled:  Boolean(projectId),
    staleTime: 60_000,
    retry: (count, err) => {
      const apiErr = err as { statusCode?: number };
      if (apiErr.statusCode === 404) return false;
      return count < 2;
    },
  });

  const cancelMutation = useMutation({
    mutationFn: () => cancelActiveProject(projectId!),
    onSuccess: () => {
      toast.success("Project cancelled");
      queryClient.invalidateQueries({ queryKey: QUERY_KEYS.projects.all() });
    },
    onError: (err: Error) => {
      toast.error(err.message ?? "Failed to cancel project");
    },
  });

  return {
    project,
    scenes,
    isLoading:    isLoading || loading,
    error,
    cancel:       cancelMutation.mutate,
    isCancelling: cancelMutation.isPending,
    refetch,
  };
}

// -------------------------------------------------------------------------- //
// useCreateProject                                                             //
// -------------------------------------------------------------------------- //

/**
 * Project creation form hook.
 * Submits via service, shows toasts, redirects to studio on success.
 *
 * @returns submit handler, loading/error state, modal controls
 *
 * @example
 *   const { submit, isLoading, error, modalOpen, openModal } =
 *     useCreateProject();
 */
export function useCreateProject() {
  const router      = useRouter();
  const queryClient = useQueryClient();
  const store       = useProjectStore();
  const { loading, error, modalOpen } = useProjectStore(selectCreateFlow);

  const submit = useCallback(
    async (formValues: Record<string, unknown>) => {
      const result = await createNewProject(formValues);

      if (result.success) {
        store.setCreateModalOpen(false);
        queryClient.invalidateQueries({ queryKey: QUERY_KEYS.projects.all() });
        toast.success("Video project created!", {
          description: `Position ${result.data.queuePosition} in queue`,
        });
        router.push(ROUTES.studio(result.data.jobId));
      } else {
        toast.error(result.error);
      }

      return result;
    },
    [store, queryClient, router]
  );

  return {
    submit,
    isLoading:  loading,
    error,
    modalOpen,
    openModal:  () => store.setCreateModalOpen(true),
    closeModal: () => store.setCreateModalOpen(false),
  };
    }
