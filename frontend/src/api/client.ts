import type {
  AuthenticationApi,
  AuthenticationInput,
  AuthenticationResponse,
  ProjectApi,
  ProjectBriefInput,
  ProjectBriefVersionResponse,
  ProjectCreateInput,
  ProjectResponse,
  UserResponse,
} from "./contracts";
import type {
  AgentCatalogResponse,
  AgentTeamApi,
  AgentTeamGateDecisionAction,
  AgentTeamGateDecisionResponse,
  AgentTeamGateSubmissionResponse,
  ProjectReadinessResponse,
  TeamEditResponse,
  TeamProposalEditInput,
  TeamProposalGenerationResponse,
  TeamProposalVersionResponse,
} from "./team-contracts";
import type {
  BriefAssumptionBulkAcceptanceResponse,
  BriefAssumptionCreateInput,
  BriefAssumptionCreationResponse,
  BriefAssumptionDecisionResponse,
  BriefAssumptionResponse,
  HumanGateEventResponse,
  HumanGateResponse,
  ProjectBriefGateDecisionAction,
  ProjectBriefGateDecisionResponse,
  ProjectBriefGateSubmissionResponse,
  ProjectWorkflowApi,
} from "./workflow-contracts";

const DEFAULT_API_BASE_URL = "/api/v1";

type FetchImplementation = typeof fetch;

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null;
}

async function errorDetail(response: Response): Promise<string> {
  try {
    const payload: unknown = await response.json();

    if (isRecord(payload) && typeof payload.detail === "string") {
      return payload.detail;
    }
    if (isRecord(payload) && isRecord(payload.detail)) {
      if (typeof payload.detail.code === "string") return payload.detail.code;
      if (typeof payload.detail.status === "string") return payload.detail.status;
    }
  } catch {
    return "unexpected_api_error";
  }

  return "unexpected_api_error";
}

export type RequestFailureListener = (error: ApiError) => void;

const requestFailureListeners = new Set<RequestFailureListener>();

export function onRequestFailure(listener: RequestFailureListener): () => void {
  requestFailureListeners.add(listener);

  return () => {
    requestFailureListeners.delete(listener);
  };
}

export class ApiError extends Error {
  public readonly status: number;
  public readonly detail: string;

  public constructor(status: number, detail: string) {
    super(detail);

    this.name = "ApiError";
    this.status = status;
    this.detail = detail;

    if (status >= 400) {
      for (const listener of [...requestFailureListeners]) {
        try {
          listener(this);
        } catch {
          continue;
        }
      }
    }
  }
}

export function resolveApiBaseUrl(
  configuredValue: string | undefined = import.meta.env.VITE_API_BASE_URL,
): string {
  const value = configuredValue?.trim() || DEFAULT_API_BASE_URL;

  if (value.startsWith("//")) {
    throw new Error("API base URL must not be protocol-relative");
  }

  if (value.startsWith("/")) {
    const normalizedPath = value.replace(/\/+$/, "");

    if (!normalizedPath) {
      throw new Error("API base URL must not resolve to the application root");
    }

    return normalizedPath;
  }

  const parsed = new URL(value);

  if (!["http:", "https:"].includes(parsed.protocol)) {
    throw new Error("API base URL must use HTTP or HTTPS");
  }

  return parsed.toString().replace(/\/+$/, "");
}

export class ApiClient implements AuthenticationApi, ProjectApi, ProjectWorkflowApi, AgentTeamApi {
  private readonly baseUrl: string;
  private readonly fetchImplementation: FetchImplementation;

  public constructor(
    baseUrl: string = resolveApiBaseUrl(),
    fetchImplementation: FetchImplementation = fetch,
  ) {
    this.baseUrl = resolveApiBaseUrl(baseUrl);

    this.fetchImplementation = fetchImplementation.bind(globalThis);
  }

  public register(input: AuthenticationInput): Promise<AuthenticationResponse> {
    return this.request<AuthenticationResponse>("/auth/register", {
      method: "POST",
      body: JSON.stringify(input),
    });
  }

