import { sendGeneration } from "./generationJobs";
import { accessTokenOf, detailCode, isRecord, responseBody } from "./http";
import { ApiRequestError } from "./requestError";

import type {
  ArchetypePayload,
  ArchetypeInput,
  ArchetypeEditRequest,
  ArchetypeArchiveRequest,
  GateCommandPayload,
  GateDecisionRequest,
  HumanGateEventPayload,
  HumanGatePayload,
  PersonaDecisionCommandPayload,
  PersonaDecisionRequest,
  PersonaProposalCommandPayload,
  PersonaVersionPayload,
  ProfileRevisionCommandPayload,
  ProfileRevisionDecisionRequest,
  ProfileRevisionProposalRequest,
  SnapshotGenerationCommandPayload,
  UserModelingReadinessPayload,
  UserModelingSnapshotVersionPayload,
  UserTwinProfileDiffPayload,
} from "../types/userModeling";

const DEFAULT_API_BASE_PATH = "/api/v1";

type HttpMethod = "GET" | "POST" | "PATCH" | "DELETE";

interface RequestOptions {
  method: HttpMethod;
  accessToken: string;
  body?: unknown;
  generationProjectId?: string;
}

export interface UserModelingApiOptions {
  basePath?: string;
  fetchImpl?: typeof fetch;
}

export class UserModelingApiError extends ApiRequestError {}

export interface UserModelingApi {
  getArchetypes(projectId: string, accessToken: string): Promise<ArchetypePayload[]>;
  createArchetype(
    projectId: string,
    request: ArchetypeInput,
    accessToken: string,
  ): Promise<ArchetypePayload>;
  editArchetype(
    projectId: string,
    personaId: string,
    request: ArchetypeEditRequest,
    accessToken: string,
  ): Promise<ArchetypePayload>;
  archiveArchetype(
    projectId: string,
    personaId: string,
    request: ArchetypeArchiveRequest,
    accessToken: string,
  ): Promise<ArchetypePayload>;
  getCurrentPersonas(projectId: string, accessToken: string): Promise<PersonaVersionPayload[]>;
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

function extractErrorCode(payload: unknown): string | null {
  return isRecord(payload) && typeof payload.detail === "string"
    ? payload.detail
    : detailCode(payload);
}

function projectPath(basePath: string, projectId: string): string {
  return `${basePath}/projects/` + `${encodeURIComponent(projectId)}/user-modeling`;
}

function createUserModelingApi(options: UserModelingApiOptions = {}): UserModelingApi {
  const basePath = normalizeBasePath(options.basePath ?? DEFAULT_API_BASE_PATH);

  async function requestJson<T>(path: string, requestOptions: RequestOptions): Promise<T> {
    const accessToken = accessTokenOf(requestOptions.accessToken, UserModelingApiError);

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

    const response =
      requestOptions.generationProjectId === undefined
        ? await fetchImpl(path, requestInit)
        : await sendGeneration(path, requestInit, {
            fetchImpl,
            basePath,
            projectId: requestOptions.generationProjectId,
          });

    const payload = await responseBody(response, UserModelingApiError, "User Modeling");

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

    if (isRecord(payload) && payload.status === "REJECTED") {
      const code = [payload.proposal_issue, payload.candidate_issue, payload.issue].find(
        (value) => typeof value === "string",
      ) as string | undefined;
      throw new UserModelingApiError(code ?? "USER_MODELING_REJECTED", {
        status: response.status,
        code: code ?? "USER_MODELING_REJECTED",
        payload,
      });
    }

    return payload as T;
  }

  function baseProjectPath(projectId: string): string {
    return projectPath(basePath, projectId);
  }

  return {
    getArchetypes(projectId, accessToken) {
      return requestJson(`${baseProjectPath(projectId)}/archetypes`, {
        method: "GET",
        accessToken,
      });
    },
    createArchetype(projectId, request, accessToken) {
      return requestJson(`${baseProjectPath(projectId)}/archetypes`, {
        method: "POST",
        accessToken,
        body: request,
      });
    },
    editArchetype(projectId, personaId, request, accessToken) {
      return requestJson(
        `${baseProjectPath(projectId)}/archetypes/${encodeURIComponent(personaId)}`,
        { method: "PATCH", accessToken, body: request },
      );
    },
    archiveArchetype(projectId, personaId, request, accessToken) {
      return requestJson(
        `${baseProjectPath(projectId)}/archetypes/${encodeURIComponent(personaId)}`,
        { method: "DELETE", accessToken, body: request },
      );
    },
    getCurrentPersonas(projectId, accessToken) {
      return requestJson(`${baseProjectPath(projectId)}/personas`, { method: "GET", accessToken });
    },
    proposePersonas(projectId, accessToken) {
      return requestJson(`${baseProjectPath(projectId)}/personas/proposals`, {
        method: "POST",
        accessToken,
        generationProjectId: projectId,
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
        generationProjectId: projectId,
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
