import { ApiRequestError } from "./requestError";
import type { SourcePlatform } from "./sourceGeneration";

export interface BrowserAction {
  kind: "fill" | "click" | "press" | "expect_text" | "expect_contains" | "expect_not_text";
  selector: string;
  value: string | null;
}
export interface BrowserExecutionChecks {
  declared_routes: { route_id: string; path: string }[];
  browser_interactions: { route_id: string; actions: BrowserAction[] }[];
}
export interface JourneyStep {
  action: BrowserAction;
  element_code: string;
  element_label: string;
  screen_code: string;
  screen_title: string;
}
export interface ExecutionJourney {
  status: "DERIVED" | "NOT_DERIVABLE";
  reason?: string;
  source_revision_id: string;
  source_revision_content_hash?: string;
  declared_routes?: { route_id: string; path: string }[];
  browser_interactions?: { route_id: string; actions: BrowserAction[] }[];
  steps?: JourneyStep[];
}

export interface ExecutionOperation {
  id: string;
  source_revision_id: string;
  kind: string;
  content_hash: string;
  state: string;
  gate_current: boolean;
  gate: { id: string; status: string; event_sequence: number };
  payload: {
    command?: Record<string, unknown>;
    execution_id?: string;
    effective_phases?: string[];
    source_revision?: { content_hash: string };
    proposal?: { base_revision: { content_hash: string } };
  };
}
export interface ExecutionLaunchApi {
  history(project: string, platform: SourcePlatform, token: string): Promise<ExecutionOperation[]>;
  journey(project: string, token: string): Promise<ExecutionJourney>;
  prepare(
    project: string,
    platform: SourcePlatform,
    source: { id: string; content_hash: string },
    token: string,
    checks?: BrowserExecutionChecks,
  ): Promise<ExecutionOperation>;
  decide(
    project: string,
    platform: SourcePlatform,
    operation: ExecutionOperation,
    action: "APPROVE" | "CANCEL",
    token: string,
  ): Promise<ExecutionOperation>;
  start(
    project: string,
    platform: SourcePlatform,
    operation: ExecutionOperation,
    token: string,
  ): Promise<{ id: string; report: { status: string } }>;
  applyRepair(
    platform: SourcePlatform,
    operation: ExecutionOperation,
    token: string,
  ): Promise<{ id: string }>;
}

export function createExecutionLaunchApi(
  fetchImpl: typeof fetch = globalThis.fetch.bind(globalThis),
): ExecutionLaunchApi {
  async function request(path: string, token: string, body?: unknown) {
    if (!token.trim())
      throw new ApiRequestError("Authentication required", {
        status: 0,
        code: "ACCESS_TOKEN_REQUIRED",
        payload: null,
      });
    const response = await fetchImpl("/api/v1" + path, {
      method: body === undefined ? "GET" : "POST",
      credentials: "include",
      headers: {
        Accept: "application/json",
        Authorization: `Bearer ${token.trim()}`,
        ...(body === undefined ? {} : { "Content-Type": "application/json" }),
      },
      ...(body === undefined ? {} : { body: JSON.stringify(body) }),
    });
    const data = await response.json().catch(() => null);
    if (!response.ok || data === null)
      throw new ApiRequestError("Execution request failed", {
        status: response.status,
        code: data?.detail?.code ?? data?.detail?.status ?? null,
        payload: data,
      });
    return data;
  }
  const base = (project: string, platform: SourcePlatform) =>
    `/projects/${encodeURIComponent(project)}/${platform}`;
  return {
    history: async (project, platform, token) =>
      (await request(base(project, platform) + "-operations", token)).items,
    journey: async (project, token) =>
      (await request(
        `/projects/${encodeURIComponent(project)}/execution-launch/web/journey`,
        token,
      )) as ExecutionJourney,
    prepare: async (project, platform, source, token, checks) =>
      (
        await request(
          `/projects/${encodeURIComponent(project)}/execution-launch/${platform}/prepare`,
          token,
          {
            source_revision_id: source.id,
            source_revision_content_hash: source.content_hash,
            ...checks,
          },
        )
      ).snapshot,
    decide: async (project, platform, operation, action, token) =>
      (
        await request(
          base(project, platform) + `-operations/${encodeURIComponent(operation.id)}/gate`,
          token,
          {
            expected_content_hash: operation.content_hash,
            expected_gate_event_sequence: operation.gate.event_sequence,
            action,
          },
        )
      ).snapshot,
    start: async (project, platform, operation, token) => {
      let command = operation.payload.command;
      if (!command || operation.kind !== "EXECUTION")
        throw new Error("Incomplete execution operation");
      if (platform === "web") {
        const { execution_runner_image_digest, browser_runner_image_digest, ...fields } = command;
        command = {
          ...fields,
          runners: { execution_runner_image_digest, browser_runner_image_digest },
        };
      }
      return (
        await request(base(project, platform) + "-executions", token, {
          ...command,
          authorization_id: operation.id,
        })
      ).snapshot;
    },
    applyRepair: async (platform, operation, token) => {
      const { execution_id: execution, proposal } = operation.payload;
      if (operation.kind !== "REPAIR" || !execution || !proposal || !operation.gate.id)
        throw new Error("Incomplete repair operation");
      return (
        await request(
          `/${platform}-executions/${encodeURIComponent(execution)}/repair-proposals/${encodeURIComponent(operation.id)}/apply`,
          token,
          {
            base_revision_content_hash: proposal.base_revision.content_hash,
            proposal_content_hash: operation.content_hash,
            approval_id: operation.gate.id,
          },
        )
      ).snapshot;
    },
  };
}
export const executionLaunchApi = createExecutionLaunchApi();
