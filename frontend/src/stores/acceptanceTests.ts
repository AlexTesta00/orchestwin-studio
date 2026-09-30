import { defineStore } from "pinia";

import {
  AcceptanceTestsApiError,
  acceptanceTestsApi,
  type AcceptanceTestsApi,
} from "../api/acceptanceTests";
import type {
  AcceptanceTestsOverviewPayload,
  CriterionOutcomePayload,
  TestCritiquePayload,
  TestRunPayload,
} from "../types/acceptanceTests";

export type AuthorizedRequest = <T>(operation: (accessToken: string) => Promise<T>) => Promise<T>;

export type AcceptanceTestsOperation = "load";

export interface AcceptanceTestsStoreError {
  message: string;
  code: string | null;
  status: number | null;
}

interface AcceptanceTestsState {
  projectId: string | null;
  projectEpoch: number;
  overview: AcceptanceTestsOverviewPayload | null;
  pending: Record<AcceptanceTestsOperation, boolean>;
  failure: AcceptanceTestsStoreError | null;
}

function emptyPending(): Record<AcceptanceTestsOperation, boolean> {
  return {
    load: false,
  };
}

function storeError(error: unknown): AcceptanceTestsStoreError {
  if (error instanceof AcceptanceTestsApiError) {
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
    message: "An unexpected acceptance tests error occurred",
    code: null,
    status: null,
  };
}

export const useAcceptanceTestsStore = defineStore("acceptanceTests", {
  state: (): AcceptanceTestsState => ({
    projectId: null,
    projectEpoch: 0,
    overview: null,
    pending: emptyPending(),
    failure: null,
  }),

  getters: {
    latestRun(state): TestRunPayload | null {
      return state.overview?.latest_run ?? null;
    },

    criteria(state): CriterionOutcomePayload[] {
      return state.overview?.latest_run?.criteria ?? [];
    },

    critiques(state): TestCritiquePayload[] {
      return state.overview?.latest_run?.critiques ?? [];
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
      this.pending = emptyPending();
      this.failure = null;
    },

    isCurrent(projectId: string, epoch: number): boolean {
      return this.projectId === projectId && this.projectEpoch === epoch;
    },

    async load(
      projectId: string,
      authorize: AuthorizedRequest,
      api: AcceptanceTestsApi = acceptanceTestsApi,
    ): Promise<AcceptanceTestsOverviewPayload | null> {
      this.activateProject(projectId);

      if (this.overview !== null || this.pending.load) {
        return this.overview;
      }

      const epoch = this.projectEpoch;
      this.pending.load = true;
      this.failure = null;

      try {
        const overview = await authorize((token) => api.overview(projectId, token));

        if (this.isCurrent(projectId, epoch)) {
          this.overview = overview;
        }

        return overview;
      } catch (error) {
        if (this.isCurrent(projectId, epoch)) {
          this.failure = storeError(error);
        }
        throw error;
      } finally {
        if (this.isCurrent(projectId, epoch)) {
          this.pending.load = false;
        }
      }
    },
  },
});
