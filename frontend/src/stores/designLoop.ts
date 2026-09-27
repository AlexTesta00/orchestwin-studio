import { defineStore } from "pinia";

import { designLoopApi, DesignLoopApiError, type DesignLoopApi } from "../api/designLoop";
import type { DesignGenerationPayload } from "../types/design";
import type {
  DesignDiscussionPayload,
  DesignDiscussionRequest,
  DesignEvaluationComparisonPayload,
  DesignEvaluationMode,
  DesignEvaluationRunPayload,
  DiscussionDecisionAction,
  DiscussionRoundRequest,
  FindingValidationPayload,
  FindingValidationRequest,
  InsightApplicationPayload,
  InsightApplicationRequest,
  SyntheticFindingPayload,
} from "../types/designLoop";

export type AuthorizedDesignLoopRequest = <T>(
  operation: (accessToken: string) => Promise<T>,
) => Promise<T>;

export const EVALUATOR_NOT_CONFIGURED = "DESIGN_EVALUATOR_NOT_CONFIGURED";
export const REVIEWER_NOT_CONFIGURED = "DESIGN_REVIEWER_NOT_CONFIGURED";
export const TWIN_REVIEW_EVALUATOR_ID = "proposer-design-twin-review";

export type DiscussionOperation = "load" | "start" | "round" | "decide";

interface DesignLoopStoreState {
  projectId: string | null;
  runs: DesignEvaluationRunPayload[];
  comparison: DesignEvaluationComparisonPayload | null;
  applications: InsightApplicationPayload[];
  validations: FindingValidationPayload[];
  discussions: DesignDiscussionPayload[];
  busy: "load" | "evaluate" | "regenerate" | "apply" | null;
  validating: string | null;
  discussionBusy: DiscussionOperation | null;
  loaded: boolean;
  evaluatorUnavailable: boolean;
  reviewerUnavailable: boolean;
  error: string | null;
  validationError: string | null;
  discussionError: string | null;
  lastApplication: InsightApplicationPayload | null;
}

function errorMessage(error: unknown): string {
  if (error instanceof DesignLoopApiError) {
    return error.code ?? error.message;
  }
  return error instanceof Error ? error.message : "DESIGN_LOOP_REQUEST_FAILED";
}

export function runFindings(run: DesignEvaluationRunPayload): SyntheticFindingPayload[] {
  return run.responses.flatMap((response) => response.findings);
}

export function runMode(run: DesignEvaluationRunPayload): DesignEvaluationMode {
  return run.responses[0]?.evaluator.evaluator_id === TWIN_REVIEW_EVALUATOR_ID
    ? "TWIN_REVIEW"
    : "STATIC_CHECK";
}

export function findingKey(runId: string, twinId: string, findingId: string): string {
  return `${runId}:${twinId}:${findingId}`;
}

function validationKey(validation: FindingValidationPayload): string {
  return findingKey(validation.evaluation_run_id, validation.twin_id, validation.finding_id);
}

function upsertDiscussion(
  discussions: DesignDiscussionPayload[],
  discussion: DesignDiscussionPayload,
): DesignDiscussionPayload[] {
  return discussions.some((item) => item.id === discussion.id)
    ? discussions.map((item) => (item.id === discussion.id ? discussion : item))
    : [discussion, ...discussions];
}

