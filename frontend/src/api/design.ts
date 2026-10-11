import { sendGeneration } from "./generationJobs";
import { accessTokenOf, basePathOf, detailCode, isRecord, responseBody } from "./http";
import { ApiRequestError } from "./requestError";

import type {
  DesignGateDecisionPayload,
  DesignGateDecisionRequest,
  DesignGateSubmissionPayload,
  DesignGenerationPayload,
  DesignMockupPayload,
  DesignMockupRequest,
  DesignPackageDiffPayload,
  DesignPackageVersionPayload,
  DesignReadinessPayload,
  DesignRevisionDecisionRequest,
  DesignRevisionPayload,
  DesignRevisionRequest,
  HumanGateEventPayload,
  HumanGatePayload,
} from "../types/design";
import type { DesignDistanceReportPayload } from "../types/designDistance";

const DEFAULT_API_BASE_PATH = "/api/v1";

type HttpMethod = "GET" | "POST";

interface RequestOptions {
  method: HttpMethod;
  accessToken: string;
  body?: unknown;
  generationProjectId?: string;
  accepts?: (payload: unknown) => boolean;
}

export interface DesignApiOptions {
  basePath?: string;
  fetchImpl?: typeof fetch;
}

export class DesignApiError extends ApiRequestError {}

export interface DesignApi {
  generateMockup(
    projectId: string,
    request: DesignMockupRequest,
    accessToken: string,
  ): Promise<DesignMockupPayload>;
  currentMockup(
    projectId: string,
    alternativeId: string,
    accessToken: string,
  ): Promise<DesignMockupPayload | null>;
  generate(projectId: string, accessToken: string): Promise<DesignGenerationPayload>;
  current(projectId: string, accessToken: string): Promise<DesignPackageVersionPayload>;
  history(projectId: string, accessToken: string): Promise<DesignPackageVersionPayload[]>;
  proposeRevision(
    projectId: string,
    request: DesignRevisionRequest,
    accessToken: string,
  ): Promise<DesignRevisionPayload>;
  revisionHistory(projectId: string, accessToken: string): Promise<DesignPackageDiffPayload[]>;
  getRevision(
    projectId: string,
    diffId: string,
    accessToken: string,
  ): Promise<DesignPackageDiffPayload>;
  decideRevision(
    projectId: string,
    diffId: string,
    request: DesignRevisionDecisionRequest,
    accessToken: string,
  ): Promise<DesignRevisionPayload>;
  submitGate(projectId: string, accessToken: string): Promise<DesignGateSubmissionPayload>;
  decideGate(
    projectId: string,
    request: DesignGateDecisionRequest,
    accessToken: string,
  ): Promise<DesignGateDecisionPayload>;
  currentGate(projectId: string, accessToken: string): Promise<HumanGatePayload>;
  gateEvents(projectId: string, accessToken: string): Promise<HumanGateEventPayload[]>;
  readiness(projectId: string, accessToken: string): Promise<DesignReadinessPayload>;
}

export interface DesignDistanceApi {
  distance(projectId: string, accessToken: string): Promise<DesignDistanceReportPayload>;
}

function isScore(value: unknown): boolean {
  return value === null || typeof value === "number";
}

function isMeasure(value: unknown): boolean {
  return (
    isRecord(value) &&
    typeof value.available === "boolean" &&
    isScore(value.score) &&
    Array.isArray(value.differences)
  );
}

function isDistancePair(value: unknown): boolean {
  return (
    isRecord(value) &&
    typeof value.first === "string" &&
    typeof value.second === "string" &&
    typeof value.verdict === "string" &&
    isRecord(value.declared) &&
    isScore(value.declared.score) &&
    isScore(value.declared.axes_different) &&
    Array.isArray(value.declared.axes) &&
    isMeasure(value.styles) &&
    isMeasure(value.structure)
  );
}

function isDistanceAlternative(value: unknown): boolean {
  return (
    isRecord(value) &&
    typeof value.code === "string" &&
    isRecord(value.adherence) &&
    typeof value.adherence.available === "boolean" &&
    isRecord(value.adherence.axes)
  );
}

function isDistanceReport(payload: unknown): boolean {
  return (
    isRecord(payload) &&
    typeof payload.design_version_id === "string" &&
    typeof payload.design_content_hash === "string" &&
    Array.isArray(payload.pairs) &&
    payload.pairs.every(isDistancePair) &&
    Array.isArray(payload.alternatives) &&
    payload.alternatives.every(isDistanceAlternative)
  );
}

function errorCode(payload: unknown): string | null {
  const reason =
    isRecord(payload) && isRecord(payload.detail) ? payload.detail.proposal_issue : null;

  return typeof reason === "string" && reason.length > 0 ? reason : detailCode(payload);
}

