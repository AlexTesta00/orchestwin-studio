import { defineStore } from "pinia";

import { WorkflowRunsApiError, workflowRunsApi, type WorkflowRunsApi } from "../api/workflowRuns";
import type {
  CreateWorkflowRunInput,
  WorkflowCheckpointPayload,
  WorkflowEventPayload,
  WorkflowLifecycleAction,
  WorkflowLifecycleInput,
  WorkflowRunPayload,
} from "../types/workflowRuns";

export type AuthorizedWorkflowRequest = <T>(
  operation: (accessToken: string) => Promise<T>,
) => Promise<T>;

type PendingOperation = "load-project" | "load-run" | "create-run" | "lifecycle" | "events";

interface WorkflowRunsState {
  activeProjectId: string | null;
  projectEpoch: number;
  runs: WorkflowRunPayload[];
  selectedRun: WorkflowRunPayload | null;
  checkpoints: WorkflowCheckpointPayload[];
  events: WorkflowEventPayload[];
  pending: PendingOperation[];
  errorCode: string | null;
}

function errorCode(error: unknown): string {
  if (error instanceof WorkflowRunsApiError) {
    return error.code ?? `HTTP_${error.status}`;
  }
  return "WORKFLOW_REQUEST_FAILED";
}

function sortedRuns(items: WorkflowRunPayload[]): WorkflowRunPayload[] {
  return [...items].sort((left, right) => left.created_at.localeCompare(right.created_at));
}

function mergeEvents(
  current: WorkflowEventPayload[],
  incoming: WorkflowEventPayload[],
): WorkflowEventPayload[] {
  const bySequence = new Map<number, WorkflowEventPayload>();
  for (const event of [...current, ...incoming]) {
    const existing = bySequence.get(event.sequence_number);
    if (existing !== undefined && existing.id !== event.id) {
      throw new Error("Workflow event sequence conflict");
    }
    bySequence.set(event.sequence_number, event);
  }
  return [...bySequence.values()].sort(
    (left, right) => left.sequence_number - right.sequence_number,
  );
}

export const useWorkflowRunsStore = defineStore("workflow-runs", {
  state: (): WorkflowRunsState => ({
    activeProjectId: null,
    projectEpoch: 0,
    runs: [],
    selectedRun: null,
    checkpoints: [],
    events: [],
    pending: [],
    errorCode: null,
  }),

  getters: {
    isPending: (state): boolean => state.pending.length > 0,
    canPause: (state): boolean =>
      state.selectedRun?.status === "RUNNING" || state.selectedRun?.status === "WAITING_FOR_HUMAN",
    canResume: (state): boolean =>
      state.selectedRun?.status === "PAUSED" || state.selectedRun?.status === "PAUSED_NEEDS_HUMAN",
    canCancel: (state): boolean =>
      state.selectedRun !== null &&
      !["FAILED", "CANCELLED", "APPROVED"].includes(state.selectedRun.status),
    latestEventSequence: (state): number => state.events.at(-1)?.sequence_number ?? 0,
  },

  actions: {
    begin(operation: PendingOperation): void {
      if (!this.pending.includes(operation)) {
        this.pending.push(operation);
      }
      this.errorCode = null;
    },

    finish(operation: PendingOperation): void {
      this.pending = this.pending.filter((item) => item !== operation);
    },

    fail(operation: PendingOperation, error: unknown): never {
      this.finish(operation);
      this.errorCode = errorCode(error);
      throw error;
    },

    resetProject(projectId: string): number {
      this.activeProjectId = projectId;
      this.projectEpoch += 1;
      this.runs = [];
      this.selectedRun = null;
      this.checkpoints = [];
      this.events = [];
      this.errorCode = null;
      return this.projectEpoch;
    },

    async loadProject(
      projectId: string,
      authorize: AuthorizedWorkflowRequest,
      api: WorkflowRunsApi = workflowRunsApi,
    ): Promise<void> {
      const epoch =
        this.activeProjectId === projectId ? this.projectEpoch : this.resetProject(projectId);
      this.begin("load-project");
      try {
        const runs = await authorize((token) => api.runs(projectId, token));
        if (this.activeProjectId !== projectId || this.projectEpoch !== epoch) {
          return;
        }
        this.runs = sortedRuns(runs);
      } catch (error) {
        this.fail("load-project", error);
      } finally {
        this.finish("load-project");
      }
    },

    async createRun(
      projectId: string,
      input: CreateWorkflowRunInput,
      authorize: AuthorizedWorkflowRequest,
      api: WorkflowRunsApi = workflowRunsApi,
    ): Promise<WorkflowRunPayload> {
      this.begin("create-run");
      try {
        const run = await authorize((token) => api.createRun(projectId, input, token));
        if (this.activeProjectId !== projectId) {
          this.resetProject(projectId);
        }
        this.runs = sortedRuns([...this.runs.filter((item) => item.id !== run.id), run]);
        this.selectedRun = run;
        this.checkpoints = [];
        this.events = [];
        return run;
      } catch (error) {
        return this.fail("create-run", error);
      } finally {
        this.finish("create-run");
      }
    },

    async selectRun(
      runId: string,
      authorize: AuthorizedWorkflowRequest,
      api: WorkflowRunsApi = workflowRunsApi,
    ): Promise<void> {
      this.begin("load-run");
      try {
        const [run, checkpoints] = await Promise.all([
          authorize((token) => api.run(runId, token)),
          authorize((token) => api.checkpoints(runId, token)),
        ]);
        this.selectedRun = run;
        this.checkpoints = [...checkpoints].sort(
          (left, right) => left.sequence_number - right.sequence_number,
        );
        this.events = [];
      } catch (error) {
        this.fail("load-run", error);
      } finally {
        this.finish("load-run");
      }
    },

    async applyLifecycle(
      action: WorkflowLifecycleAction,
      input: WorkflowLifecycleInput,
      authorize: AuthorizedWorkflowRequest,
      api: WorkflowRunsApi = workflowRunsApi,
    ): Promise<WorkflowRunPayload> {
      if (this.selectedRun === null) {
        throw new Error("A workflow run must be selected before applying a lifecycle command");
      }
      const runId = this.selectedRun.id;
      this.begin("lifecycle");
      try {
        const run = await authorize((token) => api.applyLifecycle(runId, action, input, token));
        this.selectedRun = run;
        this.runs = sortedRuns([...this.runs.filter((item) => item.id !== run.id), run]);
        return run;
      } catch (error) {
        return this.fail("lifecycle", error);
      } finally {
        this.finish("lifecycle");
      }
    },

    async replayEvents(
      authorize: AuthorizedWorkflowRequest,
      api: WorkflowRunsApi = workflowRunsApi,
    ): Promise<void> {
      if (this.selectedRun === null) {
        throw new Error("A workflow run must be selected before replaying events");
      }
      this.begin("events");
      try {
        const events = await authorize((token) =>
          api.replayEvents(this.selectedRun?.id ?? "", this.latestEventSequence, token),
        );
        this.events = mergeEvents(this.events, events);
      } catch (error) {
        this.fail("events", error);
      } finally {
        this.finish("events");
      }
    },
  },
});
