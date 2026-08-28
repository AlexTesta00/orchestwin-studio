import { defineStore } from "pinia";

import { JvmExecutionApiError, jvmExecutionApi, type JvmExecutionApi } from "../api/jvmExecution";
import type {
  ApplyJvmRepairProposalInput,
  CreateJvmRepairProposalInput,
  CreateJvmSourceRevisionInput,
  JvmExecutionAttemptPayload,
  JvmExecutionReportPayload,
  JvmProfilePayload,
  JvmRepairProposalPayload,
  JvmSourceRevisionPayload,
  StartJvmExecutionInput,
} from "../types/jvmExecution";

export type AuthorizedJvmExecutionRequest = <T>(
  operation: (accessToken: string) => Promise<T>,
) => Promise<T>;

type PendingOperation =
  | "load-project"
  | "load-revision"
  | "load-execution"
  | "create-revision"
  | "start-execution"
  | "create-repair"
  | "apply-repair";

interface JvmExecutionState {
  activeProjectId: string | null;
  projectEpoch: number;
  profiles: JvmProfilePayload[];
  sourceRevisions: JvmSourceRevisionPayload[];
  executions: JvmExecutionAttemptPayload[];
  selectedRevision: JvmSourceRevisionPayload | null;
  selectedExecution: JvmExecutionAttemptPayload | null;
  selectedReport: JvmExecutionReportPayload | null;
  repairProposals: JvmRepairProposalPayload[];
  pending: PendingOperation[];
  errorCode: string | null;
}

function errorCode(error: unknown): string {
  if (error instanceof JvmExecutionApiError) {
    return error.code ?? `HTTP_${error.status}`;
  }
  return "JVM_EXECUTION_REQUEST_FAILED";
}

function sortedRevisions(items: JvmSourceRevisionPayload[]): JvmSourceRevisionPayload[] {
  return [...items].sort((left, right) => left.version_number - right.version_number);
}

function sortedExecutions(items: JvmExecutionAttemptPayload[]): JvmExecutionAttemptPayload[] {
  return [...items].sort((left, right) => left.attempt_number - right.attempt_number);
}

