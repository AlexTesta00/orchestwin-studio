import { defineStore } from "pinia";

import { SectionsApiError, sectionsApi, type SectionsApi } from "../api/sections";
import type { ProjectSectionsPayload, SectionsAlignmentPayload } from "../types/sections";

export type AuthorizedRequest = <T>(operation: (accessToken: string) => Promise<T>) => Promise<T>;

export type SectionsOperation = "read" | "align";

export interface SectionsStoreError {
  message: string;
  code: string | null;
  status: number | null;
}

interface SectionsState {
  projectId: string | null;
  projectEpoch: number;
  readSequence: number;
  sections: ProjectSectionsPayload | null;
  absent: boolean;
  pending: Record<SectionsOperation, boolean>;
  failure: SectionsStoreError | null;
  alignment: SectionsAlignmentPayload | null;
  alignmentFailure: SectionsStoreError | null;
}

function emptyPending(): Record<SectionsOperation, boolean> {
  return {
    read: false,
    align: false,
  };
}

function storeError(error: unknown): SectionsStoreError {
  if (error instanceof SectionsApiError) {
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
    message: "An unexpected sections error occurred",
    code: null,
    status: null,
  };
}

export const useSectionsStore = defineStore("sections", {
  state: (): SectionsState => ({
    projectId: null,
    projectEpoch: 0,
    readSequence: 0,
    sections: null,
    absent: false,
    pending: emptyPending(),
    failure: null,
    alignment: null,
    alignmentFailure: null,
  }),

  getters: {
    firstPassComplete(state): boolean {
      return state.sections?.first_pass_complete === true;
    },
  },

  actions: {
    activateProject(projectId: string): void {
      if (this.projectId === projectId) {
        return;
      }

      this.projectId = projectId;
      this.projectEpoch += 1;
      this.readSequence += 1;
      this.sections = null;
      this.absent = false;
      this.pending = emptyPending();
      this.failure = null;
      this.alignment = null;
      this.alignmentFailure = null;
    },

    isCurrent(projectId: string, epoch: number): boolean {
      return this.projectId === projectId && this.projectEpoch === epoch;
    },

    clearAlignment(): void {
      this.alignment = null;
      this.alignmentFailure = null;
    },

    async read(
      projectId: string,
      authorize: AuthorizedRequest,
      api: SectionsApi = sectionsApi,
    ): Promise<ProjectSectionsPayload | null> {
      this.activateProject(projectId);
      const epoch = this.projectEpoch;
      const sequence = ++this.readSequence;
      const latest = () => this.isCurrent(projectId, epoch) && sequence === this.readSequence;
      this.pending.read = true;
      this.failure = null;

      try {
        const sections = await authorize((token) => api.read(projectId, token));

        if (latest()) {
          this.sections = sections;
          this.absent = sections === null;
        }

        return sections;
      } catch (error) {
        if (latest()) {
          this.failure = storeError(error);
        }
        throw error;
      } finally {
        if (latest()) {
          this.pending.read = false;
        }
      }
    },

    async align(
      projectId: string,
      authorize: AuthorizedRequest,
      api: SectionsApi = sectionsApi,
    ): Promise<SectionsAlignmentPayload | null> {
      this.activateProject(projectId);

      if (this.pending.align) {
        return null;
      }

      const epoch = this.projectEpoch;
      this.pending.align = true;
      this.alignment = null;
      this.alignmentFailure = null;

      try {
        const alignment = await authorize((token) => api.align(projectId, token));

        if (this.isCurrent(projectId, epoch)) {
          this.readSequence += 1;
          this.pending.read = false;
          this.alignment = alignment;
          this.sections = alignment.sections;
          this.absent = false;
        }

        return alignment;
      } catch (error) {
        if (this.isCurrent(projectId, epoch)) {
          this.alignmentFailure = storeError(error);
        }
        throw error;
      } finally {
        if (this.isCurrent(projectId, epoch)) {
          this.pending.align = false;
        }
      }
    },
  },
});
