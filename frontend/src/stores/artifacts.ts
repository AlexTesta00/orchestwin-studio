import { defineStore } from "pinia";

import { ArtifactGraphApiError, artifactGraphApi, type ArtifactGraphApi } from "../api/artifacts";
import type { CrossStageArtifactGraphPayload } from "../types/artifacts";

export type AuthorizedRequest = <T>(operation: (accessToken: string) => Promise<T>) => Promise<T>;

export type ArtifactGraphOperation = "load" | "export";

export interface ArtifactGraphStoreError {
  message: string;
  code: string | null;
  status: number | null;
}

interface ArtifactGraphState {
  projectId: string | null;
  projectEpoch: number;
  graph: CrossStageArtifactGraphPayload | null;
  pending: Record<ArtifactGraphOperation, boolean>;
  error: ArtifactGraphStoreError | null;
}

function emptyPending(): Record<ArtifactGraphOperation, boolean> {
  return {
    load: false,
    export: false,
  };
}

function storeError(error: unknown): ArtifactGraphStoreError {
  if (error instanceof ArtifactGraphApiError) {
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
    message: "An unexpected Artifact Graph error occurred",
    code: null,
    status: null,
  };
}

export const useArtifactGraphStore = defineStore("artifactGraph", {
  state: (): ArtifactGraphState => ({
    projectId: null,
    projectEpoch: 0,
    graph: null,
    pending: emptyPending(),
    error: null,
  }),

  getters: {
    isBusy(state): boolean {
      return Object.values(state.pending).some(Boolean);
    },

    nodeCount(state): number {
      return state.graph?.nodes.length ?? 0;
    },

    linkCount(state): number {
      return state.graph?.links.length ?? 0;
    },

    isCompleteThroughArchitecture(state): boolean {
      return state.graph?.architecture_reference !== null && state.graph !== null;
    },
  },

  actions: {
    activateProject(projectId: string): void {
      if (this.projectId === projectId) {
        return;
      }

      this.projectId = projectId;
      this.projectEpoch += 1;
      this.graph = null;
      this.pending = emptyPending();
      this.error = null;
    },

    isCurrent(projectId: string, epoch: number): boolean {
      return this.projectId === projectId && this.projectEpoch === epoch;
    },

    begin(operation: ArtifactGraphOperation): void {
      this.pending[operation] = true;
      this.error = null;
    },

    finish(operation: ArtifactGraphOperation, projectId: string, epoch: number): void {
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
      api: ArtifactGraphApi = artifactGraphApi,
    ): Promise<CrossStageArtifactGraphPayload> {
      this.activateProject(projectId);
      const epoch = this.projectEpoch;
      this.begin("load");

      try {
        const graph = await authorize((token) => api.current(projectId, token));

        if (this.isCurrent(projectId, epoch)) {
          this.graph = graph;
        }

        return graph;
      } catch (error) {
        this.capture(error, projectId, epoch);
        throw error;
      } finally {
        this.finish("load", projectId, epoch);
      }
    },

    async exportGraph(
      projectId: string,
      authorize: AuthorizedRequest,
      api: ArtifactGraphApi = artifactGraphApi,
    ): Promise<Blob> {
      this.activateProject(projectId);
      const epoch = this.projectEpoch;
      this.begin("export");

      try {
        return await authorize((token) => api.exportCurrent(projectId, token));
      } catch (error) {
        this.capture(error, projectId, epoch);
        throw error;
      } finally {
        this.finish("export", projectId, epoch);
      }
    },
  },
});
