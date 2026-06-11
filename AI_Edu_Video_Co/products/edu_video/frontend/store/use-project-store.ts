/**
 * use-project-store.ts
 * Global state for the project list, active project, and creation flow.
 * TanStack Query owns the server cache — this store owns client UI state
 * and optimistic updates.
 */

import { create } from "zustand";
import { devtools } from "zustand/middleware";
import type {
  Project,
  ProjectStatus,
  ProjectListResponse,
  CreateProjectResponse,
  Scene,
} from "@/types";

// -------------------------------------------------------------------------- //
// State + Actions types                                                         //
// -------------------------------------------------------------------------- //

type ProjectState = {
  // Project list
  projects:       Project[];
  totalProjects:  number;
  currentPage:    number;
  pageLimit:      number;
  listLoading:    boolean;
  listError:      string | null;
  hasLoadedOnce:  boolean;

  // Active project
  activeProject:         Project | null;
  activeProjectScenes:   Scene[];
  activeProjectLoading:  boolean;
  activeProjectError:    string | null;

  // Creation flow
  createLoading:       boolean;
  createError:         string | null;
  lastCreatedProject:  CreateProjectResponse | null;

  // UI
  statusFilter:     ProjectStatus | null;
  searchQuery:      string;
  createModalOpen:  boolean;
};

type ProjectActions = {
  // List management
  /** Replace list with a fresh page of results. */
  setProjects:      (response: ProjectListResponse) => void;
  /** Append to existing list (infinite scroll / load more). */
  appendProjects:   (response: ProjectListResponse) => void;
  setListLoading:   (loading: boolean) => void;
  setListError:     (error: string | null) => void;
  setPage:          (page: number) => void;

  // Active project
  setActiveProject:             (project: Project | null) => void;
  setActiveProjectScenes:       (scenes: Scene[]) => void;
  /** Update status (and optionally other fields) for the active project,
   *  keeping the projects list in sync. */
  updateActiveProjectStatus:    (status: ProjectStatus, extra?: Partial<Project>) => void;
  setActiveProjectLoading:      (loading: boolean) => void;
  setActiveProjectError:        (error: string | null) => void;

  // Project CRUD (optimistic)
  addProject:     (project: Project) => void;
  updateProject:  (projectId: string, updates: Partial<Project>) => void;
  removeProject:  (projectId: string) => void;

  // Creation flow
  setCreateLoading:       (loading: boolean) => void;
  setCreateError:         (error: string | null) => void;
  setLastCreatedProject:  (response: CreateProjectResponse | null) => void;

  // UI
  setStatusFilter:      (status: ProjectStatus | null) => void;
  setSearchQuery:       (query: string) => void;
  setCreateModalOpen:   (open: boolean) => void;

  // Reset
  reset:              () => void;
  resetActiveProject: () => void;
};

// -------------------------------------------------------------------------- //
// Initial state                                                                 //
// -------------------------------------------------------------------------- //

const INITIAL_STATE: ProjectState = {
  projects:              [],
  totalProjects:         0,
  currentPage:           1,
  pageLimit:             20,
  listLoading:           false,
  listError:             null,
  hasLoadedOnce:         false,
  activeProject:         null,
  activeProjectScenes:   [],
  activeProjectLoading:  false,
  activeProjectError:    null,
  createLoading:         false,
  createError:           null,
  lastCreatedProject:    null,
  statusFilter:          null,
  searchQuery:           "",
  createModalOpen:       false,
};

// -------------------------------------------------------------------------- //
// Store                                                                         //
// -------------------------------------------------------------------------- //