  public login(input: AuthenticationInput): Promise<AuthenticationResponse> {
    return this.request<AuthenticationResponse>("/auth/login", {
      method: "POST",
      body: JSON.stringify(input),
    });
  }

  public refresh(): Promise<AuthenticationResponse> {
    return this.request<AuthenticationResponse>("/auth/refresh", {
      method: "POST",
    });
  }

  public async logout(): Promise<void> {
    await this.request<void>("/auth/logout", {
      method: "POST",
    });
  }

  public me(accessToken: string): Promise<UserResponse> {
    return this.request<UserResponse>("/auth/me", {
      headers: this.authorization(accessToken),
    });
  }

  public createProject(accessToken: string, input: ProjectCreateInput): Promise<ProjectResponse> {
    return this.request<ProjectResponse>("/projects", {
      method: "POST",
      headers: this.authorization(accessToken),
      body: JSON.stringify(input),
    });
  }

  public listProjects(accessToken: string): Promise<readonly ProjectResponse[]> {
    return this.request<readonly ProjectResponse[]>("/projects", {
      headers: this.authorization(accessToken),
    });
  }

  public getProject(accessToken: string, projectId: string): Promise<ProjectResponse> {
    return this.request<ProjectResponse>(this.projectPath(projectId), {
      headers: this.authorization(accessToken),
    });
  }

  public renameProject(
    accessToken: string,
    projectId: string,
    displayName: string,
  ): Promise<ProjectResponse> {
    return this.request<ProjectResponse>(this.projectPath(projectId), {
      method: "PATCH",
      headers: this.authorization(accessToken),
      body: JSON.stringify({
        display_name: displayName,
      }),
    });
  }

  public async archiveProject(accessToken: string, projectId: string): Promise<void> {
    await this.request<void>(this.projectPath(projectId), {
      method: "DELETE",
      headers: this.authorization(accessToken),
    });
  }

  public createBriefVersion(
    accessToken: string,
    projectId: string,
    input: ProjectBriefInput,
  ): Promise<ProjectBriefVersionResponse> {
    return this.request<ProjectBriefVersionResponse>(
      `${this.projectPath(projectId)}/brief-versions`,
      {
        method: "POST",
        headers: this.authorization(accessToken),
        body: JSON.stringify(input),
      },
    );
  }

  public currentBriefVersion(
    accessToken: string,
    projectId: string,
  ): Promise<ProjectBriefVersionResponse> {
    return this.request<ProjectBriefVersionResponse>(
      `${this.projectPath(projectId)}/brief-versions/current`,
      {
        headers: this.authorization(accessToken),
      },
    );
  }

  public listBriefVersions(
    accessToken: string,
    projectId: string,
  ): Promise<readonly ProjectBriefVersionResponse[]> {
    return this.request<readonly ProjectBriefVersionResponse[]>(
      `${this.projectPath(projectId)}/brief-versions`,
      {
        headers: this.authorization(accessToken),
      },
    );
  }

  public getBriefVersion(
    accessToken: string,
    projectId: string,
    versionNumber: number,
  ): Promise<ProjectBriefVersionResponse> {
    return this.request<ProjectBriefVersionResponse>(
      `${this.projectPath(projectId)}/brief-versions/${encodeURIComponent(versionNumber)}`,
      {
        headers: this.authorization(accessToken),
      },
    );
  }

  public listProjectBriefAssumptions(
    accessToken: string,
    projectId: string,
  ): Promise<readonly BriefAssumptionResponse[]> {
    return this.request<readonly BriefAssumptionResponse[]>(
      `${this.projectPath(projectId)}/brief-assumptions`,
      {
        headers: this.authorization(accessToken),
      },
    );
  }

  public createProjectBriefAssumption(
    accessToken: string,
    projectId: string,
    input: BriefAssumptionCreateInput,
  ): Promise<BriefAssumptionCreationResponse> {
    return this.request<BriefAssumptionCreationResponse>(
      `${this.projectPath(projectId)}/brief-assumptions`,
      {
        method: "POST",
        headers: this.authorization(accessToken),
        body: JSON.stringify(input),
      },
      [409],
    );
  }

