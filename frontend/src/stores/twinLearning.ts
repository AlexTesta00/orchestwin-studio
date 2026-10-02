import { defineStore } from "pinia";

import { TwinLearningApiError, twinLearningApi, type TwinLearningApi } from "../api/twinLearning";
import type { LearningTwinPayload, TwinLearningPayload } from "../types/twinLearning";

export type AuthorizedRequest = <T>(operation: (accessToken: string) => Promise<T>) => Promise<T>;

export type TwinLearningOperation = "load";

export interface TwinLearningStoreError {
  message: string;
  code: string | null;
  status: number | null;
}

interface TwinLearningState {
  projectId: string | null;
  projectEpoch: number;
  loadSequence: number;
  overview: TwinLearningPayload | null;
  absent: boolean;
  pending: Record<TwinLearningOperation, boolean>;
  failure: TwinLearningStoreError | null;
}

function emptyPending(): Record<TwinLearningOperation, boolean> {
  return {
    load: false,
  };
}

function storeError(error: unknown): TwinLearningStoreError {
  if (error instanceof TwinLearningApiError) {
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
    message: "An unexpected twin learning error occurred",
    code: null,
    status: null,
  };
}

export const useTwinLearningStore = defineStore("twinLearning", {
  state: (): TwinLearningState => ({
    projectId: null,
    projectEpoch: 0,
    loadSequence: 0,
    overview: null,
    absent: false,
    pending: emptyPending(),
    failure: null,
  }),

  getters: {
    loaded(state): boolean {
      return state.overview !== null || state.absent;
    },

    twins(state): LearningTwinPayload[] {
      return state.overview?.twins ?? [];
    },

    updateAvailable(state): boolean {
      return state.overview?.update_available === true;
    },
  },

  actions: {
    activateProject(projectId: string): void {
      if (this.projectId === projectId) {
        return;
      }

      this.projectId = projectId;
      this.projectEpoch += 1;
      this.overview = null;
      this.absent = false;
      this.pending = emptyPending();
      this.failure = null;
    },

    isCurrent(projectId: string, epoch: number): boolean {
      return this.projectId === projectId && this.projectEpoch === epoch;
    },

    async load(
      projectId: string,
      authorize: AuthorizedRequest,
      api: TwinLearningApi = twinLearningApi,
    ): Promise<TwinLearningPayload | null> {
      this.activateProject(projectId);

      if (this.loaded || this.pending.load) {
        return this.overview;
      }

      return this.readOverview(projectId, authorize, api);
    },

    async reload(
      projectId: string,
      authorize: AuthorizedRequest,
      api: TwinLearningApi = twinLearningApi,
    ): Promise<TwinLearningPayload | null> {
      this.activateProject(projectId);
      return this.readOverview(projectId, authorize, api);
    },

    async readOverview(
      projectId: string,
      authorize: AuthorizedRequest,
      api: TwinLearningApi,
    ): Promise<TwinLearningPayload | null> {
      const epoch = this.projectEpoch;
      const sequence = ++this.loadSequence;
      const latest = () => this.isCurrent(projectId, epoch) && sequence === this.loadSequence;
      this.pending.load = true;
      this.failure = null;

      try {
        const overview = await authorize((token) => api.overview(projectId, token));

        if (latest()) {
          this.overview = overview;
          this.absent = overview === null;
        }

        return overview;
      } catch (error) {
        if (latest()) {
          this.failure = storeError(error);
        }
        throw error;
      } finally {
        if (latest()) {
          this.pending.load = false;
        }
      }
    },
  },
});
