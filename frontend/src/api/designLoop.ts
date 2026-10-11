import { sendGeneration } from "./generationJobs";
import { absoluteBasePathOf, accessTokenOf, detailCode, responseBody } from "./http";
import { ApiRequestError } from "./requestError";

import type { DesignGenerationPayload } from "../types/design";
import type {
  DesignDiscussionPayload,
  DesignDiscussionRequest,
  DesignEvaluationComparisonPayload,
  DesignEvaluationRequest,
  DesignEvaluationRunPayload,
  DiscussionDecisionRequest,
  DiscussionRoundRequest,
  FindingValidationPayload,
  FindingValidationRequest,
  InsightApplicationPayload,
  InsightApplicationRequest,
  InsightBatchApplicationPayload,
  InsightBatchApplicationRequest,
} from "../types/designLoop";

const DEFAULT_API_BASE_PATH = "/api/v1";

export interface DesignLoopApiOptions {
  basePath?: string;
  fetchImpl?: typeof fetch;
}

export interface DesignEvaluationScope {
  screen_code: string;
  element_code?: string;
}

export type DesignEvaluationBody = DesignEvaluationRequest & { scope?: DesignEvaluationScope };

export interface DesignLoopApi {
  evaluate(
    projectId: string,
    body: DesignEvaluationBody,
    accessToken: string,
  ): Promise<DesignEvaluationRunPayload>;
  runs(projectId: string, accessToken: string): Promise<DesignEvaluationRunPayload[]>;
  comparison(
    projectId: string,
    accessToken: string,
  ): Promise<DesignEvaluationComparisonPayload | null>;
  regenerate(projectId: string, accessToken: string): Promise<DesignGenerationPayload>;
  applyInsight(
    projectId: string,
    body: InsightApplicationRequest,
    accessToken: string,
  ): Promise<InsightApplicationPayload>;
  applications(projectId: string, accessToken: string): Promise<InsightApplicationPayload[]>;
  validations(projectId: string, accessToken: string): Promise<FindingValidationPayload[]>;
  validate(
    projectId: string,
    runId: string,
    body: FindingValidationRequest,
    accessToken: string,
  ): Promise<FindingValidationPayload>;
  discussions(projectId: string, accessToken: string): Promise<DesignDiscussionPayload[]>;
  startDiscussion(
    projectId: string,
    body: DesignDiscussionRequest,
    accessToken: string,
  ): Promise<DesignDiscussionPayload>;
  nextDiscussionRound(
    projectId: string,
    discussionId: string,
    body: DiscussionRoundRequest,
    accessToken: string,
  ): Promise<DesignDiscussionPayload>;
  decideDiscussion(
    projectId: string,
    discussionId: string,
    body: DiscussionDecisionRequest,
    accessToken: string,
  ): Promise<DesignDiscussionPayload>;
}

export interface InsightBatchApi {
  applyInsightBatch(
    projectId: string,
    body: InsightBatchApplicationRequest,
    accessToken: string,
  ): Promise<InsightBatchApplicationPayload>;
}

export class DesignLoopApiError extends ApiRequestError {}