  public acceptProjectBriefAssumption(
    accessToken: string,
    projectId: string,
    assumptionId: string,
    reason: string | null = null,
  ): Promise<BriefAssumptionDecisionResponse> {
    return this.request<BriefAssumptionDecisionResponse>(
      `${this.projectPath(projectId)}/brief-assumptions/${encodeURIComponent(assumptionId)}/accept`,
      {
        method: "POST",
        headers: this.authorization(accessToken),
        body: JSON.stringify({
          reason,
        }),
      },
      [409],
    );
  }

  public acceptAllProjectBriefAssumptions(
    accessToken: string,
    projectId: string,
    reason: string | null = null,
  ): Promise<BriefAssumptionBulkAcceptanceResponse> {
    return this.request<BriefAssumptionBulkAcceptanceResponse>(
      `${this.projectPath(projectId)}/brief-assumptions/accept-all`,
      {
        method: "POST",
        headers: this.authorization(accessToken),
        body: JSON.stringify({
          reason,
        }),
      },
      [409],
    );
  }

  public rejectProjectBriefAssumption(
    accessToken: string,
    projectId: string,
    assumptionId: string,
    reason: string,
  ): Promise<BriefAssumptionDecisionResponse> {
    return this.request<BriefAssumptionDecisionResponse>(
      `${this.projectPath(projectId)}/brief-assumptions/${encodeURIComponent(assumptionId)}/reject`,
      {
        method: "POST",
        headers: this.authorization(accessToken),
        body: JSON.stringify({
          reason,
        }),
      },
      [409],
    );
  }

  public submitProjectBriefGate(
    accessToken: string,
    projectId: string,
  ): Promise<ProjectBriefGateSubmissionResponse> {
    return this.request<ProjectBriefGateSubmissionResponse>(
      `${this.projectPath(projectId)}/gates/project-brief/submit`,
      {
        method: "POST",
        headers: this.authorization(accessToken),
      },
      [409],
    );
  }

  public getCurrentProjectBriefGate(
    accessToken: string,
    projectId: string,
  ): Promise<HumanGateResponse> {
    return this.request<HumanGateResponse>(
      `${this.projectPath(projectId)}/gates/project-brief/current`,
      {
        headers: this.authorization(accessToken),
      },
    );
  }

  public listProjectBriefGateEvents(
    accessToken: string,
    projectId: string,
    gateId: string,
  ): Promise<readonly HumanGateEventResponse[]> {
    return this.request<readonly HumanGateEventResponse[]>(
      `${this.projectPath(projectId)}/gates/project-brief/${encodeURIComponent(gateId)}/events`,
      {
        headers: this.authorization(accessToken),
      },
    );
  }

  public decideProjectBriefGate(
    accessToken: string,
    projectId: string,
    action: ProjectBriefGateDecisionAction,
    reason: string | null = null,
  ): Promise<ProjectBriefGateDecisionResponse> {
    return this.request<ProjectBriefGateDecisionResponse>(
      `${this.projectPath(projectId)}/gates/project-brief/decisions`,
      {
        method: "POST",
        headers: this.authorization(accessToken),
        body: JSON.stringify({
          action,
          reason,
        }),
      },
      [409],
    );
  }

  public getAgentCatalog(accessToken: string): Promise<AgentCatalogResponse> {
    return this.request<AgentCatalogResponse>("/agent-catalog", {
      headers: this.authorization(accessToken),
    });
  }

  public generateProjectTeamProposal(
    accessToken: string,
    projectId: string,
  ): Promise<TeamProposalGenerationResponse> {
    return this.request<TeamProposalGenerationResponse>(
      `${this.projectPath(projectId)}/team-proposals`,
      {
        method: "POST",
        headers: this.authorization(accessToken),
      },
      [409],
    );
  }

  public listProjectTeamProposals(
    accessToken: string,
    projectId: string,
  ): Promise<readonly TeamProposalVersionResponse[]> {
    return this.request<readonly TeamProposalVersionResponse[]>(
      `${this.projectPath(projectId)}/team-proposals`,
      {
        headers: this.authorization(accessToken),
      },
    );
  }

