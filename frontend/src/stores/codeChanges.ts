import { defineStore } from "pinia";

import { CodeChangesApiError, codeChangesApi, type CodeChangesApi } from "../api/codeChanges";
import type {
  AlignmentPayload,
  ChangeReviewRunPayload,
  CodeChangePayload,
  CodeTaskPayload,
} from "../types/codeChanges";

export type AuthorizedRequest = <T>(operation: (accessToken: string) => Promise<T>) => Promise<T>;

export type CodeChangesOperation = "load" | "run";

export interface CodeChangesStoreError {
  message: string;
  code: string | null;
  status: number | null;
}

export interface DevelopmentSnapshot {
  alignment: AlignmentPayload;
  changes: CodeChangePayload[];
  tasks: CodeTaskPayload[] | null;
}

export interface ClosedTaskCounts {
  done: number;
  dropped: number;
}

interface CodeChangesState {
  projectId: string | null;
  projectEpoch: number;
  loadSequence: number;
  alignment: AlignmentPayload | null;
  changes: CodeChangePayload[];
  tasks: CodeTaskPayload[] | null;
  runs: Record<string, ChangeReviewRunPayload | null>;
  pending: Record<CodeChangesOperation, boolean>;
  error: CodeChangesStoreError | null;
}

function emptyPending(): Record<CodeChangesOperation, boolean> {
  return {
    load: false,
    run: false,
  };
}

function storeError(error: unknown): CodeChangesStoreError {
  if (error instanceof CodeChangesApiError) {
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
    message: "An unexpected code change error occurred",
    code: null,
    status: null,
  };
}

export const useCodeChangesStore = defineStore("codeChanges", {
  state: (): CodeChangesState => ({
    projectId: null,
    projectEpoch: 0,
    loadSequence: 0,
    alignment: null,
    changes: [],
    tasks: null,
    runs: {},
    pending: emptyPending(),
    error: null,
  }),

  getters: {
    isBusy(state): boolean {
      return Object.values(state.pending).some(Boolean);
    },

    pendingChanges(state): CodeChangePayload[] {
      const aligned = state.changes.findIndex((change) => change.decision?.kind === "ALIGNED");
      return aligned < 0 ? [...state.changes] : state.changes.slice(0, aligned);
    },

    openTasks(state): CodeTaskPayload[] {
      return (state.alignment?.tasks ?? []).filter((task) => task.status === "OPEN");
    },

    closedTasks(state): ClosedTaskCounts | null {
      if (state.tasks === null) {
        return null;
      }
      return {
        done: state.tasks.filter((task) => task.status === "DONE").length,
        dropped: state.tasks.filter((task) => task.status === "DROPPED").length,
      };
    },

    staleReviews(state): number {
      return state.alignment?.stale_reviews ?? 0;
    },

    latestReviewed(state): CodeChangePayload | null {
      return state.changes.find((change) => change.review !== null) ?? null;
    },

    latestRun(state): ChangeReviewRunPayload | null {
      const reviewed = state.changes.find((change) => change.review !== null);
      return reviewed === undefined ? null : (state.runs[reviewed.commit] ?? null);
    },
  },

  actions: {
    activateProject(projectId: string): void {
      if (this.projectId === projectId) {
        return;
      }

      this.projectId = projectId;
      this.projectEpoch += 1;
      this.alignment = null;
      this.changes = [];
      this.tasks = null;
      this.runs = {};
      this.pending = emptyPending();
      this.error = null;
    },

    isCurrent(projectId: string, epoch: number): boolean {
      return this.projectId === projectId && this.projectEpoch === epoch;
    },

    begin(operation: CodeChangesOperation): void {
      this.pending[operation] = true;
      this.error = null;
    },

    finish(operation: CodeChangesOperation, projectId: string, epoch: number): void {
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
      api: CodeChangesApi = codeChangesApi,
    ): Promise<DevelopmentSnapshot> {
      this.activateProject(projectId);
      const epoch = this.projectEpoch;
      const sequence = ++this.loadSequence;
      this.begin("load");

      try {
        const [alignment, list, tasks] = await Promise.all([
          authorize((token) => api.alignment(projectId, token)),
          authorize((token) => api.changes(projectId, token)),
          authorize((token) => api.tasks(projectId, token, "all")).then(
            (answer) => answer.items,
            () => null,
          ),
        ]);

        if (this.isCurrent(projectId, epoch) && sequence === this.loadSequence) {
          this.alignment = alignment;
          this.changes = [...list.items];
          this.tasks = tasks === null ? null : [...tasks];
        }

        return { alignment, changes: list.items, tasks };
      } catch (error) {
        if (sequence === this.loadSequence) {
          this.capture(error, projectId, epoch);
        }
        throw error;
      } finally {
        if (sequence === this.loadSequence) {
          this.finish("load", projectId, epoch);
        }
      }
    },

    async loadRun(
      projectId: string,
      commit: string,
      authorize: AuthorizedRequest,
      api: CodeChangesApi = codeChangesApi,
    ): Promise<ChangeReviewRunPayload | null> {
      this.activateProject(projectId);
      const epoch = this.projectEpoch;
      this.begin("run");

      try {
        const list = await authorize((token) => api.reviews(projectId, commit, token));
        const run = list.items[0] ?? null;

        if (this.isCurrent(projectId, epoch)) {
          this.runs = { ...this.runs, [commit]: run };
        }

        return run;
      } catch (error) {
        this.capture(error, projectId, epoch);
        throw error;
      } finally {
        this.finish("run", projectId, epoch);
      }
    },
  },
});
