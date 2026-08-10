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

const DEFAULT_API_BASE_URL = "http://127.0.0.1:8000/api/v1";

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
  } catch {
    return "unexpected_api_error";
  }

  return "unexpected_api_error";
}

export class ApiError extends Error {
  public readonly status: number;
  public readonly detail: string;

  public constructor(status: number, detail: string) {
    super(detail);
    this.name = "ApiError";
    this.status = status;
    this.detail = detail;
  }
}

export function resolveApiBaseUrl(
  configuredValue: string | undefined = import.meta.env.VITE_API_BASE_URL,
): string {
  const value = configuredValue?.trim() || DEFAULT_API_BASE_URL;
  const parsed = new URL(value);

  if (!["http:", "https:"].includes(parsed.protocol)) {
    throw new Error("API base URL must use HTTP or HTTPS");
  }

  return parsed.toString().replace(/\/+$/, "");
}

export class ApiClient implements AuthenticationApi, ProjectApi {
  private readonly baseUrl: string;
  private readonly fetchImplementation: FetchImplementation;

  public constructor(
    baseUrl: string = resolveApiBaseUrl(),
    fetchImplementation: FetchImplementation = fetch,
  ) {
    this.baseUrl = baseUrl.replace(/\/+$/, "");
    this.fetchImplementation = fetchImplementation;
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
    return this.request<ProjectResponse>(`/projects/${projectId}`, {
      headers: this.authorization(accessToken),
    });
  }

  public renameProject(
    accessToken: string,
    projectId: string,
    displayName: string,
  ): Promise<ProjectResponse> {
    return this.request<ProjectResponse>(`/projects/${projectId}`, {
      method: "PATCH",
      headers: this.authorization(accessToken),
      body: JSON.stringify({
        display_name: displayName,
      }),
    });
  }

  public async archiveProject(accessToken: string, projectId: string): Promise<void> {
    await this.request<void>(`/projects/${projectId}`, {
      method: "DELETE",
      headers: this.authorization(accessToken),
    });
  }

  public createBriefVersion(
    accessToken: string,
    projectId: string,
    input: ProjectBriefInput,
  ): Promise<ProjectBriefVersionResponse> {
    return this.request<ProjectBriefVersionResponse>(`/projects/${projectId}/brief-versions`, {
      method: "POST",
      headers: this.authorization(accessToken),
      body: JSON.stringify(input),
    });
  }

  public currentBriefVersion(
    accessToken: string,
    projectId: string,
  ): Promise<ProjectBriefVersionResponse> {
    return this.request<ProjectBriefVersionResponse>(
      `/projects/${projectId}/brief-versions/current`,
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
      `/projects/${projectId}/brief-versions`,
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
      `/projects/${projectId}/brief-versions/${versionNumber}`,
      {
        headers: this.authorization(accessToken),
      },
    );
  }

  private authorization(accessToken: string): HeadersInit {
    return {
      Authorization: `Bearer ${accessToken}`,
    };
  }

  private async request<T>(path: string, init: RequestInit = {}): Promise<T> {
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

    if (!response.ok) {
      throw new ApiError(response.status, await errorDetail(response));
    }

    if (response.status === 204) {
      return undefined as T;
    }

    return (await response.json()) as T;
  }
}

export const apiClient = new ApiClient();