  public getCurrentProjectTeamProposal(
    accessToken: string,
    projectId: string,
  ): Promise<TeamProposalVersionResponse> {
    return this.request<TeamProposalVersionResponse>(
      `${this.projectPath(projectId)}/team-proposals/current`,
      {
        headers: this.authorization(accessToken),
      },
    );
  }

  public editCurrentProjectTeamProposal(
    accessToken: string,
    projectId: string,
    input: TeamProposalEditInput,
  ): Promise<TeamEditResponse> {
    return this.request<TeamEditResponse>(
      `${this.projectPath(projectId)}/team-proposals/current`,
      {
        method: "PATCH",
        headers: this.authorization(accessToken),
        body: JSON.stringify(input),
      },
      [409, 422],
    );
  }

  public submitAgentTeamGate(
    accessToken: string,
    projectId: string,
  ): Promise<AgentTeamGateSubmissionResponse> {
    return this.request<AgentTeamGateSubmissionResponse>(
      `${this.projectPath(projectId)}/gates/agent-team/submit`,
      {
        method: "POST",
        headers: this.authorization(accessToken),
      },
      [409],
    );
  }

  public getCurrentAgentTeamGate(
    accessToken: string,
    projectId: string,
  ): Promise<HumanGateResponse> {
    return this.request<HumanGateResponse>(
      `${this.projectPath(projectId)}/gates/agent-team/current`,
      {
        headers: this.authorization(accessToken),
      },
    );
  }

  public listAgentTeamGateEvents(
    accessToken: string,
    projectId: string,
    gateId: string,
  ): Promise<readonly HumanGateEventResponse[]> {
    return this.request<readonly HumanGateEventResponse[]>(
      `${this.projectPath(projectId)}/gates/agent-team/${encodeURIComponent(gateId)}/events`,
      {
        headers: this.authorization(accessToken),
      },
    );
  }

  public decideAgentTeamGate(
    accessToken: string,
    projectId: string,
    action: AgentTeamGateDecisionAction,
    reason: string | null = null,
  ): Promise<AgentTeamGateDecisionResponse> {
    return this.request<AgentTeamGateDecisionResponse>(
      `${this.projectPath(projectId)}/gates/agent-team/decisions`,
      {
        method: "POST",
        headers: this.authorization(accessToken),
        body: JSON.stringify({
          action,
          reason,
        }),
      },
      [409],
    );
  }

  public getProjectWorkflowReadiness(
    accessToken: string,
    projectId: string,
  ): Promise<ProjectReadinessResponse> {
    return this.request<ProjectReadinessResponse>(`${this.projectPath(projectId)}/readiness`, {
      headers: this.authorization(accessToken),
    });
  }

  private authorization(accessToken: string): HeadersInit {
    return {
      Authorization: `Bearer ${accessToken}`,
    };
  }

  private projectPath(projectId: string): string {
    return `/projects/${encodeURIComponent(projectId)}`;
  }

  private async request<T>(
    path: string,
    init: RequestInit = {},
    acceptedStatuses: readonly number[] = [],
  ): Promise<T> {
    const headers = new Headers(init.headers);

    headers.set("Accept", "application/json");

    if (init.body !== undefined) {
      headers.set("Content-Type", "application/json");
    }

    const response = await this.fetchImplementation(`${this.baseUrl}${path}`, {
      ...init,
      headers,
      credentials: "include",
    });

    if (!response.ok && !acceptedStatuses.includes(response.status)) {
      throw new ApiError(response.status, await errorDetail(response));
    }

    if (response.status === 204) {
      return undefined as T;
    }

    const payload: unknown = await response.json();
    // Gate commands use 409 for typed domain results as well as HTTP errors.
    if (!response.ok && isRecord(payload) && "detail" in payload) {
      const detail = payload.detail;
      const code =
        typeof detail === "string"
          ? detail
          : isRecord(detail) && typeof detail.code === "string"
            ? detail.code
            : "unexpected_api_error";
      throw new ApiError(response.status, code);
    }
    return payload as T;
  }
}

export const apiClient = new ApiClient();