function projectDesignPath(basePath: string, projectId: string): string {
  return `${basePath}/projects/${encodeURIComponent(projectId)}/design`;
}

export function createDesignApi(options: DesignApiOptions = {}): DesignApi & DesignDistanceApi {
  const basePath = basePathOf(options.basePath ?? DEFAULT_API_BASE_PATH, "Design");

  async function request<T>(path: string, optionsValue: RequestOptions): Promise<T> {
    const accessToken = accessTokenOf(optionsValue.accessToken, DesignApiError);
    const headers: Record<string, string> = {
      Accept: "application/json",
      Authorization: `Bearer ${accessToken}`,
    };
    const init: RequestInit = {
      method: optionsValue.method,
      headers,
      credentials: "include",
    };

    if (optionsValue.body !== undefined) {
      headers["Content-Type"] = "application/json";
      init.body = JSON.stringify(optionsValue.body);
    }

    const fetchImpl = options.fetchImpl ?? globalThis.fetch;
    const response =
      optionsValue.generationProjectId === undefined
        ? await fetchImpl(path, init)
        : await sendGeneration(path, init, {
            fetchImpl,
            basePath,
            projectId: optionsValue.generationProjectId,
          });
    const payload = await responseBody(response, DesignApiError, "Design");

    if (!response.ok) {
      const code = errorCode(payload);

      throw new DesignApiError(code ?? `Design API request failed with status ${response.status}`, {
        status: response.status,
        code,
        payload,
      });
    }

    if (optionsValue.accepts !== undefined && !optionsValue.accepts(payload)) {
      throw new DesignApiError("The Design API returned an unexpected answer", {
        status: response.status,
        code: "INVALID_API_RESPONSE",
        payload,
      });
    }

    return payload as T;
  }

  function projectPath(projectId: string): string {
    return projectDesignPath(basePath, projectId);
  }

  return {
    generateMockup(projectId, requestValue, accessToken) {
      return request(`${projectPath(projectId)}/mockups`, {
        method: "POST",
        accessToken,
        body: requestValue,
      });
    },

    currentMockup(projectId, alternativeId, accessToken) {
      return request(
        `${projectPath(projectId)}/mockups?alternative_id=${encodeURIComponent(alternativeId)}`,
        {
          method: "GET",
          accessToken,
        },
      );
    },

    generate(projectId, accessToken) {
      return request(`${projectPath(projectId)}/proposals`, {
        method: "POST",
        accessToken,
        generationProjectId: projectId,
      });
    },

    current(projectId, accessToken) {
      return request(`${projectPath(projectId)}/current`, {
        method: "GET",
        accessToken,
      });
    },

    history(projectId, accessToken) {
      return request(projectPath(projectId), {
        method: "GET",
        accessToken,
      });
    },

    proposeRevision(projectId, requestValue, accessToken) {
      return request(`${projectPath(projectId)}/revisions`, {
        method: "POST",
        accessToken,
        body: requestValue,
      });
    },

    revisionHistory(projectId, accessToken) {
      return request(`${projectPath(projectId)}/revisions`, {
        method: "GET",
        accessToken,
      });
    },

    getRevision(projectId, diffId, accessToken) {
      return request(`${projectPath(projectId)}/revisions/${encodeURIComponent(diffId)}`, {
        method: "GET",
        accessToken,
      });
    },

    decideRevision(projectId, diffId, requestValue, accessToken) {
      return request(`${projectPath(projectId)}/revisions/${encodeURIComponent(diffId)}/decision`, {
        method: "POST",
        accessToken,
        body: requestValue,
      });
    },

    submitGate(projectId, accessToken) {
      return request(`${projectPath(projectId)}/gate/submit`, {
        method: "POST",
        accessToken,
      });
    },

    decideGate(projectId, requestValue, accessToken) {
      return request(`${projectPath(projectId)}/gate/decision`, {
        method: "POST",
        accessToken,
        body: requestValue,
      });
    },

    currentGate(projectId, accessToken) {
      return request(`${projectPath(projectId)}/gate`, {
        method: "GET",
        accessToken,
      });
    },

    gateEvents(projectId, accessToken) {
      return request(`${projectPath(projectId)}/gate/events`, {
        method: "GET",
        accessToken,
      });
    },

    readiness(projectId, accessToken) {
      return request(`${projectPath(projectId)}/readiness`, {
        method: "GET",
        accessToken,
      });
    },

    distance(projectId, accessToken) {
      return request(`${projectPath(projectId)}/distance`, {
        method: "GET",
        accessToken,
        accepts: isDistanceReport,
      });
    },
  };
}

export const designApi = createDesignApi();
