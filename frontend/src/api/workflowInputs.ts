import { ApiRequestError } from "./requestError";
import type { HumanGatePayload } from "@/types/design";
import type {
  OwnerDefinitionInput,
  OwnerProfilesInput,
  OwnerTeamInput,
  ProvidedPrototype,
  ProvidedPrototypeGateResult,
  ProvidedPrototypeInput,
  WorkflowDecision,
  WorkflowDecisionInput,
  WorkflowInputsPayload,
} from "@/types/workflowInputs";

export class WorkflowInputsApiError extends ApiRequestError {}

export function createWorkflowInputsApi(
  options: { basePath?: string; fetchImpl?: typeof fetch } = {},
) {
  const base = (options.basePath ?? "/api/v1").replace(/\/+$/, "");

  async function request<T>(
    projectId: string,
    suffix: string,
    token: string,
    body?: unknown,
  ): Promise<T> {
    if (!token.trim())
      throw new WorkflowInputsApiError("Authentication is required", {
        status: 0,
        code: "ACCESS_TOKEN_REQUIRED",
        payload: null,
      });
    const response = await (options.fetchImpl ?? globalThis.fetch)(
      `${base}/projects/${encodeURIComponent(projectId)}${suffix}`,
      {
        method: body === undefined ? "GET" : "POST",
        credentials: "include",
        headers: {
          Accept: "application/json",
          Authorization: `Bearer ${token}`,
          ...(body === undefined ? {} : { "Content-Type": "application/json" }),
        },
        ...(body === undefined ? {} : { body: JSON.stringify(body) }),
      },
    );
    const raw = await response.text();
    let payload: unknown;
    try {
      payload = raw.trim() ? JSON.parse(raw) : null;
    } catch {
      throw new WorkflowInputsApiError("Invalid response", {
        status: response.status,
        code: "INVALID_API_RESPONSE",
        payload: null,
      });
    }
    if (!response.ok) {
      const detail = (payload as { detail?: { code?: string; message?: string } } | null)?.detail;
      throw new WorkflowInputsApiError(
        detail?.message ?? detail?.code ?? "Workflow inputs request failed",
        {
          status: response.status,
          code: detail?.code ?? null,
          payload,
        },
      );
    }
    return payload as T;
  }

  return {
    read: (id: string, token: string) =>
      request<WorkflowInputsPayload>(id, "/workflow-inputs", token),
    decide: (id: string, body: WorkflowDecisionInput, token: string) =>
      request<WorkflowDecision>(id, "/workflow-inputs/decisions", token, body),
    team: (id: string, body: OwnerTeamInput, token: string) =>
      request<unknown>(id, "/team/owner-proposals", token, body),
    profiles: (id: string, body: OwnerProfilesInput, token: string) =>
      request<unknown>(id, "/user-modeling/owner-profiles", token, body),
    definition: (id: string, body: OwnerDefinitionInput, token: string) =>
      request<unknown>(id, "/requirements/owner-specifications", token, body),
    prototypes: (id: string, token: string) =>
      request<{ prototypes: ProvidedPrototype[]; limits: string[] }>(
        id,
        "/provided-prototypes",
        token,
      ),
    currentPrototype: (id: string, token: string) =>
      request<ProvidedPrototype>(id, "/provided-prototypes/current", token),
    savePrototype: (id: string, body: ProvidedPrototypeInput, token: string) =>
      request<ProvidedPrototype>(id, "/provided-prototypes", token, body),
    prototypeGate: (id: string, token: string) =>
      request<HumanGatePayload>(id, "/provided-prototypes/gate/current", token),
    submitPrototype: (id: string, token: string) =>
      request<ProvidedPrototypeGateResult>(id, "/provided-prototypes/gate/submit", token, {}),
    decidePrototype: (
      id: string,
      body: { action: "APPROVE" | "REJECT" | "REQUEST_REVISION"; reason?: string },
      token: string,
    ) =>
      request<ProvidedPrototypeGateResult>(id, "/provided-prototypes/gate/decision", token, body),
    prototypeDocument: (id: string, prototypeId: string, token: string, screen?: string) =>
      request<{ html: string; title: string }>(
        id,
        `/provided-prototypes/${encodeURIComponent(prototypeId)}/document${screen ? `?entry_screen=${encodeURIComponent(screen)}` : ""}`,
        token,
      ),
  };
}

export type WorkflowInputsApi = ReturnType<typeof createWorkflowInputsApi>;
export const workflowInputsApi = createWorkflowInputsApi();
