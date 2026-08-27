import { defineStore } from "pinia";

import { WebExecutionApiError, webExecutionApi, type WebExecutionApi } from "../api/webExecution";
import type {
  ApplyWebRepairProposalInput,
  CreateWebRepairProposalInput,
  CreateWebSourceRevisionInput,
  StartWebExecutionInput,
  WebBrowserEvidencePayload,
  WebExecutionAttemptPayload,
  WebExecutionReportPayload,
  WebRepairProposalPayload,
  WebSourceRevisionPayload,
} from "../types/webExecution";

export type AuthorizedWebExecutionRequest = <T>(
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

interface WebExecutionState {
  activeProjectId: string | null;
  projectEpoch: number;
  sourceRevisions: WebSourceRevisionPayload[];
  executions: WebExecutionAttemptPayload[];
  selectedRevision: WebSourceRevisionPayload | null;
  selectedExecution: WebExecutionAttemptPayload | null;
  selectedReport: WebExecutionReportPayload | null;
  browserEvidence: WebBrowserEvidencePayload | null;
  repairProposals: WebRepairProposalPayload[];
  pending: PendingOperation[];
  errorCode: string | null;
}

function errorCode(error: unknown): string {
  if (error instanceof WebExecutionApiError) {
    return error.code ?? `HTTP_${error.status}`;
  }
  return "WEB_EXECUTION_REQUEST_FAILED";
}

export const useWebExecutionStore = defineStore("webExecution", {
  state: (): WebExecutionState => ({
    activeProjectId: null,
    projectEpoch: 0,
    sourceRevisions: [],
    executions: [],
    selectedRevision: null,
    selectedExecution: null,
    selectedReport: null,
    browserEvidence: null,
    repairProposals: [],
    pending: [],
    errorCode: null,
  }),

  getters: {
    isBusy: (state): boolean => state.pending.length > 0,
    currentSourceRevision: (state): WebSourceRevisionPayload | null =>
      state.sourceRevisions[state.sourceRevisions.length - 1] ?? null,
    currentExecution: (state): WebExecutionAttemptPayload | null =>
      state.executions[state.executions.length - 1] ?? null,
  },

  actions: {
    activateProject(projectId: string): void {
      if (this.activeProjectId === projectId) {
        return;
      }
      this.activeProjectId = projectId;
      this.projectEpoch += 1;
      this.sourceRevisions = [];
      this.executions = [];
      this.selectedRevision = null;
      this.selectedExecution = null;
      this.selectedReport = null;
      this.browserEvidence = null;
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
      if (this.activeProjectId !== projectId || this.projectEpoch !== epoch) {
        return;
      }
      this.pending = this.pending.filter((item) => item !== operation);
    },

    capture(error: unknown, projectId: string, epoch: number): void {
      if (this.activeProjectId === projectId && this.projectEpoch === epoch) {
        this.errorCode = errorCode(error);
      }
    },

    async loadProject(
      projectId: string,
      authorize: AuthorizedWebExecutionRequest,
      api: WebExecutionApi = webExecutionApi,
    ): Promise<void> {
      this.activateProject(projectId);
      const epoch = this.projectEpoch;
      this.begin("load-project");
      try {
        const [revisions, executions] = await Promise.all([
          authorize((token) => api.sourceRevisions(projectId, token)),
          authorize((token) => api.executions(projectId, token)),
        ]);
        if (this.activeProjectId !== projectId || this.projectEpoch !== epoch) {
          return;
        }
        this.sourceRevisions = [...revisions].sort(
          (left, right) => left.version_number - right.version_number,
        );
        this.executions = [...executions].sort(
          (left, right) => left.attempt_number - right.attempt_number,
        );
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
      authorize: AuthorizedWebExecutionRequest,
      api: WebExecutionApi = webExecutionApi,
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
      authorize: AuthorizedWebExecutionRequest,
      api: WebExecutionApi = webExecutionApi,
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
        let browserEvidence: WebBrowserEvidencePayload | null = null;
        try {
          browserEvidence = await authorize((token) => api.browserEvidence(executionId, token));
        } catch (error: unknown) {
          if (!(error instanceof WebExecutionApiError) || error.status !== 404) {
            throw error;
          }
        }
        if (this.activeProjectId !== projectId || this.projectEpoch !== epoch) {
          return;
        }
        this.selectedExecution = execution;
        this.selectedReport = report;
        this.browserEvidence = browserEvidence;
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
      input: CreateWebSourceRevisionInput,
      authorize: AuthorizedWebExecutionRequest,
      api: WebExecutionApi = webExecutionApi,
    ): Promise<WebSourceRevisionPayload> {
      this.activateProject(projectId);
      const epoch = this.projectEpoch;
      this.begin("create-revision");
      try {
        const revision = await authorize((token) =>
          api.createSourceRevision(projectId, input, token),
        );
        if (this.activeProjectId === projectId && this.projectEpoch === epoch) {
          this.sourceRevisions = [...this.sourceRevisions, revision].sort(
            (left, right) => left.version_number - right.version_number,
          );
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
      input: StartWebExecutionInput,
      authorize: AuthorizedWebExecutionRequest,
      api: WebExecutionApi = webExecutionApi,
    ): Promise<WebExecutionAttemptPayload> {
      this.activateProject(projectId);
      const epoch = this.projectEpoch;
      this.begin("start-execution");
      try {
        const execution = await authorize((token) => api.startExecution(projectId, input, token));
        if (this.activeProjectId === projectId && this.projectEpoch === epoch) {
          this.executions = [...this.executions, execution].sort(
            (left, right) => left.attempt_number - right.attempt_number,
          );
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
      input: CreateWebRepairProposalInput,
      authorize: AuthorizedWebExecutionRequest,
      api: WebExecutionApi = webExecutionApi,
    ): Promise<WebRepairProposalPayload> {
      this.activateProject(projectId);
      const epoch = this.projectEpoch;
      this.begin("create-repair");
      try {
        const proposal = await authorize((token) =>
          api.createRepairProposal(executionId, input, token),
        );
        if (this.activeProjectId === projectId && this.projectEpoch === epoch) {
          this.repairProposals = [...this.repairProposals, proposal];
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
      input: ApplyWebRepairProposalInput,
      authorize: AuthorizedWebExecutionRequest,
      api: WebExecutionApi = webExecutionApi,
    ): Promise<WebSourceRevisionPayload> {
      this.activateProject(projectId);
      const epoch = this.projectEpoch;
      this.begin("apply-repair");
      try {
        const revision = await authorize((token) =>
          api.applyRepairProposal(executionId, proposalId, input, token),
        );
        if (this.activeProjectId === projectId && this.projectEpoch === epoch) {
          this.sourceRevisions = [...this.sourceRevisions, revision].sort(
            (left, right) => left.version_number - right.version_number,
          );
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
