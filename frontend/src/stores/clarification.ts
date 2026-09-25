import { ref } from "vue";
import { defineStore } from "pinia";

import { ApiError } from "@/api/client";
import type {
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
} from "@/api/workflow-contracts";

export interface AuthorizedRequest {
  <T>(operation: (accessToken: string) => Promise<T>): Promise<T>;
}

function errorCode(error: unknown): string {
  if (error instanceof ApiError) {
    return error.detail;
  }

  return "unexpected_error";
}

async function optionalResource<T>(operation: () => Promise<T>): Promise<T | null> {
  try {
    return await operation();
  } catch (error: unknown) {
    if (error instanceof ApiError && error.status === 404) {
      return null;
    }

    throw error;
  }
}

export const useClarificationStore = defineStore("clarification", () => {
  const projectId = ref<string | null>(null);
  const assumptions = ref<readonly BriefAssumptionResponse[]>([]);
  const gate = ref<HumanGateResponse | null>(null);
  const gateEvents = ref<readonly HumanGateEventResponse[]>([]);

  const lastAssumptionCreation = ref<BriefAssumptionCreationResponse | null>(null);
  const lastAssumptionDecision = ref<BriefAssumptionDecisionResponse | null>(null);
  const lastGateSubmission = ref<ProjectBriefGateSubmissionResponse | null>(null);
  const lastGateDecision = ref<ProjectBriefGateDecisionResponse | null>(null);

  const busy = ref(false);
  const errorDetail = ref<string | null>(null);

  function reset(): void {
    projectId.value = null;
    assumptions.value = [];
    gate.value = null;
    gateEvents.value = [];

    lastAssumptionCreation.value = null;
    lastAssumptionDecision.value = null;
    lastGateSubmission.value = null;
    lastGateDecision.value = null;

    busy.value = false;
    errorDetail.value = null;
  }

  async function refreshState(
    targetProjectId: string,
    api: ProjectWorkflowApi,
    authorize: AuthorizedRequest,
  ): Promise<void> {
    const [assumptionsResult, gateResult] = await Promise.all([
      authorize((accessToken) => api.listProjectBriefAssumptions(accessToken, targetProjectId)),
      optionalResource(() =>
        authorize((accessToken) => api.getCurrentProjectBriefGate(accessToken, targetProjectId)),
      ),
    ]);

    assumptions.value = assumptionsResult;
    gate.value = gateResult;

    gateEvents.value =
      gateResult === null
        ? []
        : await authorize((accessToken) =>
            api.listProjectBriefGateEvents(accessToken, targetProjectId, gateResult.id),
          );
  }

  async function perform<T>(operation: () => Promise<T>): Promise<T | null> {
    busy.value = true;
    errorDetail.value = null;

    try {
      return await operation();
    } catch (error: unknown) {
      errorDetail.value = errorCode(error);

      return null;
    } finally {
      busy.value = false;
    }
  }

  async function load(
    targetProjectId: string,
    api: ProjectWorkflowApi,
    authorize: AuthorizedRequest,
  ): Promise<boolean> {
    if (projectId.value !== targetProjectId) {
      reset();
      projectId.value = targetProjectId;
    }

    const result = await perform(async () => {
      await refreshState(targetProjectId, api, authorize);

      return true;
    });

    return result ?? false;
  }

  async function createAssumption(
    targetProjectId: string,
    input: BriefAssumptionCreateInput,
    api: ProjectWorkflowApi,
    authorize: AuthorizedRequest,
  ): Promise<BriefAssumptionCreationResponse | null> {
    return perform(async () => {
      const result = await authorize((accessToken) =>
        api.createProjectBriefAssumption(accessToken, targetProjectId, input),
      );

      lastAssumptionCreation.value = result;

      await refreshState(targetProjectId, api, authorize);

      return result;
    });
  }

  async function acceptAssumption(
    targetProjectId: string,
    assumptionId: string,
    reason: string | null,
    api: ProjectWorkflowApi,
    authorize: AuthorizedRequest,
  ): Promise<BriefAssumptionDecisionResponse | null> {
    return perform(async () => {
      const result = await authorize((accessToken) =>
        api.acceptProjectBriefAssumption(accessToken, targetProjectId, assumptionId, reason),
      );

      lastAssumptionDecision.value = result;

      await refreshState(targetProjectId, api, authorize);

      return result;
    });
  }

  async function rejectAssumption(
    targetProjectId: string,
    assumptionId: string,
    reason: string,
    api: ProjectWorkflowApi,
    authorize: AuthorizedRequest,
  ): Promise<BriefAssumptionDecisionResponse | null> {
    return perform(async () => {
      const result = await authorize((accessToken) =>
        api.rejectProjectBriefAssumption(accessToken, targetProjectId, assumptionId, reason),
      );

      lastAssumptionDecision.value = result;

      await refreshState(targetProjectId, api, authorize);

      return result;
    });
  }

  async function submitGate(
    targetProjectId: string,
    api: ProjectWorkflowApi,
    authorize: AuthorizedRequest,
  ): Promise<ProjectBriefGateSubmissionResponse | null> {
    return perform(async () => {
      const result = await authorize((accessToken) =>
        api.submitProjectBriefGate(accessToken, targetProjectId),
      );

      lastGateSubmission.value = result;

      await refreshState(targetProjectId, api, authorize);

      return result;
    });
  }

  async function decideGate(
    targetProjectId: string,
    action: ProjectBriefGateDecisionAction,
    reason: string | null,
    api: ProjectWorkflowApi,
    authorize: AuthorizedRequest,
  ): Promise<ProjectBriefGateDecisionResponse | null> {
    return perform(async () => {
      const result = await authorize((accessToken) =>
        api.decideProjectBriefGate(accessToken, targetProjectId, action, reason),
      );

      lastGateDecision.value = result;

      await refreshState(targetProjectId, api, authorize);

      return result;
    });
  }

  return {
    projectId,
    assumptions,
    gate,
    gateEvents,

    lastAssumptionCreation,
    lastAssumptionDecision,
    lastGateSubmission,
    lastGateDecision,

    busy,
    errorDetail,

    reset,
    load,
    createAssumption,
    acceptAssumption,
    rejectAssumption,
    submitGate,
    decideGate,
  };
});
