import type {
  HumanGateEventPayload,
  HumanGatePayload,
  RequirementsCoveragePayload,
  RequirementsGateDecisionPayload,
  RequirementsGateDecisionRequest,
  RequirementsGateSubmissionPayload,
  RequirementsGenerationPayload,
  RequirementsReadinessPayload,
  RequirementsRevisionDecisionRequest,
  RequirementsRevisionPayload,
  RequirementsRevisionRequest,
  RequirementsSpecificationDiffPayload,
  RequirementsSpecificationVersionPayload,
  RequirementsTraceabilityPayload,
} from "../types/requirements";

const DEFAULT_API_BASE_PATH = "/api/v1";

type HttpMethod = "GET" | "POST";

interface RequestOptions {
  method: HttpMethod;
  accessToken: string;
  body?: unknown;
}

export interface RequirementsApiOptions {
  basePath?: string;
  fetchImpl?: typeof fetch;
}

export class RequirementsApiError extends Error {
  readonly status: number;
  readonly code: string | null;
  readonly payload: unknown;

  constructor(
    message: string,
    options: {
      status: number;
      code: string | null;
      payload: unknown;
    },
  ) {
    super(message);
    this.name = "RequirementsApiError";
    this.status = options.status;
    this.code = options.code;
    this.payload = options.payload;
  }
}

export interface RequirementsApi {
  generate(projectId: string, accessToken: string): Promise<RequirementsGenerationPayload>;
  current(projectId: string, accessToken: string): Promise<RequirementsSpecificationVersionPayload>;
  history(
    projectId: string,
    accessToken: string,
  ): Promise<RequirementsSpecificationVersionPayload[]>;
  proposeRevision(
    projectId: string,
    request: RequirementsRevisionRequest,
    accessToken: string,
  ): Promise<RequirementsRevisionPayload>;
  revisionHistory(
    projectId: string,
    accessToken: string,
  ): Promise<RequirementsSpecificationDiffPayload[]>;
  getRevision(
    projectId: string,
    diffId: string,
    accessToken: string,
  ): Promise<RequirementsSpecificationDiffPayload>;
  decideRevision(
    projectId: string,
    diffId: string,
    request: RequirementsRevisionDecisionRequest,
    accessToken: string,
  ): Promise<RequirementsRevisionPayload>;
  traceability(projectId: string, accessToken: string): Promise<RequirementsTraceabilityPayload>;
  coverage(projectId: string, accessToken: string): Promise<RequirementsCoveragePayload>;
  submitGate(projectId: string, accessToken: string): Promise<RequirementsGateSubmissionPayload>;
  decideGate(
    projectId: string,
    request: RequirementsGateDecisionRequest,
    accessToken: string,
  ): Promise<RequirementsGateDecisionPayload>;
  currentGate(projectId: string, accessToken: string): Promise<HumanGatePayload>;
  gateEvents(projectId: string, accessToken: string): Promise<HumanGateEventPayload[]>;
  readiness(projectId: string, accessToken: string): Promise<RequirementsReadinessPayload>;
}

function normalizedBasePath(value: string): string {
  const normalized = value.trim().replace(/\/+$/, "");

  if (normalized.length === 0) {
    throw new Error("Requirements API base path must not be empty");
  }

  return normalized;
}

function requiredAccessToken(value: string): string {
  const normalized = value.trim();

  if (normalized.length === 0) {
    throw new RequirementsApiError("Authentication is required", {
      status: 0,
      code: "ACCESS_TOKEN_REQUIRED",
      payload: null,
    });
  }

  return normalized;
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

function errorCode(payload: unknown): string | null {
  if (!isRecord(payload) || !isRecord(payload.detail)) {
    return null;
  }

  return typeof payload.detail.code === "string" ? payload.detail.code : null;
}

async function responsePayload(response: Response): Promise<unknown> {
  const text = await response.text();

  if (text.trim().length === 0) {
    return null;
  }

  try {
    return JSON.parse(text) as unknown;
  } catch {
    throw new RequirementsApiError("The Requirements API returned invalid JSON", {
      status: response.status,
      code: "INVALID_API_RESPONSE",
      payload: text,
    });
  }
}

function projectRequirementsPath(basePath: string, projectId: string): string {
  return `${basePath}/projects/${encodeURIComponent(projectId)}/requirements`;
}

export function createRequirementsApi(options: RequirementsApiOptions = {}): RequirementsApi {
  const basePath = normalizedBasePath(options.basePath ?? DEFAULT_API_BASE_PATH);

  async function request<T>(path: string, optionsValue: RequestOptions): Promise<T> {
    const accessToken = requiredAccessToken(optionsValue.accessToken);
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
    const response = await fetchImpl(path, init);
    const payload = await responsePayload(response);

    if (!response.ok) {
      const code = errorCode(payload);

      throw new RequirementsApiError(
        code ?? `Requirements API request failed with status ${response.status}`,
        {
          status: response.status,
          code,
          payload,
        },
      );
    }

    return payload as T;
  }

  function projectPath(projectId: string): string {
    return projectRequirementsPath(basePath, projectId);
  }

  return {
    generate(projectId, accessToken) {
      return request(`${projectPath(projectId)}/proposals`, {
        method: "POST",
        accessToken,
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

    traceability(projectId, accessToken) {
      return request(`${projectPath(projectId)}/traceability`, {
        method: "GET",
        accessToken,
      });
    },

    coverage(projectId, accessToken) {
      return request(`${projectPath(projectId)}/coverage`, {
        method: "GET",
        accessToken,
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
  };
}

export const requirementsApi = createRequirementsApi();
