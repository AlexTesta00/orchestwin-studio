import { ref } from "vue";
import { defineStore } from "pinia";

import { ApiError } from "@/api/client";
import type {
  AgentCatalogResponse,
  AgentIdentifier,
  AgentTeamApi,
  AgentTeamGateDecisionAction,
  AgentTeamGateDecisionResponse,
  AgentTeamGateSubmissionResponse,
  OwnerAgentRationaleInput,
  ProjectReadinessResponse,
  TeamEditResponse,
  TeamProposalGenerationResponse,
  TeamProposalVersionResponse,
} from "@/api/team-contracts";
import type { HumanGateEventResponse, HumanGateResponse } from "@/api/workflow-contracts";

export interface TeamAuthorizedRequest {
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

export const useTeamStore = defineStore("team", () => {
  const projectId = ref<string | null>(null);

  const catalog = ref<AgentCatalogResponse | null>(null);
  const currentVersion = ref<TeamProposalVersionResponse | null>(null);
  const history = ref<readonly TeamProposalVersionResponse[]>([]);
  const gate = ref<HumanGateResponse | null>(null);
  const gateEvents = ref<readonly HumanGateEventResponse[]>([]);
  const readiness = ref<ProjectReadinessResponse | null>(null);

  const lastGeneration = ref<TeamProposalGenerationResponse | null>(null);
  const lastEdit = ref<TeamEditResponse | null>(null);
  const lastGateSubmission = ref<AgentTeamGateSubmissionResponse | null>(null);
  const lastGateDecision = ref<AgentTeamGateDecisionResponse | null>(null);

  const busy = ref(false);
  const errorDetail = ref<string | null>(null);

  function reset(): void {
    projectId.value = null;
    catalog.value = null;
    currentVersion.value = null;
    history.value = [];
    gate.value = null;
    gateEvents.value = [];
    readiness.value = null;

    lastGeneration.value = null;
    lastEdit.value = null;
    lastGateSubmission.value = null;
    lastGateDecision.value = null;

    busy.value = false;
    errorDetail.value = null;
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

  async function refreshState(
    targetProjectId: string,
    api: AgentTeamApi,
    authorize: TeamAuthorizedRequest,
  ): Promise<void> {
    const [catalogResult, historyResult, currentResult, gateResult, readinessResult] =
      await Promise.all([
        authorize((accessToken) => api.getAgentCatalog(accessToken)),
        authorize((accessToken) => api.listProjectTeamProposals(accessToken, targetProjectId)),
        optionalResource(() =>
          authorize((accessToken) =>
            api.getCurrentProjectTeamProposal(accessToken, targetProjectId),
          ),
        ),
        optionalResource(() =>
          authorize((accessToken) => api.getCurrentAgentTeamGate(accessToken, targetProjectId)),
        ),
        authorize((accessToken) => api.getProjectWorkflowReadiness(accessToken, targetProjectId)),
      ]);

    catalog.value = catalogResult;
    history.value = historyResult;
    currentVersion.value = currentResult;
    gate.value = gateResult;
    readiness.value = readinessResult;

    gateEvents.value =
      gateResult === null
        ? []
        : await authorize((accessToken) =>
            api.listAgentTeamGateEvents(accessToken, targetProjectId, gateResult.id),
          );
  }

  async function load(
    targetProjectId: string,
    api: AgentTeamApi,
    authorize: TeamAuthorizedRequest,
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

  async function generateProposal(
    targetProjectId: string,
    api: AgentTeamApi,
    authorize: TeamAuthorizedRequest,
  ): Promise<TeamProposalGenerationResponse | null> {
    return perform(async () => {
      const result = await authorize((accessToken) =>
        api.generateProjectTeamProposal(accessToken, targetProjectId),
      );

      lastGeneration.value = result;

      await refreshState(targetProjectId, api, authorize);

      return result;
    });
  }

  async function editCurrent(
    targetProjectId: string,
    selectedAgentIds: readonly AgentIdentifier[],
    ownerRationales: readonly OwnerAgentRationaleInput[],
    api: AgentTeamApi,
    authorize: TeamAuthorizedRequest,
  ): Promise<TeamEditResponse | null> {
    return perform(async () => {
      const result = await authorize((accessToken) =>
        api.editCurrentProjectTeamProposal(accessToken, targetProjectId, {
          selected_agent_ids: selectedAgentIds,
          owner_rationales: ownerRationales,
        }),
      );

      lastEdit.value = result;

      await refreshState(targetProjectId, api, authorize);

      return result;
    });
  }

  async function submitGate(
    targetProjectId: string,
    api: AgentTeamApi,
    authorize: TeamAuthorizedRequest,
  ): Promise<AgentTeamGateSubmissionResponse | null> {
    return perform(async () => {
      const result = await authorize((accessToken) =>
        api.submitAgentTeamGate(accessToken, targetProjectId),
      );

      lastGateSubmission.value = result;

      await refreshState(targetProjectId, api, authorize);

      return result;
    });
  }

  async function decideGate(
    targetProjectId: string,
    action: AgentTeamGateDecisionAction,
    reason: string | null,
    api: AgentTeamApi,
    authorize: TeamAuthorizedRequest,
  ): Promise<AgentTeamGateDecisionResponse | null> {
    return perform(async () => {
      const result = await authorize((accessToken) =>
        api.decideAgentTeamGate(accessToken, targetProjectId, action, reason),
      );

      lastGateDecision.value = result;

      await refreshState(targetProjectId, api, authorize);

      return result;
    });
  }

  return {
    projectId,
    catalog,
    currentVersion,
    history,
    gate,
    gateEvents,
    readiness,

    lastGeneration,
    lastEdit,
    lastGateSubmission,
    lastGateDecision,

    busy,
    errorDetail,

    reset,
    load,
    generateProposal,
    editCurrent,
    submitGate,
    decideGate,
  };
});
