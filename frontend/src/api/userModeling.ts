import type {
  GateCommandPayload,
  GateDecisionRequest,
  HumanGateEventPayload,
  HumanGatePayload,
  PersonaDecisionCommandPayload,
  PersonaDecisionRequest,
  PersonaProposalCommandPayload,
  ProfileRevisionCommandPayload,
  ProfileRevisionDecisionRequest,
  ProfileRevisionProposalRequest,
  SnapshotGenerationCommandPayload,
  UserModelingReadinessPayload,
  UserModelingSnapshotVersionPayload,
  UserTwinProfileDiffPayload,
} from "../types/userModeling";

const DEFAULT_API_BASE_PATH = "/api/v1";

type HttpMethod = "GET" | "POST";

interface RequestOptions {
  method: HttpMethod;
  accessToken: string;
  body?: unknown;
}

export interface UserModelingApiOptions {
  basePath?: string;
  fetchImpl?: typeof fetch;
}

export class UserModelingApiError extends Error {
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

    this.name = "UserModelingApiError";
    this.status = options.status;
    this.code = options.code;
    this.payload = options.payload;
  }
}

export interface UserModelingApi {
  proposePersonas(projectId: string, accessToken: string): Promise<PersonaProposalCommandPayload>;

  decidePersona(
    projectId: string,
    personaId: string,
    request: PersonaDecisionRequest,
    accessToken: string,
  ): Promise<PersonaDecisionCommandPayload>;

  generateSnapshot(
    projectId: string,
    accessToken: string,
  ): Promise<SnapshotGenerationCommandPayload>;

  getCurrentSnapshot(
    projectId: string,
    accessToken: string,
  ): Promise<UserModelingSnapshotVersionPayload>;

  getSnapshotHistory(
    projectId: string,
    accessToken: string,
  ): Promise<UserModelingSnapshotVersionPayload[]>;

  proposeRevision(
    projectId: string,
    twinId: string,
    request: ProfileRevisionProposalRequest,
    accessToken: string,
  ): Promise<ProfileRevisionCommandPayload>;

  getRevision(
    projectId: string,
    diffId: string,
    accessToken: string,
  ): Promise<UserTwinProfileDiffPayload>;

  decideRevision(
    projectId: string,
    diffId: string,
    request: ProfileRevisionDecisionRequest,
    accessToken: string,
  ): Promise<ProfileRevisionCommandPayload>;

  submitGate(projectId: string, accessToken: string): Promise<GateCommandPayload>;

  decideGate(
    projectId: string,
    request: GateDecisionRequest,
    accessToken: string,
  ): Promise<GateCommandPayload>;

  getCurrentGate(projectId: string, accessToken: string): Promise<HumanGatePayload>;

  getGateEvents(projectId: string, accessToken: string): Promise<HumanGateEventPayload[]>;

  getReadiness(projectId: string, accessToken: string): Promise<UserModelingReadinessPayload>;
}

function normalizeBasePath(value: string): string {
  const trimmed = value.trim();

  if (trimmed.length === 0) {
    throw new Error("User Modeling API base path must not be empty");
  }

  return trimmed.endsWith("/") ? trimmed.slice(0, -1) : trimmed;
}

