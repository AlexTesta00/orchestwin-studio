import type {
  BrownfieldCapabilityPayload,
  BrownfieldIntakeListPayload,
  BrownfieldIntakeSummaryPayload,
  BrownfieldInventoryPayload,
  ExecutionProfilePayload,
  HighImpactDecisionInput,
  HighImpactExpectedReferenceInput,
  HighImpactOperationInput,
  HighImpactOperationPayload,
  HighImpactOperationResponsePayload,
  HighImpactReadinessPayload,
  HumanGateEventPayload,
  SandboxLogsPayload,
  SandboxRunPayload,
  SnapshotListPayload,
  SnapshotPayload,
  SourceArchiveUploadOptions,
} from "../types/execution";

const DEFAULT_API_BASE_PATH = "/api/v1";

export interface ExecutionApiOptions {
  basePath?: string;
  fetchImpl?: typeof fetch;
}

export interface ExecutionApi {
  uploadSourceArchive(
    projectId: string,
    archive: File,
    accessToken: string,
    options?: SourceArchiveUploadOptions,
  ): Promise<BrownfieldIntakeSummaryPayload>;
  sourceArchiveHistory(
    projectId: string,
    accessToken: string,
  ): Promise<BrownfieldIntakeListPayload>;
  sourceInventory(
    projectId: string,
    intakeId: string,
    accessToken: string,
  ): Promise<BrownfieldInventoryPayload>;
  capabilities(projectId: string, accessToken: string): Promise<BrownfieldCapabilityPayload>;
  profiles(accessToken: string): Promise<ExecutionProfilePayload[]>;
  profile(
    profileId: string,
    accessToken: string,
    version?: string,
  ): Promise<ExecutionProfilePayload>;
  sandboxRuns(projectId: string, accessToken: string): Promise<SandboxRunPayload[]>;
  sandboxRun(runId: string, accessToken: string): Promise<SandboxRunPayload>;
  sandboxLogs(runId: string, accessToken: string): Promise<SandboxLogsPayload>;
  highImpactOperations(
    projectId: string,
    accessToken: string,
  ): Promise<HighImpactOperationPayload[]>;
  createHighImpactOperation(
    projectId: string,
    input: HighImpactOperationInput,
    accessToken: string,
  ): Promise<HighImpactOperationResponsePayload>;
  submitHighImpactGate(
    projectId: string,
    requestId: string,
    input: HighImpactExpectedReferenceInput,
    accessToken: string,
  ): Promise<HighImpactOperationResponsePayload>;
  decideHighImpactGate(
    projectId: string,
    requestId: string,
    input: HighImpactDecisionInput,
    accessToken: string,
  ): Promise<HighImpactOperationResponsePayload>;
  highImpactReadiness(
    projectId: string,
    requestId: string,
    accessToken: string,
  ): Promise<HighImpactReadinessPayload>;
  highImpactEvents(
    projectId: string,
    requestId: string,
    accessToken: string,
  ): Promise<HumanGateEventPayload[]>;
}

export class ExecutionApiError extends Error {
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
    this.name = "ExecutionApiError";
    this.status = options.status;
    this.code = options.code;
    this.payload = options.payload;
  }
}

function normalizedBasePath(value: string): string {
  const normalized = value.trim().replace(/\/+$/, "");

  if (normalized.length === 0 || normalized.startsWith("//")) {
    throw new Error("Execution API base path must be an absolute application path");
  }

  return normalized;
}