export const useProjectStore = create<ProjectState & ProjectActions>()(
  devtools(
    (set, get) => ({
      ...INITIAL_STATE,

      // ------------------------------------------------------------------- //
      // List management                                                        //
      // ------------------------------------------------------------------- //

      setProjects: (response) =>
        set(
          {
            projects:      response.items,
            totalProjects: response.total,
            currentPage:   response.page,
            pageLimit:     response.limit,
            hasLoadedOnce: true,
            listError:     null,
          },
          false,
          "setProjects"
        ),

      appendProjects: (response) =>
        set(
          (s) => ({
            projects:      [...s.projects, ...response.items],
            totalProjects: response.total,
            currentPage:   response.page,
            hasLoadedOnce: true,
          }),
          false,
          "appendProjects"
        ),

      setListLoading: (loading) =>
        set({ listLoading: loading }, false, "setListLoading"),

      setListError: (error) =>
        set({ listError: error, listLoading: false }, false, "setListError"),

      setPage: (page) =>
        set({ currentPage: page }, false, "setPage"),

      // ------------------------------------------------------------------- //
      // Active project                                                         //
      // ------------------------------------------------------------------- //

      setActiveProject: (project) =>
        set(
          (s) => ({
            activeProject:       project,
            activeProjectError:  null,
            activeProjectScenes: project === null ? [] : s.activeProjectScenes,
          }),
          false,
          "setActiveProject"
        ),

      setActiveProjectScenes: (scenes) =>
        set({ activeProjectScenes: scenes }, false, "setActiveProjectScenes"),

      updateActiveProjectStatus: (status, extra = {}) =>
        set(
          (s) => {
            if (!s.activeProject) return {};
            const updated: Project = { ...s.activeProject, status, ...extra };
            return {
              activeProject: updated,
              projects:      s.projects.map((p) =>
                p.id === updated.id ? updated : p
              ),
            };
          },
          false,
          "updateActiveProjectStatus"
        ),

      setActiveProjectLoading: (loading) =>
        set({ activeProjectLoading: loading }, false, "setActiveProjectLoading"),

      setActiveProjectError: (error) =>
        set(
          { activeProjectError: error, activeProjectLoading: false },
          false,
          "setActiveProjectError"
        ),

      // ------------------------------------------------------------------- //
      // Project CRUD                                                           //
      // ------------------------------------------------------------------- //

      addProject: (project) =>
        set(
          (s) => ({
            projects:      [project, ...s.projects],
            totalProjects: s.totalProjects + 1,
          }),
          false,
          "addProject"
        ),

      updateProject: (projectId, updates) =>
        set(
          (s) => ({
            projects: s.projects.map((p) =>
              p.id === projectId ? { ...p, ...updates } : p
            ),
            activeProject:
              s.activeProject?.id === projectId
                ? { ...s.activeProject, ...updates }
                : s.activeProject,
          }),
          false,
          "updateProject"
        ),

      removeProject: (projectId) =>
        set(
          (s) => ({
            projects:      s.projects.filter((p) => p.id !== projectId),
            totalProjects: Math.max(0, s.totalProjects - 1),
            activeProject:
              s.activeProject?.id === projectId ? null : s.activeProject,
          }),
          false,
          "removeProject"
        ),

      // ------------------------------------------------------------------- //
      // Creation flow                                                          //
      // ------------------------------------------------------------------- //

      setCreateLoading: (loading) =>
        set({ createLoading: loading }, false, "setCreateLoading"),

      setCreateError: (error) =>
        set(
          { createError: error, createLoading: false },
          false,
          "setCreateError"
        ),

      setLastCreatedProject: (response) =>
        set({ lastCreatedProject: response }, false, "setLastCreatedProject"),

      // ------------------------------------------------------------------- //
      // UI                                                                     //
      // ------------------------------------------------------------------- //

      setStatusFilter: (status) =>
        set(
          { statusFilter: status, currentPage: 1 },
          false,
          "setStatusFilter"
        ),

      setSearchQuery: (query) =>
        set(
          { searchQuery: query, currentPage: 1 },
          false,
          "setSearchQuery"
        ),

      setCreateModalOpen: (open) =>
        set(
          (s) => ({
            createModalOpen: open,
            createError:     open ? null : s.createError,
          }),
          false,
          "setCreateModalOpen"
        ),

      // ------------------------------------------------------------------- //
      // Reset                                                                  //
      // ------------------------------------------------------------------- //

      reset: () => set(INITIAL_STATE, false, "reset"),

      resetActiveProject: () =>
        set(
          {
            activeProject:        null,
            activeProjectScenes:  [],
            activeProjectLoading: false,
            activeProjectError:   null,
          },
          false,
          "resetActiveProject"
        ),
    }),
    { name: "EduVideo:Projects" }
  )
);

// -------------------------------------------------------------------------- //
// Selectors                                                                     //
// -------------------------------------------------------------------------- //

type S = ProjectState & ProjectActions;

/** Project list — avoids re-renders from active project changes. */
export const selectProjectList = (s: S) => s.projects;

/** Loading / error / first-load state for the list. */
export const selectProjectListStatus = (s: S) => ({
  loading:       s.listLoading,
  error:         s.listError,
  hasLoadedOnce: s.hasLoadedOnce,
});

/** Pagination state + computed totalPages. */
export const selectPagination = (s: S) => ({
  currentPage:   s.currentPage,
  pageLimit:     s.pageLimit,
  totalProjects: s.totalProjects,
  totalPages:    Math.ceil(s.totalProjects / s.pageLimit),
});

/** Active project + its scenes + loading state. */
export const selectActiveProject = (s: S) => ({
  project: s.activeProject,
  scenes:  s.activeProjectScenes,
  loading: s.activeProjectLoading,
  error:   s.activeProjectError,
});

/** Creation flow state. */
export const selectCreateFlow = (s: S) => ({
  loading:     s.createLoading,
  error:       s.createError,
  lastCreated: s.lastCreatedProject,
  modalOpen:   s.createModalOpen,
});

/** Current filter/search state. */
export const selectProjectFilters = (s: S) => ({
  statusFilter: s.statusFilter,
  searchQuery:  s.searchQuery,
});

/** Find a project by ID from the list. Returns undefined if not present. */
export const selectProjectById =
  (projectId: string) =>
  (s: S): Project | undefined =>
    s.projects.find((p) => p.id === projectId);

/** True if there are more pages to load. */
export const selectHasMorePages = (s: S): boolean =>
  s.projects.length < s.totalProjects;