function requireAccessToken(accessToken: string): string {
  const normalized = accessToken.trim();

  if (normalized.length === 0) {
    throw new UserModelingApiError("Authentication is required", {
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

function extractErrorCode(payload: unknown): string | null {
  if (!isRecord(payload)) {
    return null;
  }

  const detail = payload.detail;

  if (!isRecord(detail)) {
    return null;
  }

  const code = detail.code;

  return typeof code === "string" ? code : null;
}

async function readJson(response: Response): Promise<unknown> {
  const text = await response.text();

  if (text.trim().length === 0) {
    return null;
  }

  try {
    return JSON.parse(text) as unknown;
  } catch {
    throw new UserModelingApiError("The User Modeling API returned invalid JSON", {
      status: response.status,
      code: "INVALID_API_RESPONSE",
      payload: text,
    });
  }
}

function projectPath(basePath: string, projectId: string): string {
  return `${basePath}/projects/` + `${encodeURIComponent(projectId)}/user-modeling`;
}

export function createUserModelingApi(options: UserModelingApiOptions = {}): UserModelingApi {
  const basePath = normalizeBasePath(options.basePath ?? DEFAULT_API_BASE_PATH);

  async function requestJson<T>(path: string, requestOptions: RequestOptions): Promise<T> {
    const accessToken = requireAccessToken(requestOptions.accessToken);

    const headers: Record<string, string> = {
      Accept: "application/json",
      Authorization: `Bearer ${accessToken}`,
    };

    const requestInit: RequestInit = {
      method: requestOptions.method,
      headers,
      credentials: "include",
    };

    if (requestOptions.body !== undefined) {
      headers["Content-Type"] = "application/json";

      requestInit.body = JSON.stringify(requestOptions.body);
    }

    const fetchImpl = options.fetchImpl ?? globalThis.fetch;

    const response = await fetchImpl(path, requestInit);

    const payload = await readJson(response);

    if (!response.ok) {
      const code = extractErrorCode(payload);

      throw new UserModelingApiError(
        code ?? `User Modeling API request failed with status ${response.status}`,
        {
          status: response.status,
          code,
          payload,
        },
      );
    }

    return payload as T;
  }

  function baseProjectPath(projectId: string): string {
    return projectPath(basePath, projectId);
  }

  return {
    proposePersonas(projectId, accessToken) {
      return requestJson(`${baseProjectPath(projectId)}/personas/proposals`, {
        method: "POST",
        accessToken,
      });
    },

    decidePersona(projectId, personaId, request, accessToken) {
      return requestJson(
        `${baseProjectPath(projectId)}/personas/` + `${encodeURIComponent(personaId)}/decision`,
        {
          method: "POST",
          accessToken,
          body: request,
        },
      );
    },

    generateSnapshot(projectId, accessToken) {
      return requestJson(`${baseProjectPath(projectId)}/snapshots/generate`, {
        method: "POST",
        accessToken,
      });
    },

    getCurrentSnapshot(projectId, accessToken) {
      return requestJson(`${baseProjectPath(projectId)}/snapshots/current`, {
        method: "GET",
        accessToken,
      });
    },

    getSnapshotHistory(projectId, accessToken) {
      return requestJson(`${baseProjectPath(projectId)}/snapshots`, {
        method: "GET",
        accessToken,
      });
    },

    proposeRevision(projectId, twinId, request, accessToken) {
      return requestJson(
        `${baseProjectPath(projectId)}/twins/` + `${encodeURIComponent(twinId)}/revisions`,
        {
          method: "POST",
          accessToken,
          body: request,
        },
      );
    },

    getRevision(projectId, diffId, accessToken) {
      return requestJson(`${baseProjectPath(projectId)}/revisions/` + encodeURIComponent(diffId), {
        method: "GET",
        accessToken,
      });
    },

    decideRevision(projectId, diffId, request, accessToken) {
      return requestJson(
        `${baseProjectPath(projectId)}/revisions/` + `${encodeURIComponent(diffId)}/decision`,
        {
          method: "POST",
          accessToken,
          body: request,
        },
      );
    },

    submitGate(projectId, accessToken) {
      return requestJson(`${baseProjectPath(projectId)}/gate/submit`, {
        method: "POST",
        accessToken,
      });
    },

    decideGate(projectId, request, accessToken) {
      return requestJson(`${baseProjectPath(projectId)}/gate/decision`, {
        method: "POST",
        accessToken,
        body: request,
      });
    },

    getCurrentGate(projectId, accessToken) {
      return requestJson(`${baseProjectPath(projectId)}/gate`, {
        method: "GET",
        accessToken,
      });
    },

    getGateEvents(projectId, accessToken) {
      return requestJson(`${baseProjectPath(projectId)}/gate/events`, {
        method: "GET",
        accessToken,
      });
    },

    getReadiness(projectId, accessToken) {
      return requestJson(`${baseProjectPath(projectId)}/readiness`, {
        method: "GET",
        accessToken,
      });
    },
  };
}

export const userModelingApi = createUserModelingApi();