export function createDesignLoopApi(
  options: DesignLoopApiOptions = {},
): DesignLoopApi & InsightBatchApi {
  const basePath = absoluteBasePathOf(options.basePath ?? DEFAULT_API_BASE_PATH, "Design loop");
  const fetchImpl = options.fetchImpl ?? globalThis.fetch.bind(globalThis);

  function projectPath(projectId: string): string {
    return `${basePath}/projects/${encodeURIComponent(projectId)}`;
  }

  async function request(
    path: string,
    accessToken: string,
    method: "GET" | "POST",
    body?: unknown,
    generationProjectId?: string,
  ): Promise<unknown> {
    const headers = new Headers();
    headers.set("Accept", "application/json");
    headers.set("Authorization", `Bearer ${accessTokenOf(accessToken, DesignLoopApiError)}`);
    const init: RequestInit = { credentials: "include", headers, method };
    if (body !== undefined) {
      headers.set("Content-Type", "application/json");
      init.body = JSON.stringify(body);
    }
    const response =
      generationProjectId === undefined
        ? await fetchImpl(path, init)
        : await sendGeneration(path, init, {
            fetchImpl,
            basePath,
            projectId: generationProjectId,
          });
    const payload = await responseBody(response);
    if (!response.ok) {
      throw new DesignLoopApiError("The design loop request failed", {
        status: response.status,
        code: detailCode(payload),
        payload,
      });
    }
    return payload;
  }

  return {
    async evaluate(projectId, body, accessToken) {
      return (await request(
        `${projectPath(projectId)}/design/evaluations`,
        accessToken,
        "POST",
        body,
        projectId,
      )) as DesignEvaluationRunPayload;
    },

    async runs(projectId, accessToken) {
      return (await request(
        `${projectPath(projectId)}/design/evaluations`,
        accessToken,
        "GET",
      )) as DesignEvaluationRunPayload[];
    },

    async comparison(projectId, accessToken) {
      try {
        return (await request(
          `${projectPath(projectId)}/design/evaluations/comparison`,
          accessToken,
          "GET",
        )) as DesignEvaluationComparisonPayload;
      } catch (error) {
        if (error instanceof DesignLoopApiError && error.status === 404) {
          return null;
        }
        throw error;
      }
    },

    async regenerate(projectId, accessToken) {
      return (await request(
        `${projectPath(projectId)}/design/regenerations`,
        accessToken,
        "POST",
        {},
        projectId,
      )) as DesignGenerationPayload;
    },

    async applyInsight(projectId, body, accessToken) {
      return (await request(
        `${projectPath(projectId)}/insight-applications`,
        accessToken,
        "POST",
        body,
      )) as InsightApplicationPayload;
    },

    async applyInsightBatch(projectId, body, accessToken) {
      return (await request(
        `${projectPath(projectId)}/insight-applications/batch`,
        accessToken,
        "POST",
        body,
      )) as InsightBatchApplicationPayload;
    },

    async applications(projectId, accessToken) {
      return (await request(
        `${projectPath(projectId)}/insight-applications`,
        accessToken,
        "GET",
      )) as InsightApplicationPayload[];
    },

    async validations(projectId, accessToken) {
      return (await request(
        `${projectPath(projectId)}/design/evaluations/validations`,
        accessToken,
        "GET",
      )) as FindingValidationPayload[];
    },

    async validate(projectId, runId, body, accessToken) {
      return (await request(
        `${projectPath(projectId)}/design/evaluations/${encodeURIComponent(runId)}/validations`,
        accessToken,
        "POST",
        body,
      )) as FindingValidationPayload;
    },

    async discussions(projectId, accessToken) {
      return (await request(
        `${projectPath(projectId)}/design/discussions`,
        accessToken,
        "GET",
      )) as DesignDiscussionPayload[];
    },

    async startDiscussion(projectId, body, accessToken) {
      return (await request(
        `${projectPath(projectId)}/design/discussions`,
        accessToken,
        "POST",
        body,
        projectId,
      )) as DesignDiscussionPayload;
    },

    async nextDiscussionRound(projectId, discussionId, body, accessToken) {
      return (await request(
        `${projectPath(projectId)}/design/discussions/${encodeURIComponent(discussionId)}/rounds`,
        accessToken,
        "POST",
        body,
        projectId,
      )) as DesignDiscussionPayload;
    },

    async decideDiscussion(projectId, discussionId, body, accessToken) {
      return (await request(
        `${projectPath(projectId)}/design/discussions/${encodeURIComponent(discussionId)}/decision`,
        accessToken,
        "POST",
        body,
      )) as DesignDiscussionPayload;
    },
  };
}

export const designLoopApi = createDesignLoopApi();
