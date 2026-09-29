import { defineStore } from "pinia";

import { DiagramsApiError, diagramsApi, type DiagramsApi } from "../api/diagrams";
import type {
  DiagramLocale,
  DiagramPayload,
  DiagramStage,
  ProjectDiagramsPayload,
} from "../types/diagrams";

export type AuthorizedRequest = <T>(operation: (accessToken: string) => Promise<T>) => Promise<T>;

export type DiagramsOperation = "load";

export interface DiagramsStoreError {
  message: string;
  code: string | null;
  status: number | null;
}

interface DiagramsState {
  projectId: string | null;
  projectEpoch: number;
  readSequence: number;
  locale: DiagramLocale | null;
  result: ProjectDiagramsPayload | null;
  pending: Record<DiagramsOperation, boolean>;
  error: DiagramsStoreError | null;
}

function emptyPending(): Record<DiagramsOperation, boolean> {
  return {
    load: false,
  };
}

function storeError(error: unknown): DiagramsStoreError {
  if (error instanceof DiagramsApiError) {
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
    message: "An unexpected diagrams error occurred",
    code: null,
    status: null,
  };
}

export const useDiagramsStore = defineStore("diagrams", {
  state: (): DiagramsState => ({
    projectId: null,
    projectEpoch: 0,
    readSequence: 0,
    locale: null,
    result: null,
    pending: emptyPending(),
    error: null,
  }),

  getters: {
    isBusy(state): boolean {
      return Object.values(state.pending).some(Boolean);
    },

    diagrams(state): DiagramPayload[] {
      return state.result?.diagrams ?? [];
    },

    byStage(state): (stage: DiagramStage) => DiagramPayload[] {
      return (stage) => (state.result?.diagrams ?? []).filter((diagram) => diagram.stage === stage);
    },
  },

  actions: {
    activateProject(projectId: string): void {
      if (this.projectId === projectId) {
        return;
      }

      this.projectId = projectId;
      this.projectEpoch += 1;
      this.locale = null;
      this.result = null;
      this.pending = emptyPending();
      this.error = null;
    },

    isCurrent(projectId: string, epoch: number, sequence: number): boolean {
      return (
        this.projectId === projectId &&
        this.projectEpoch === epoch &&
        this.readSequence === sequence
      );
    },

    async load(
      projectId: string,
      locale: DiagramLocale,
      authorize: AuthorizedRequest,
      api: DiagramsApi = diagramsApi,
    ): Promise<ProjectDiagramsPayload | null> {
      this.activateProject(projectId);
      const epoch = this.projectEpoch;
      const sequence = ++this.readSequence;
      this.pending.load = true;
      this.error = null;

      try {
        const result = await authorize((token) => api.current(projectId, locale, token));

        if (this.isCurrent(projectId, epoch, sequence)) {
          this.locale = locale;
          this.result = result;
        }

        return result;
      } catch (error) {
        if (error instanceof DiagramsApiError && error.status === 404) {
          if (this.isCurrent(projectId, epoch, sequence)) {
            this.locale = locale;
            this.result = null;
          }

          return null;
        }

        if (this.isCurrent(projectId, epoch, sequence)) {
          this.error = storeError(error);
        }

        throw error;
      } finally {
        if (this.isCurrent(projectId, epoch, sequence)) {
          this.pending.load = false;
        }
      }
    },

    reset(): void {
      this.projectId = null;
      this.projectEpoch += 1;
      this.locale = null;
      this.result = null;
      this.pending = emptyPending();
      this.error = null;
    },
  },
});
