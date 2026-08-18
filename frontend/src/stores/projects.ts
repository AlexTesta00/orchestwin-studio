import { ref } from "vue";
import { defineStore } from "pinia";

import { ApiError } from "@/api/client";
import type {
  AuthenticationApi,
  ProjectApi,
  ProjectBriefInput,
  ProjectBriefVersionResponse,
  ProjectCreateInput,
  ProjectResponse,
} from "@/api/contracts";
import type { useAuthStore } from "@/stores/auth";

type ApplicationApi = AuthenticationApi & ProjectApi;
type AuthStore = ReturnType<typeof useAuthStore>;

function errorCode(error: unknown): string {
  if (error instanceof ApiError) {
    return error.detail;
  }

  return "unexpected_error";
}

export const useProjectsStore = defineStore("projects", () => {
  const projects = ref<readonly ProjectResponse[]>([]);
  const currentProject = ref<ProjectResponse | null>(null);
  const currentBrief = ref<ProjectBriefVersionResponse | null>(null);
  const briefVersions = ref<readonly ProjectBriefVersionResponse[]>([]);
  const loading = ref(false);
  const errorDetail = ref<string | null>(null);

  async function loadProjects(api: ApplicationApi, auth: AuthStore): Promise<boolean> {
    loading.value = true;
    errorDetail.value = null;

    try {
      projects.value = await auth.withAccessToken(api, (token) => api.listProjects(token));
      return true;
    } catch (error: unknown) {
      errorDetail.value = errorCode(error);
      return false;
    } finally {
      loading.value = false;
    }
  }

  async function createProject(
    api: ApplicationApi,
    auth: AuthStore,
    input: ProjectCreateInput,
  ): Promise<ProjectResponse | null> {
    loading.value = true;
    errorDetail.value = null;

    try {
      const project = await auth.withAccessToken(api, (token) => api.createProject(token, input));

      projects.value = [project, ...projects.value];
      return project;
    } catch (error: unknown) {
      errorDetail.value = errorCode(error);
      return null;
    } finally {
      loading.value = false;
    }
  }

  async function loadProject(
    api: ApplicationApi,
    auth: AuthStore,
    projectId: string,
  ): Promise<boolean> {
    loading.value = true;
    errorDetail.value = null;
    currentBrief.value = null;

    try {
      currentProject.value = await auth.withAccessToken(api, (token) =>
        api.getProject(token, projectId),
      );

      briefVersions.value = await auth.withAccessToken(api, (token) =>
        api.listBriefVersions(token, projectId),
      );

      try {
        currentBrief.value = await auth.withAccessToken(api, (token) =>
          api.currentBriefVersion(token, projectId),
        );
      } catch (error: unknown) {
        if (!(error instanceof ApiError) || error.status !== 404) {
          throw error;
        }

        currentBrief.value = null;
      }

      return true;
    } catch (error: unknown) {
      currentProject.value = null;
      briefVersions.value = [];
      errorDetail.value = errorCode(error);
      return false;
    } finally {
      loading.value = false;
    }
  }

  async function saveBrief(
    api: ApplicationApi,
    auth: AuthStore,
    projectId: string,
    input: ProjectBriefInput,
  ): Promise<ProjectBriefVersionResponse | null> {
    loading.value = true;
    errorDetail.value = null;

    try {
      const version = await auth.withAccessToken(api, (token) =>
        api.createBriefVersion(token, projectId, input),
      );

      currentBrief.value = version;

      const existingIndex = briefVersions.value.findIndex(
        (candidate) => candidate.version_number === version.version_number,
      );

      briefVersions.value =
        existingIndex >= 0
          ? briefVersions.value.map((candidate) =>
              candidate.version_number === version.version_number ? version : candidate,
            )
          : [...briefVersions.value, version];

      if (currentProject.value !== null) {
        currentProject.value = {
          ...currentProject.value,
          current_brief_version: version.version_number,
        };
      }

      return version;
    } catch (error: unknown) {
      errorDetail.value = errorCode(error);
      return null;
    } finally {
      loading.value = false;
    }
  }

  function clearCurrentProject(): void {
    currentProject.value = null;
    currentBrief.value = null;
    briefVersions.value = [];
    errorDetail.value = null;
  }

  return {
    projects,
    currentProject,
    currentBrief,
    briefVersions,
    loading,
    errorDetail,
    loadProjects,
    createProject,
    loadProject,
    saveBrief,
    clearCurrentProject,
  };
});
