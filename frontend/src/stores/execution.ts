import { defineStore } from "pinia";

import { ExecutionApiError, executionApi, type ExecutionApi } from "../api/execution";
import type {
  BrownfieldCapabilityPayload,
  BrownfieldIntakeSummaryPayload,
  BrownfieldInventoryPayload,
  ExecutionProfilePayload,
  HighImpactDecisionInput,
  HighImpactExpectedReferenceInput,
  HighImpactOperationInput,
  HighImpactOperationPayload,
  HighImpactReadinessPayload,
  HumanGateEventPayload,
  SandboxRunPayload,
  SourceArchiveUploadOptions,
} from "../types/execution";

export type AuthorizedRequest = <T>(operation: (accessToken: string) => Promise<T>) => Promise<T>;

export type ExecutionOperation =
  "load" | "upload" | "create-high-impact" | "submit-gate" | "decide-gate";

export interface ExecutionStoreError {
  message: string;
  code: string | null;
  status: number | null;
}

interface ExecutionState {
  projectId: string | null;
  projectEpoch: number;
  intakes: BrownfieldIntakeSummaryPayload[];
  inventory: BrownfieldInventoryPayload | null;
  capability: BrownfieldCapabilityPayload | null;
  profiles: ExecutionProfilePayload[];
  sandboxRuns: SandboxRunPayload[];
  highImpactOperations: HighImpactOperationPayload[];
  highImpactReadiness: HighImpactReadinessPayload | null;
  highImpactEvents: HumanGateEventPayload[];
  pending: Record<ExecutionOperation, boolean>;
  error: ExecutionStoreError | null;
}

function emptyPending(): Record<ExecutionOperation, boolean> {
  return {
    load: false,
    upload: false,
    "create-high-impact": false,
    "submit-gate": false,
    "decide-gate": false,
  };
}

function storeError(error: unknown): ExecutionStoreError {
  if (error instanceof ExecutionApiError) {
    return {
      message: error.message,
      code: error.code,
      status: error.status,
    };
  }

  if (error instanceof Error) {
    return {
      message: error.message,
      code: null,
      status: null,
    };
  }

  return {
    message: "An unexpected execution error occurred",
    code: null,
    status: null,
  };
}

async function optionalCapability(
  api: ExecutionApi,
  projectId: string,
  accessToken: string,
): Promise<BrownfieldCapabilityPayload | null> {
  try {
    return await api.capabilities(projectId, accessToken);
  } catch (error) {
    if (error instanceof ExecutionApiError && error.status === 404) {
      return null;
    }
    throw error;
  }
}

