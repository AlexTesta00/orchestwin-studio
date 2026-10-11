import { accessTokenOf, basePathOf, detailCode, isRecord } from "./http";
import { ApiRequestError } from "./requestError";
import type {
  HumanValidationOutcome,
  HumanValidationOverview,
  HypothesisInput,
  HypothesisRevisionInput,
  OperationalHypothesis,
  ScenarioWalkthrough,
  ValidationOutcomeInput,
} from "../types/humanValidation";

export class HumanValidationApiError extends ApiRequestError {}

export interface HumanValidationApi {
  overview(projectId: string, token: string): Promise<HumanValidationOverview>;
  walkthrough(
    projectId: string,
    scenarioKey: string,
    context: { alternativeId?: string; documentHash?: string },
    token: string,
  ): Promise<ScenarioWalkthrough>;
  createHypothesis(
    projectId: string,
    input: HypothesisInput,
    token: string,
  ): Promise<{ status: "HYPOTHESIS_SAVED"; hypothesis: OperationalHypothesis }>;
  reviseHypothesis(
    projectId: string,
    id: string,
    input: HypothesisRevisionInput,
    token: string,
  ): Promise<{ status: "HYPOTHESIS_REVISED"; hypothesis: OperationalHypothesis }>;
  recordOutcome(
    projectId: string,
    input: ValidationOutcomeInput,
    token: string,
  ): Promise<{ status: "VALIDATION_OUTCOME_RECORDED"; outcome: HumanValidationOutcome }>;
}

export function createHumanValidationApi(
  options: { basePath?: string; fetchImpl?: typeof fetch } = {},
): HumanValidationApi {
  const base = basePathOf(options.basePath ?? "/api/v1", "Validation");
  const fetchImpl = options.fetchImpl ?? globalThis.fetch.bind(globalThis);
  const path = (project: string) => `${base}/projects/${encodeURIComponent(project)}/validation`;

  async function request<T>(
    url: string,
    token: string,
    expected: string,
    body?: unknown,
  ): Promise<T> {
    const response = await fetchImpl(url, {
      method: body === undefined ? "GET" : "POST",
      credentials: "include",
      headers: {
        Accept: "application/json",
        Authorization: `Bearer ${accessTokenOf(token, HumanValidationApiError)}`,
        ...(body === undefined ? {} : { "Content-Type": "application/json" }),
      },
      ...(body === undefined ? {} : { body: JSON.stringify(body) }),
    });
    let payload: unknown;
    try {
      payload = await response.json();
    } catch {
      payload = null;
    }
    if (!response.ok) {
      throw new HumanValidationApiError("The validation request failed", {
        status: response.status,
        code: detailCode(payload),
        payload: null,
      });
    }
    const valid =
      isRecord(payload) &&
      (expected.startsWith("orchestwin.")
        ? payload.kind === expected && payload.schema_version === 1
        : payload.status === expected);
    if (!valid)
      throw new HumanValidationApiError("Validation API returned an invalid response", {
        status: response.status,
        code: "INVALID_API_RESPONSE",
        payload: null,
      });
    return payload as T;
  }

  return {
    overview: (project, token) => request(path(project), token, "orchestwin.human-validation"),
    walkthrough: (project, scenario, context, token) => {
      const query = new URLSearchParams({ scenario_key: scenario });
      if (context.alternativeId !== undefined) query.set("alternative_id", context.alternativeId);
      if (context.documentHash !== undefined) query.set("document_hash", context.documentHash);
      return request(
        `${path(project)}/walkthrough?${query}`,
        token,
        "orchestwin.scenario-walkthrough",
      );
    },
    createHypothesis: (project, input, token) =>
      request(`${path(project)}/hypotheses`, token, "HYPOTHESIS_SAVED", input),
    reviseHypothesis: (project, id, input, token) =>
      request(
        `${path(project)}/hypotheses/${encodeURIComponent(id)}/versions`,
        token,
        "HYPOTHESIS_REVISED",
        input,
      ),
    recordOutcome: (project, input, token) =>
      request(`${path(project)}/outcomes`, token, "VALIDATION_OUTCOME_RECORDED", input),
  };
}

export const humanValidationApi = createHumanValidationApi();
