import { defineStore } from "pinia";

import { finalizationApi, FinalizationApiError, type FinalizationApi } from "../api/finalization";
import type {
  CreateFinalExportInput,
  DecideFinalApprovalInput,
  EvaluationAggregationPayload,
  FinalApprovalPayload,
  FinalExportDownloadPayload,
  FinalExportPayload,
  FinalReviewPayload,
  SubmitFinalReviewInput,
  SyntheticEvaluationRunPayload,
  SyntheticFindingPayload,
} from "../types/finalization";

export type AuthorizedFinalizationRequest = <T>(
  operation: (accessToken: string) => Promise<T>,
) => Promise<T>;

interface FinalizationStoreState {
  evaluationRun: SyntheticEvaluationRunPayload | null;
  findings: SyntheticFindingPayload[];
  aggregation: EvaluationAggregationPayload | null;
  finalReviews: FinalReviewPayload[];
  selectedReview: FinalReviewPayload | null;
  finalApproval: FinalApprovalPayload | null;
  exportBundle: FinalExportPayload | null;
  busyOperations: string[];
  error: string | null;
}

function errorMessage(error: unknown): string {
  if (error instanceof FinalizationApiError) {
    return error.code ?? error.message;
  }
  return error instanceof Error ? error.message : "FINALIZATION_REQUEST_FAILED";
}

function sortedReviews(reviews: FinalReviewPayload[]): FinalReviewPayload[] {
  return [...reviews].sort((left, right) => left.version_number - right.version_number);
}

export const useFinalizationStore = defineStore("finalization", {
  state: (): FinalizationStoreState => ({
    evaluationRun: null,
    findings: [],
    aggregation: null,
    finalReviews: [],
    selectedReview: null,
    finalApproval: null,
    exportBundle: null,
    busyOperations: [],
    error: null,
  }),

  getters: {
    isBusy: (state) => state.busyOperations.length > 0,
    deterministicFindings: (state) =>
      state.findings.filter((finding) => finding.origin === "DETERMINISTIC"),
    modelGeneratedFindings: (state) =>
      state.findings.filter((finding) => finding.origin !== "DETERMINISTIC"),
    latestReview: (state) => state.finalReviews.at(-1) ?? null,
    canSubmitGate8(): boolean {
      return this.selectedReview?.ready_for_gate8 === true && this.finalApproval === null;
    },
    ownerApprovalIsEmpiricalValidation: () => false,
  },

  actions: {
    begin(operation: string): void {
      if (!this.busyOperations.includes(operation)) {
        this.busyOperations.push(operation);
      }
      this.error = null;
    },

    finish(operation: string): void {
      this.busyOperations = this.busyOperations.filter((item) => item !== operation);
    },

    fail(error: unknown): never {
      this.error = errorMessage(error);
      throw error;
    },

    async loadEvaluation(
      evaluationRunId: string,
      authorize: AuthorizedFinalizationRequest,
      api: FinalizationApi = finalizationApi,
    ): Promise<void> {
      this.begin("evaluation");
      try {
        const [run, findings, aggregation] = await Promise.all([
          authorize((token) => api.evaluationRun(evaluationRunId, token)),
          authorize((token) => api.findings(evaluationRunId, token)),
          authorize((token) => api.aggregation(evaluationRunId, token)),
        ]);
        this.evaluationRun = run;
        this.findings = findings;
        this.aggregation = aggregation;
      } catch (error) {
        this.fail(error);
      } finally {
        this.finish("evaluation");
      }
    },

    async loadFinalReviews(
      projectId: string,
      authorize: AuthorizedFinalizationRequest,
      api: FinalizationApi = finalizationApi,
    ): Promise<void> {
      this.begin("reviews");
      try {
        this.finalReviews = sortedReviews(
          await authorize((token) => api.finalReviews(projectId, token)),
        );
        this.selectedReview = this.finalReviews.at(-1) ?? null;
      } catch (error) {
        this.fail(error);
      } finally {
        this.finish("reviews");
      }
    },

    selectReview(reviewId: string): void {
      this.selectedReview =
        this.finalReviews.find((review) => review.review_id === reviewId) ?? null;
      this.finalApproval = null;
    },

    async submitGate8(
      input: SubmitFinalReviewInput,
      authorize: AuthorizedFinalizationRequest,
      api: FinalizationApi = finalizationApi,
    ): Promise<FinalApprovalPayload> {
      if (this.selectedReview === null) {
        throw new Error("A final review must be selected before Gate 8 submission");
      }
      this.begin("gate8");
      try {
        this.finalApproval = await authorize((token) =>
          api.submitFinalReview(this.selectedReview?.review_id ?? "", input, token),
        );
        return this.finalApproval;
      } catch (error) {
        return this.fail(error);
      } finally {
        this.finish("gate8");
      }
    },

    async decideGate8(
      input: DecideFinalApprovalInput,
      authorize: AuthorizedFinalizationRequest,
      api: FinalizationApi = finalizationApi,
    ): Promise<FinalApprovalPayload> {
      if (this.finalApproval === null) {
        throw new Error("Gate 8 must be submitted before an owner decision");
      }
      this.begin("gate8-decision");
      try {
        this.finalApproval = await authorize((token) =>
          api.decideFinalApproval(this.finalApproval?.gate_id ?? "", input, token),
        );
        return this.finalApproval;
      } catch (error) {
        return this.fail(error);
      } finally {
        this.finish("gate8-decision");
      }
    },

    async createExport(
      projectId: string,
      input: CreateFinalExportInput,
      authorize: AuthorizedFinalizationRequest,
      api: FinalizationApi = finalizationApi,
    ): Promise<FinalExportPayload> {
      this.begin("export");
      try {
        this.exportBundle = await authorize((token) => api.createExport(projectId, input, token));
        return this.exportBundle;
      } catch (error) {
        return this.fail(error);
      } finally {
        this.finish("export");
      }
    },

    async downloadExport(
      authorize: AuthorizedFinalizationRequest,
      api: FinalizationApi = finalizationApi,
    ): Promise<FinalExportDownloadPayload> {
      if (this.exportBundle === null) {
        throw new Error("A final export must exist before download");
      }
      return authorize((token) => api.downloadExport(this.exportBundle?.id ?? "", token));
    },
  },
});