export const useExecutionStore = defineStore("execution", {
  state: (): ExecutionState => ({
    projectId: null,
    projectEpoch: 0,
    intakes: [],
    inventory: null,
    capability: null,
    profiles: [],
    sandboxRuns: [],
    highImpactOperations: [],
    highImpactReadiness: null,
    highImpactEvents: [],
    pending: emptyPending(),
    error: null,
  }),

  getters: {
    isBusy(state): boolean {
      return Object.values(state.pending).some(Boolean);
    },

    currentIntake(state): BrownfieldIntakeSummaryPayload | null {
      return state.intakes.at(-1) ?? null;
    },

    selectedCapability(state): string | null {
      return state.capability?.intake.effective_capability_status ?? null;
    },

    requiresHighImpactApproval(state): boolean {
      return state.highImpactReadiness?.status === "OWNER_APPROVAL_REQUIRED";
    },
  },

  actions: {
    activateProject(projectId: string): void {
      if (this.projectId === projectId) {
        return;
      }

      this.projectId = projectId;
      this.projectEpoch += 1;
      this.intakes = [];
      this.inventory = null;
      this.capability = null;
      this.sandboxRuns = [];
      this.highImpactOperations = [];
      this.highImpactReadiness = null;
      this.highImpactEvents = [];
      this.pending = emptyPending();
      this.error = null;
    },

    isCurrent(projectId: string, epoch: number): boolean {
      return this.projectId === projectId && this.projectEpoch === epoch;
    },

    begin(operation: ExecutionOperation): void {
      this.pending[operation] = true;
      this.error = null;
    },

    finish(operation: ExecutionOperation, projectId: string, epoch: number): void {
      if (this.isCurrent(projectId, epoch)) {
        this.pending[operation] = false;
      }
    },

    capture(error: unknown, projectId: string, epoch: number): void {
      if (this.isCurrent(projectId, epoch)) {
        this.error = storeError(error);
      }
    },

    async load(
      projectId: string,
      authorize: AuthorizedRequest,
      api: ExecutionApi = executionApi,
    ): Promise<void> {
      this.activateProject(projectId);
      const epoch = this.projectEpoch;
      this.begin("load");

      try {
        const [history, capability, profiles, sandboxRuns, highImpactOperations] =
          await Promise.all([
            authorize((token) => api.sourceArchiveHistory(projectId, token)),
            authorize((token) => optionalCapability(api, projectId, token)),
            authorize((token) => api.profiles(token)),
            authorize((token) => api.sandboxRuns(projectId, token)),
            authorize((token) => api.highImpactOperations(projectId, token)),
          ]);

        if (!this.isCurrent(projectId, epoch)) {
          return;
        }

        this.intakes = [...history.items];
        this.capability = capability;
        this.profiles = [...profiles];
        this.sandboxRuns = [...sandboxRuns];
        this.highImpactOperations = [...highImpactOperations];
      } catch (error) {
        this.capture(error, projectId, epoch);
        throw error;
      } finally {
        this.finish("load", projectId, epoch);
      }
    },

    async uploadSourceArchive(
      projectId: string,
      archive: File,
      options: SourceArchiveUploadOptions,
      authorize: AuthorizedRequest,
      api: ExecutionApi = executionApi,
    ): Promise<BrownfieldIntakeSummaryPayload> {
      this.activateProject(projectId);
      const epoch = this.projectEpoch;
      this.begin("upload");

      try {
        const intake = await authorize((token) =>
          api.uploadSourceArchive(projectId, archive, token, options),
        );
        const [history, inventory, capability] = await Promise.all([
          authorize((token) => api.sourceArchiveHistory(projectId, token)),
          authorize((token) => api.sourceInventory(projectId, intake.id, token)),
          authorize((token) => api.capabilities(projectId, token)),
        ]);

        if (this.isCurrent(projectId, epoch)) {
          this.intakes = [...history.items];
          this.inventory = inventory;
          this.capability = capability;
        }

        return intake;
      } catch (error) {
        this.capture(error, projectId, epoch);
        throw error;
      } finally {
        this.finish("upload", projectId, epoch);
      }
    },

    async createHighImpactOperation(
      projectId: string,
      input: HighImpactOperationInput,
      authorize: AuthorizedRequest,
      api: ExecutionApi = executionApi,
    ): Promise<HighImpactOperationPayload> {
      return this.runHighImpactCommand(
        "create-high-impact",
        projectId,
        authorize,
        async (token) => api.createHighImpactOperation(projectId, input, token),
        api,
      );
    },

    async submitHighImpactGate(
      projectId: string,
      requestId: string,
      input: HighImpactExpectedReferenceInput,
      authorize: AuthorizedRequest,
      api: ExecutionApi = executionApi,
    ): Promise<HighImpactOperationPayload> {
      return this.runHighImpactCommand(
        "submit-gate",
        projectId,
        authorize,
        async (token) => api.submitHighImpactGate(projectId, requestId, input, token),
        api,
      );
    },

    async decideHighImpactGate(
      projectId: string,
      requestId: string,
      input: HighImpactDecisionInput,
      authorize: AuthorizedRequest,
      api: ExecutionApi = executionApi,
    ): Promise<HighImpactOperationPayload> {
      return this.runHighImpactCommand(
        "decide-gate",
        projectId,
        authorize,
        async (token) => api.decideHighImpactGate(projectId, requestId, input, token),
        api,
      );
    },

    async runHighImpactCommand(
      operation: Extract<ExecutionOperation, "create-high-impact" | "submit-gate" | "decide-gate">,
      projectId: string,
      authorize: AuthorizedRequest,
      command: (accessToken: string) => Promise<{ operation: HighImpactOperationPayload }>,
      api: ExecutionApi,
    ): Promise<HighImpactOperationPayload> {
      this.activateProject(projectId);
      const epoch = this.projectEpoch;
      this.begin(operation);

      try {
        const result = await authorize(command);
        const requestId = result.operation.version.id;
        const [operations, readiness, events] = await Promise.all([
          authorize((token) => api.highImpactOperations(projectId, token)),
          authorize((token) => api.highImpactReadiness(projectId, requestId, token)),
          authorize((token) => api.highImpactEvents(projectId, requestId, token)).catch(
            (error: unknown) => {
              if (error instanceof ExecutionApiError && error.status === 404) {
                return [];
              }
              throw error;
            },
          ),
        ]);

        if (this.isCurrent(projectId, epoch)) {
          this.highImpactOperations = [...operations];
          this.highImpactReadiness = readiness;
          this.highImpactEvents = [...events];
        }

        return result.operation;
      } catch (error) {
        this.capture(error, projectId, epoch);
        throw error;
      } finally {
        this.finish(operation, projectId, epoch);
      }
    },
  },
});