export const useJvmExecutionStore = defineStore("jvmExecution", {
  state: (): JvmExecutionState => ({
    activeProjectId: null,
    projectEpoch: 0,
    profiles: [],
    sourceRevisions: [],
    executions: [],
    selectedRevision: null,
    selectedExecution: null,
    selectedReport: null,
    repairProposals: [],
    pending: [],
    errorCode: null,
  }),

  getters: {
    isBusy: (state): boolean => state.pending.length > 0,
    currentSourceRevision: (state): JvmSourceRevisionPayload | null =>
      state.sourceRevisions[state.sourceRevisions.length - 1] ?? null,
    currentExecution: (state): JvmExecutionAttemptPayload | null =>
      state.executions[state.executions.length - 1] ?? null,
    selectedProfile(state): JvmProfilePayload | null {
      const target = state.selectedRevision?.target_selection.target;
      return state.profiles.find((profile) => profile.target === target) ?? null;
    },
  },

  actions: {
    activateProject(projectId: string): void {
      if (this.activeProjectId === projectId) {
        return;
      }
      this.activeProjectId = projectId;
      this.projectEpoch += 1;
      this.profiles = [];
      this.sourceRevisions = [];
      this.executions = [];
      this.selectedRevision = null;
      this.selectedExecution = null;
      this.selectedReport = null;
      this.repairProposals = [];
      this.pending = [];
      this.errorCode = null;
    },

    begin(operation: PendingOperation): void {
      if (!this.pending.includes(operation)) {
        this.pending.push(operation);
      }
      this.errorCode = null;
    },

    finish(operation: PendingOperation, projectId: string, epoch: number): void {
      if (this.activeProjectId === projectId && this.projectEpoch === epoch) {
        this.pending = this.pending.filter((item) => item !== operation);
      }
    },

    capture(error: unknown, projectId: string, epoch: number): void {
      if (this.activeProjectId === projectId && this.projectEpoch === epoch) {
        this.errorCode = errorCode(error);
      }
    },

    async loadProject(
      projectId: string,
      authorize: AuthorizedJvmExecutionRequest,
      api: JvmExecutionApi = jvmExecutionApi,
    ): Promise<void> {
      this.activateProject(projectId);
      const epoch = this.projectEpoch;
      this.begin("load-project");
      try {
        const [profiles, revisions, executions] = await Promise.all([
          authorize((token) => api.profiles(token)),
          authorize((token) => api.sourceRevisions(projectId, token)),
          authorize((token) => api.executions(projectId, token)),
        ]);
        if (this.activeProjectId !== projectId || this.projectEpoch !== epoch) {
          return;
        }
        this.profiles = [...profiles].sort((left, right) =>
          left.profile_id.localeCompare(right.profile_id),
        );
        this.sourceRevisions = sortedRevisions(revisions);
        this.executions = sortedExecutions(executions);
        this.selectedRevision = this.currentSourceRevision;
        this.selectedExecution = this.currentExecution;
        this.selectedReport = this.selectedExecution?.report ?? null;
      } catch (error: unknown) {
        this.capture(error, projectId, epoch);
        throw error;
      } finally {
        this.finish("load-project", projectId, epoch);
      }
    },

    async loadRevision(
      projectId: string,
      revisionId: string,
      authorize: AuthorizedJvmExecutionRequest,
      api: JvmExecutionApi = jvmExecutionApi,
    ): Promise<void> {
      this.activateProject(projectId);
      const epoch = this.projectEpoch;
      this.begin("load-revision");
      try {
        const revision = await authorize((token) =>
          api.sourceRevision(projectId, revisionId, token),
        );
        if (this.activeProjectId === projectId && this.projectEpoch === epoch) {
          this.selectedRevision = revision;
        }
      } catch (error: unknown) {
        this.capture(error, projectId, epoch);
        throw error;
      } finally {
        this.finish("load-revision", projectId, epoch);
      }
    },

    async loadExecution(
      projectId: string,
      executionId: string,
      authorize: AuthorizedJvmExecutionRequest,
      api: JvmExecutionApi = jvmExecutionApi,
    ): Promise<void> {
      this.activateProject(projectId);
      const epoch = this.projectEpoch;
      this.begin("load-execution");
      try {
        const [execution, report, proposals] = await Promise.all([
          authorize((token) => api.execution(executionId, token)),
          authorize((token) => api.executionReport(executionId, token)),
          authorize((token) => api.repairProposals(executionId, token)),
        ]);
        if (this.activeProjectId !== projectId || this.projectEpoch !== epoch) {
          return;
        }
        this.selectedExecution = execution;
        this.selectedReport = report;
        this.repairProposals = [...proposals];
      } catch (error: unknown) {
        this.capture(error, projectId, epoch);
        throw error;
      } finally {
        this.finish("load-execution", projectId, epoch);
      }
    },

    async createSourceRevision(
      projectId: string,
      input: CreateJvmSourceRevisionInput,
      authorize: AuthorizedJvmExecutionRequest,
      api: JvmExecutionApi = jvmExecutionApi,
    ): Promise<JvmSourceRevisionPayload> {
      this.activateProject(projectId);
      const epoch = this.projectEpoch;
      this.begin("create-revision");
      try {
        const revision = await authorize((token) =>
          api.createSourceRevision(projectId, input, token),
        );
        if (this.activeProjectId === projectId && this.projectEpoch === epoch) {
          this.sourceRevisions = sortedRevisions([
            ...this.sourceRevisions.filter((item) => item.id !== revision.id),
            revision,
          ]);
          this.selectedRevision = revision;
        }
        return revision;
      } catch (error: unknown) {
        this.capture(error, projectId, epoch);
        throw error;
      } finally {
        this.finish("create-revision", projectId, epoch);
      }
    },

    async startExecution(
      projectId: string,
      input: StartJvmExecutionInput,
      authorize: AuthorizedJvmExecutionRequest,
      api: JvmExecutionApi = jvmExecutionApi,
    ): Promise<JvmExecutionAttemptPayload> {
      this.activateProject(projectId);
      const epoch = this.projectEpoch;
      this.begin("start-execution");
      try {
        const execution = await authorize((token) => api.startExecution(projectId, input, token));
        if (this.activeProjectId === projectId && this.projectEpoch === epoch) {
          this.executions = sortedExecutions([
            ...this.executions.filter((item) => item.id !== execution.id),
            execution,
          ]);
          this.selectedExecution = execution;
          this.selectedReport = execution.report;
        }
        return execution;
      } catch (error: unknown) {
        this.capture(error, projectId, epoch);
        throw error;
      } finally {
        this.finish("start-execution", projectId, epoch);
      }
    },

    async createRepairProposal(
      projectId: string,
      executionId: string,
      input: CreateJvmRepairProposalInput,
      authorize: AuthorizedJvmExecutionRequest,
      api: JvmExecutionApi = jvmExecutionApi,
    ): Promise<JvmRepairProposalPayload> {
      this.activateProject(projectId);
      const epoch = this.projectEpoch;
      this.begin("create-repair");
      try {
        const proposal = await authorize((token) =>
          api.createRepairProposal(executionId, input, token),
        );
        if (this.activeProjectId === projectId && this.projectEpoch === epoch) {
          this.repairProposals = [
            ...this.repairProposals.filter((item) => item.id !== proposal.id),
            proposal,
          ];
        }
        return proposal;
      } catch (error: unknown) {
        this.capture(error, projectId, epoch);
        throw error;
      } finally {
        this.finish("create-repair", projectId, epoch);
      }
    },

    async applyRepairProposal(
      projectId: string,
      executionId: string,
      proposalId: string,
      input: ApplyJvmRepairProposalInput,
      authorize: AuthorizedJvmExecutionRequest,
      api: JvmExecutionApi = jvmExecutionApi,
    ): Promise<JvmSourceRevisionPayload> {
      this.activateProject(projectId);
      const epoch = this.projectEpoch;
      this.begin("apply-repair");
      try {
        const revision = await authorize((token) =>
          api.applyRepairProposal(executionId, proposalId, input, token),
        );
        if (this.activeProjectId === projectId && this.projectEpoch === epoch) {
          this.sourceRevisions = sortedRevisions([
            ...this.sourceRevisions.filter((item) => item.id !== revision.id),
            revision,
          ]);
          this.selectedRevision = revision;
        }
        return revision;
      } catch (error: unknown) {
        this.capture(error, projectId, epoch);
        throw error;
      } finally {
        this.finish("apply-repair", projectId, epoch);
      }
    },
  },
});
