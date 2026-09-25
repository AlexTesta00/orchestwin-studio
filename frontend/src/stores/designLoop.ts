import { defineStore } from "pinia";

import { designLoopApi, DesignLoopApiError, type DesignLoopApi } from "../api/designLoop";
import type { DesignGenerationPayload } from "../types/design";
import type {
  DesignEvaluationComparisonPayload,
  DesignEvaluationRunPayload,
  InsightApplicationPayload,
  InsightApplicationRequest,
  SyntheticFindingPayload,
} from "../types/designLoop";

export type AuthorizedDesignLoopRequest = <T>(
  operation: (accessToken: string) => Promise<T>,
) => Promise<T>;

export const EVALUATOR_NOT_CONFIGURED = "DESIGN_EVALUATOR_NOT_CONFIGURED";

interface DesignLoopStoreState {
  projectId: string | null;
  runs: DesignEvaluationRunPayload[];
  comparison: DesignEvaluationComparisonPayload | null;
  applications: InsightApplicationPayload[];
  busy: "load" | "evaluate" | "regenerate" | "apply" | null;
  loaded: boolean;
  evaluatorUnavailable: boolean;
  error: string | null;
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

export const useDesignLoopStore = defineStore("designLoop", {
  state: (): DesignLoopStoreState => ({
    projectId: null,
    runs: [],
    comparison: null,
    applications: [],
    busy: null,
    loaded: false,
    evaluatorUnavailable: false,
    error: null,
    lastApplication: null,
  }),

  getters: {
    latestRun: (state) => state.runs[0] ?? null,
    isBusy: (state) => state.busy !== null,
  },

  actions: {
    reset(projectId: string): void {
      this.projectId = projectId;
      this.runs = [];
      this.comparison = null;
      this.applications = [];
      this.busy = null;
      this.loaded = false;
      this.evaluatorUnavailable = false;
      this.error = null;
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
        const [runs, applications, comparison] = await Promise.all([
          authorize((token) => api.runs(projectId, token)),
          authorize((token) => api.applications(projectId, token)),
          authorize((token) => api.comparison(projectId, token)),
        ]);
        this.runs = runs;
        this.applications = applications;
        this.comparison = comparison;
        this.loaded = true;
      } catch (error) {
        this.error = errorMessage(error);
        throw error;
      } finally {
        this.busy = null;
      }
    },

    async evaluate(
      projectId: string,
      designVersionId: string,
      designContentHash: string,
      authorize: AuthorizedDesignLoopRequest,
      api: DesignLoopApi = designLoopApi,
    ): Promise<DesignEvaluationRunPayload> {
      this.busy = "evaluate";
      this.error = null;
      try {
        const run = await authorize((token) =>
          api.evaluate(
            projectId,
            { design_version_id: designVersionId, design_content_hash: designContentHash },
            token,
          ),
        );
        this.runs = [run, ...this.runs.filter((item) => item.id !== run.id)];
        this.comparison = await authorize((token) => api.comparison(projectId, token));
        return run;
      } catch (error) {
        this.error = errorMessage(error);
        this.evaluatorUnavailable =
          error instanceof DesignLoopApiError && error.code === EVALUATOR_NOT_CONFIGURED;
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
        return await authorize((token) => api.regenerate(projectId, token));
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
      this.busy = "apply";
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
        this.busy = null;
      }
    },
  },
});
