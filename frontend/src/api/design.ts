import type {
  DesignGateDecisionPayload,
  DesignGateDecisionRequest,
  DesignGateSubmissionPayload,
  DesignGenerationPayload,
  DesignPackageDiffPayload,
  DesignPackageVersionPayload,
  DesignReadinessPayload,
  DesignRevisionDecisionRequest,
  DesignRevisionPayload,
  DesignRevisionRequest,
  HumanGateEventPayload,
  HumanGatePayload,
} from "../types/design";

const DEFAULT_API_BASE_PATH = "/api/v1";

type HttpMethod = "GET" | "POST";

interface RequestOptions {
  method: HttpMethod;
  accessToken: string;
  body?: unknown;
}

export interface DesignApiOptions {
  basePath?: string;
  fetchImpl?: typeof fetch;
}

export class DesignApiError extends Error {
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
    this.name = "DesignApiError";
    this.status = options.status;
    this.code = options.code;
    this.payload = options.payload;
  }
}

export interface DesignApi {
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

function normalizedBasePath(value: string): string {
  const normalized = value.trim().replace(/\/+$/, "");

  if (normalized.length === 0) {
    throw new Error("Design API base path must not be empty");
  }

  return normalized;
}

function requiredAccessToken(value: string): string {
  const normalized = value.trim();

  if (normalized.length === 0) {
    throw new DesignApiError("Authentication is required", {
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
    throw new DesignApiError("The Design API returned invalid JSON", {
      status: response.status,
      code: "INVALID_API_RESPONSE",
      payload: text,
    });
  }
}

function projectDesignPath(basePath: string, projectId: string): string {
  return `${basePath}/projects/${encodeURIComponent(projectId)}/design`;
}

export function createDesignApi(options: DesignApiOptions = {}): DesignApi {
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

      throw new DesignApiError(code ?? `Design API request failed with status ${response.status}`, {
        status: response.status,
        code,
        payload,
      });
    }

    return payload as T;
  }

  function projectPath(projectId: string): string {
    return projectDesignPath(basePath, projectId);
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

export const designApi = createDesignApi();
