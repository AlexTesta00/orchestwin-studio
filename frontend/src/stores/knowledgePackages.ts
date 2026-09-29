import { defineStore } from "pinia";

import {
  KnowledgePackagesApiError,
  knowledgePackagesApi,
  type KnowledgePackagesApi,
} from "../api/knowledgePackages";
import type {
  KnowledgePackageDownload,
  KnowledgePackagePublicationPayload,
  KnowledgePackageVersionPayload,
} from "../types/knowledgePackages";

export type AuthorizedRequest = <T>(operation: (accessToken: string) => Promise<T>) => Promise<T>;

export type KnowledgePackagesOperation = "load" | "publish" | "download";

export interface KnowledgePackagesStoreError {
  message: string;
  code: string | null;
  status: number | null;
}

interface KnowledgePackagesState {
  projectId: string | null;
  projectEpoch: number;
  versions: KnowledgePackageVersionPayload[];
  lastPublication: KnowledgePackagePublicationPayload | null;
  pending: Record<KnowledgePackagesOperation, boolean>;
  error: KnowledgePackagesStoreError | null;
}

function emptyPending(): Record<KnowledgePackagesOperation, boolean> {
  return {
    load: false,
    publish: false,
    download: false,
  };
}

function storeError(error: unknown): KnowledgePackagesStoreError {
  if (error instanceof KnowledgePackagesApiError) {
    return {
      message: error.message,
      code: error.code,
      status: error.status,
    };
  }

  if (error instanceof Error) {
    return {
      message: error.message,
      code: null,
      status: null,
    };
  }

  return {
    message: "An unexpected knowledge package error occurred",
    code: null,
    status: null,
  };
}

function withVersionFirst(
  versions: KnowledgePackageVersionPayload[],
  candidate: KnowledgePackageVersionPayload,
): KnowledgePackageVersionPayload[] {
  return [candidate, ...versions.filter((version) => version.id !== candidate.id)];
}

function withPublication(
  versions: KnowledgePackageVersionPayload[],
  publication: KnowledgePackagePublicationPayload | null,
): KnowledgePackageVersionPayload[] {
  if (publication === null || versions.some((version) => version.id === publication.version.id)) {
    return [...versions];
  }

  return withVersionFirst(versions, publication.version);
}

export const useKnowledgePackagesStore = defineStore("knowledgePackages", {
  state: (): KnowledgePackagesState => ({
    projectId: null,
    projectEpoch: 0,
    versions: [],
    lastPublication: null,
    pending: emptyPending(),
    error: null,
  }),

  getters: {
    isBusy(state): boolean {
      return Object.values(state.pending).some(Boolean);
    },

    latest(state): KnowledgePackageVersionPayload | null {
      return state.versions[0] ?? null;
    },
  },

  actions: {
    activateProject(projectId: string): void {
      if (this.projectId === projectId) {
        return;
      }

      this.projectId = projectId;
      this.projectEpoch += 1;
      this.versions = [];
      this.lastPublication = null;
      this.pending = emptyPending();
      this.error = null;
    },

    isCurrent(projectId: string, epoch: number): boolean {
      return this.projectId === projectId && this.projectEpoch === epoch;
    },

    begin(operation: KnowledgePackagesOperation): void {
      this.pending[operation] = true;
      this.error = null;
    },

    finish(operation: KnowledgePackagesOperation, projectId: string, epoch: number): void {
      if (this.isCurrent(projectId, epoch)) {
        this.pending[operation] = false;
      }
    },

    capture(error: unknown, projectId: string, epoch: number): void {
      if (this.isCurrent(projectId, epoch)) {
        this.error = storeError(error);
      }
    },

    async load(
      projectId: string,
      authorize: AuthorizedRequest,
      api: KnowledgePackagesApi = knowledgePackagesApi,
    ): Promise<KnowledgePackageVersionPayload[]> {
      this.activateProject(projectId);
      const epoch = this.projectEpoch;
      this.begin("load");

      try {
        const history = await authorize((token) => api.history(projectId, token));

        if (this.isCurrent(projectId, epoch)) {
          this.versions = withPublication(history.versions, this.lastPublication);
        }

        return history.versions;
      } catch (error) {
        if (error instanceof KnowledgePackagesApiError && error.status === 404) {
          if (this.isCurrent(projectId, epoch)) this.versions = [];
          return [];
        }
        this.capture(error, projectId, epoch);
        throw error;
      } finally {
        this.finish("load", projectId, epoch);
      }
    },

    async publish(
      projectId: string,
      authorize: AuthorizedRequest,
      api: KnowledgePackagesApi = knowledgePackagesApi,
    ): Promise<KnowledgePackagePublicationPayload> {
      this.activateProject(projectId);
      const epoch = this.projectEpoch;
      this.begin("publish");

      try {
        const publication = await authorize((token) => api.publish(projectId, token));

        if (this.isCurrent(projectId, epoch)) {
          this.lastPublication = publication;
          this.versions = withVersionFirst(this.versions, publication.version);
        }

        return publication;
      } catch (error) {
        this.capture(error, projectId, epoch);
        throw error;
      } finally {
        this.finish("publish", projectId, epoch);
      }
    },

    async download(
      projectId: string,
      versionNumber: number,
      authorize: AuthorizedRequest,
      api: KnowledgePackagesApi = knowledgePackagesApi,
    ): Promise<KnowledgePackageDownload> {
      this.activateProject(projectId);
      const epoch = this.projectEpoch;
      this.begin("download");

      try {
        return await authorize((token) => api.download(projectId, versionNumber, token));
      } catch (error) {
        this.capture(error, projectId, epoch);
        throw error;
      } finally {
        this.finish("download", projectId, epoch);
      }
    },
  },
});