function requiredAccessToken(value: string): string {
  const normalized = value.trim();

  if (normalized.length === 0) {
    throw new ExecutionApiError("Authentication is required", {
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
    return text;
  }
}

function projectPath(basePath: string, projectId: string): string {
  return `${basePath}/projects/${encodeURIComponent(projectId)}`;
}

function highImpactPath(basePath: string, projectId: string, requestId?: string): string {
  const root = `${projectPath(basePath, projectId)}/high-impact-operations`;
  return requestId === undefined ? root : `${root}/${encodeURIComponent(requestId)}`;
}

export function createExecutionApi(options: ExecutionApiOptions = {}): ExecutionApi {
  const basePath = normalizedBasePath(options.basePath ?? DEFAULT_API_BASE_PATH);
  const fetchImpl = options.fetchImpl ?? globalThis.fetch.bind(globalThis);

  async function request<T>(path: string, accessToken: string, init: RequestInit = {}): Promise<T> {
    const headers = new Headers(init.headers);
    headers.set("Accept", "application/json");
    headers.set("Authorization", `Bearer ${requiredAccessToken(accessToken)}`);

    if (init.body !== undefined && !(init.body instanceof FormData)) {
      headers.set("Content-Type", "application/json");
    }

    const response = await fetchImpl(path, {
      ...init,
      credentials: "include",
      headers,
    });
    const payload = await responsePayload(response);

    if (!response.ok) {
      throw new ExecutionApiError("The execution request failed", {
        status: response.status,
        code: errorCode(payload),
        payload,
      });
    }

    return payload as T;
  }

  return {
    async uploadSourceArchive(projectId, archive, accessToken, uploadOptions = {}) {
      const parameters = new URLSearchParams();

      if (uploadOptions.requestedTarget !== undefined) {
        parameters.set("requested_target", uploadOptions.requestedTarget);
      }
      for (const runner of [...(uploadOptions.availableRunners ?? [])].sort()) {
        parameters.append("available_runner", runner);
      }

      const query = parameters.size === 0 ? "" : `?${parameters.toString()}`;
      const form = new FormData();
      form.set("archive", archive);

      return request<BrownfieldIntakeSummaryPayload>(
        `${projectPath(basePath, projectId)}/source-archives${query}`,
        accessToken,
        { method: "POST", body: form },
      );
    },

    sourceArchiveHistory(projectId, accessToken) {
      return request<BrownfieldIntakeListPayload>(
        `${projectPath(basePath, projectId)}/source-archives`,
        accessToken,
      );
    },

    sourceInventory(projectId, intakeId, accessToken) {
      return request<BrownfieldInventoryPayload>(
        `${projectPath(basePath, projectId)}/source-archives/${encodeURIComponent(intakeId)}/inventory`,
        accessToken,
      );
    },

    capabilities(projectId, accessToken) {
      return request<BrownfieldCapabilityPayload>(
        `${projectPath(basePath, projectId)}/capabilities`,
        accessToken,
      );
    },

    async profiles(accessToken) {
      const payload = await request<SnapshotListPayload<ExecutionProfilePayload>>(
        `${basePath}/execution-profiles`,
        accessToken,
      );
      return payload.items;
    },

    async profile(profileId, accessToken, version) {
      const parameters = new URLSearchParams();
      if (version !== undefined) {
        parameters.set("profile_version", version);
      }
      const query = parameters.size === 0 ? "" : `?${parameters.toString()}`;
      const payload = await request<SnapshotPayload<ExecutionProfilePayload>>(
        `${basePath}/execution-profiles/${encodeURIComponent(profileId)}${query}`,
        accessToken,
      );
      return payload.snapshot;
    },

    async sandboxRuns(projectId, accessToken) {
      const payload = await request<SnapshotListPayload<SandboxRunPayload>>(
        `${projectPath(basePath, projectId)}/sandbox-runs`,
        accessToken,
      );
      return payload.items;
    },

    async sandboxRun(runId, accessToken) {
      const payload = await request<SnapshotPayload<SandboxRunPayload>>(
        `${basePath}/sandbox-runs/${encodeURIComponent(runId)}`,
        accessToken,
      );
      return payload.snapshot;
    },

    sandboxLogs(runId, accessToken) {
      return request<SandboxLogsPayload>(
        `${basePath}/sandbox-runs/${encodeURIComponent(runId)}/logs`,
        accessToken,
      );
    },

    async highImpactOperations(projectId, accessToken) {
      const payload = await request<SnapshotListPayload<HighImpactOperationPayload>>(
        highImpactPath(basePath, projectId),
        accessToken,
      );
      return payload.items;
    },

    createHighImpactOperation(projectId, input, accessToken) {
      return request<HighImpactOperationResponsePayload>(
        highImpactPath(basePath, projectId),
        accessToken,
        { method: "POST", body: JSON.stringify(input) },
      );
    },

    submitHighImpactGate(projectId, requestId, input, accessToken) {
      return request<HighImpactOperationResponsePayload>(
        `${highImpactPath(basePath, projectId, requestId)}/gate/submit`,
        accessToken,
        { method: "POST", body: JSON.stringify(input) },
      );
    },

    decideHighImpactGate(projectId, requestId, input, accessToken) {
      return request<HighImpactOperationResponsePayload>(
        `${highImpactPath(basePath, projectId, requestId)}/gate/decision`,
        accessToken,
        { method: "POST", body: JSON.stringify(input) },
      );
    },

    highImpactReadiness(projectId, requestId, accessToken) {
      return request<HighImpactReadinessPayload>(
        `${highImpactPath(basePath, projectId, requestId)}/gate`,
        accessToken,
      );
    },

    highImpactEvents(projectId, requestId, accessToken) {
      return request<HumanGateEventPayload[]>(
        `${highImpactPath(basePath, projectId, requestId)}/gate/events`,
        accessToken,
      );
    },
  };
}

export const executionApi = createExecutionApi();