export const useDesignLoopStore = defineStore("designLoop", {
  state: (): DesignLoopStoreState => ({
    projectId: null,
    runs: [],
    comparison: null,
    applications: [],
    validations: [],
    discussions: [],
    busy: null,
    validating: null,
    discussionBusy: null,
    loaded: false,
    evaluatorUnavailable: false,
    reviewerUnavailable: false,
    error: null,
    validationError: null,
    discussionError: null,
    lastApplication: null,
  }),

  getters: {
    latestRun: (state) => state.runs[0] ?? null,
    latestDiscussion: (state) => state.discussions[0] ?? null,
    isBusy: (state) => state.busy !== null || state.discussionBusy !== null,
    validationByKey: (state): Record<string, FindingValidationPayload> => {
      const byKey: Record<string, FindingValidationPayload> = {};
      for (const validation of state.validations) {
        const key = validationKey(validation);
        const known = byKey[key];
        if (known === undefined || known.sequence_number < validation.sequence_number) {
          byKey[key] = validation;
        }
      }
      return byKey;
    },
  },

  actions: {
    reset(projectId: string): void {
      this.projectId = projectId;
      this.runs = [];
      this.comparison = null;
      this.applications = [];
      this.validations = [];
      this.discussions = [];
      this.busy = null;
      this.validating = null;
      this.discussionBusy = null;
      this.loaded = false;
      this.evaluatorUnavailable = false;
      this.reviewerUnavailable = false;
      this.error = null;
      this.validationError = null;
      this.discussionError = null;
      this.lastApplication = null;
    },

    async load(
      projectId: string,
      authorize: AuthorizedDesignLoopRequest,
      api: DesignLoopApi = designLoopApi,
    ): Promise<void> {
      if (this.projectId !== projectId) {
        this.reset(projectId);
      }
      this.busy = "load";
      this.error = null;
      try {
        const [runs, applications, comparison, validations] = await Promise.all([
          authorize((token) => api.runs(projectId, token)),
          authorize((token) => api.applications(projectId, token)),
          authorize((token) => api.comparison(projectId, token)),
          authorize((token) => api.validations(projectId, token)),
        ]);
        if (this.projectId !== projectId) return;
        this.runs = runs;
        this.applications = applications;
        this.comparison = comparison;
        this.validations = validations;
        this.loaded = true;
      } catch (error) {
        this.error = errorMessage(error);
        throw error;
      } finally {
        this.busy = null;
      }
    },

    async refreshComparison(
      projectId: string,
      authorize: AuthorizedDesignLoopRequest,
      api: DesignLoopApi = designLoopApi,
    ): Promise<void> {
      try {
        const comparison = await authorize((token) => api.comparison(projectId, token));
        if (this.projectId === projectId) this.comparison = comparison;
      } catch {
        if (this.projectId === projectId) this.comparison = null;
      }
    },

    async evaluate(
      projectId: string,
      designVersionId: string,
      designContentHash: string,
      authorize: AuthorizedDesignLoopRequest,
      api: DesignLoopApi = designLoopApi,
      mode: DesignEvaluationMode = "TWIN_REVIEW",
      locale?: string,
    ): Promise<DesignEvaluationRunPayload> {
      this.busy = "evaluate";
      this.error = null;
      try {
        const run = await authorize((token) =>
          api.evaluate(
            projectId,
            {
              design_version_id: designVersionId,
              design_content_hash: designContentHash,
              mode,
              ...(locale === undefined ? {} : { locale }),
            },
            token,
          ),
        );
        if (this.projectId === projectId) {
          this.runs = [run, ...this.runs.filter((item) => item.id !== run.id)];
          if (mode === "TWIN_REVIEW") {
            this.reviewerUnavailable = false;
          } else {
            this.evaluatorUnavailable = false;
          }
          await this.refreshComparison(projectId, authorize, api);
        }
        return run;
      } catch (error) {
        this.error = errorMessage(error);
        if (error instanceof DesignLoopApiError && error.code === REVIEWER_NOT_CONFIGURED) {
          this.reviewerUnavailable = true;
        }
        if (error instanceof DesignLoopApiError && error.code === EVALUATOR_NOT_CONFIGURED) {
          this.evaluatorUnavailable = true;
        }
        throw error;
      } finally {
        this.busy = null;
      }
    },

    async regenerate(
      projectId: string,
      authorize: AuthorizedDesignLoopRequest,
      api: DesignLoopApi = designLoopApi,
    ): Promise<DesignGenerationPayload> {
      this.busy = "regenerate";
      this.error = null;
      try {
        const result = await authorize((token) => api.regenerate(projectId, token));
        if (result.status === "CREATED") {
          this.lastApplication = null;
        }
        return result;
      } catch (error) {
        this.error = errorMessage(error);
        throw error;
      } finally {
        this.busy = null;
      }
    },

    async apply(
      projectId: string,
      body: InsightApplicationRequest,
      authorize: AuthorizedDesignLoopRequest,
      api: DesignLoopApi = designLoopApi,
    ): Promise<InsightApplicationPayload> {
      const claimed = this.busy === null;
      if (claimed) this.busy = "apply";
      this.error = null;
      try {
        const application = await authorize((token) => api.applyInsight(projectId, body, token));
        this.applications = [application, ...this.applications];
        this.lastApplication = application;
        return application;
      } catch (error) {
        this.error = errorMessage(error);
        throw error;
      } finally {
        if (claimed) this.busy = null;
      }
    },

    async validate(
      projectId: string,
      runId: string,
      body: FindingValidationRequest,
      authorize: AuthorizedDesignLoopRequest,
      api: DesignLoopApi = designLoopApi,
    ): Promise<FindingValidationPayload> {
      const key = findingKey(runId, body.twin_id, body.finding_id);
      this.validating = key;
      this.validationError = null;
      try {
        const validation = await authorize((token) => api.validate(projectId, runId, body, token));
        if (this.projectId === projectId) {
          this.validations = [
            validation,
            ...this.validations.filter((item) => validationKey(item) !== key),
          ];
          await this.refreshComparison(projectId, authorize, api);
        }
        return validation;
      } catch (error) {
        this.validationError = errorMessage(error);
        throw error;
      } finally {
        this.validating = null;
      }
    },

    async loadDiscussions(
      projectId: string,
      authorize: AuthorizedDesignLoopRequest,
      api: DesignLoopApi = designLoopApi,
    ): Promise<void> {
      if (this.projectId !== projectId) {
        this.reset(projectId);
      }
      this.discussionBusy = "load";
      this.discussionError = null;
      try {
        const discussions = await authorize((token) => api.discussions(projectId, token));
        if (this.projectId === projectId) this.discussions = discussions;
      } catch (error) {
        if (this.projectId === projectId) this.discussionError = errorMessage(error);
        throw error;
      } finally {
        this.discussionBusy = null;
      }
    },

    async startDiscussion(
      projectId: string,
      body: DesignDiscussionRequest,
      authorize: AuthorizedDesignLoopRequest,
      api: DesignLoopApi = designLoopApi,
    ): Promise<DesignDiscussionPayload> {
      this.discussionBusy = "start";
      this.discussionError = null;
      try {
        const discussion = await authorize((token) => api.startDiscussion(projectId, body, token));
        if (this.projectId === projectId) {
          this.discussions = upsertDiscussion(this.discussions, discussion);
        }
        return discussion;
      } catch (error) {
        if (this.projectId === projectId) this.discussionError = errorMessage(error);
        throw error;
      } finally {
        this.discussionBusy = null;
      }
    },

    async nextDiscussionRound(
      projectId: string,
      discussionId: string,
      body: DiscussionRoundRequest,
      authorize: AuthorizedDesignLoopRequest,
      api: DesignLoopApi = designLoopApi,
    ): Promise<DesignDiscussionPayload> {
      this.discussionBusy = "round";
      this.discussionError = null;
      try {
        const discussion = await authorize((token) =>
          api.nextDiscussionRound(projectId, discussionId, body, token),
        );
        if (this.projectId === projectId) {
          this.discussions = upsertDiscussion(this.discussions, discussion);
        }
        return discussion;
      } catch (error) {
        if (this.projectId === projectId) this.discussionError = errorMessage(error);
        throw error;
      } finally {
        this.discussionBusy = null;
      }
    },

    async decideDiscussion(
      projectId: string,
      discussionId: string,
      action: DiscussionDecisionAction,
      authorize: AuthorizedDesignLoopRequest,
      api: DesignLoopApi = designLoopApi,
    ): Promise<DesignDiscussionPayload> {
      this.discussionBusy = "decide";
      this.discussionError = null;
      try {
        const discussion = await authorize((token) =>
          api.decideDiscussion(projectId, discussionId, { action }, token),
        );
        if (this.projectId === projectId) {
          this.discussions = upsertDiscussion(this.discussions, discussion);
        }
        return discussion;
      } catch (error) {
        if (this.projectId === projectId) this.discussionError = errorMessage(error);
        throw error;
      } finally {
        this.discussionBusy = null;
      }
    },
  },
});
