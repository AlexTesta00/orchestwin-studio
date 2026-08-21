import { defineStore } from "pinia";

import { RequirementsApiError, requirementsApi, type RequirementsApi } from "../api/requirements";
import type {
  HumanGateEventPayload,
  HumanGatePayload,
  RequirementsCoveragePayload,
  RequirementsGateDecisionAction,
  RequirementsReadinessPayload,
  RequirementsRevisionDecision,
  RequirementsSpecificationDiffPayload,
  RequirementsSpecificationPayload,
  RequirementsSpecificationVersionPayload,
  RequirementsTraceabilityPayload,
} from "../types/requirements";

export type AuthorizedRequest = <T>(operation: (accessToken: string) => Promise<T>) => Promise<T>;

export type RequirementsOperation =
  "load" | "generate" | "propose-revision" | "decide-revision" | "submit-gate" | "decide-gate";

export interface RequirementsStoreError {
  message: string;
  code: string | null;
  status: number | null;
}

interface RequirementsState {
  projectId: string | null;
  projectEpoch: number;
  current: RequirementsSpecificationVersionPayload | null;
  history: RequirementsSpecificationVersionPayload[];
  diffs: Record<string, RequirementsSpecificationDiffPayload>;
  traceability: RequirementsTraceabilityPayload | null;
  coverage: RequirementsCoveragePayload | null;
  gate: HumanGatePayload | null;
  gateEvents: HumanGateEventPayload[];
  readiness: RequirementsReadinessPayload | null;
  pending: Record<RequirementsOperation, boolean>;
  error: RequirementsStoreError | null;
}

function emptyPending(): Record<RequirementsOperation, boolean> {
  return {
    load: false,
    generate: false,
    "propose-revision": false,
    "decide-revision": false,
    "submit-gate": false,
    "decide-gate": false,
  };
}

function storeError(error: unknown): RequirementsStoreError {
  if (error instanceof RequirementsApiError) {
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
    message: "An unexpected Requirements error occurred",
    code: null,
    status: null,
  };
}

function upsertVersion(
  versions: RequirementsSpecificationVersionPayload[],
  candidate: RequirementsSpecificationVersionPayload,
): RequirementsSpecificationVersionPayload[] {
  const withoutCandidate = versions.filter((version) => version.id !== candidate.id);

  return [...withoutCandidate, candidate].sort(
    (left, right) => left.version_number - right.version_number,
  );
}

function mergeEvents(
  current: HumanGateEventPayload[],
  incoming: HumanGateEventPayload[],
): HumanGateEventPayload[] {
  const events = new Map<string, HumanGateEventPayload>();

  for (const event of [...current, ...incoming]) {
    events.set(event.id, event);
  }

  return [...events.values()].sort((left, right) => left.sequence_number - right.sequence_number);
}

export const useRequirementsStore = defineStore("requirements", {
  state: (): RequirementsState => ({
    projectId: null,
    projectEpoch: 0,
    current: null,
    history: [],
    diffs: {},
    traceability: null,
    coverage: null,
    gate: null,
    gateEvents: [],
    readiness: null,
    pending: emptyPending(),
    error: null,
  }),

  getters: {
    isBusy(state): boolean {
      return Object.values(state.pending).some(Boolean);
    },

    diffHistory(state): RequirementsSpecificationDiffPayload[] {
      return Object.values(state.diffs).sort((left, right) =>
        left.created_at.localeCompare(right.created_at),
      );
    },

    pendingDiffs(state): RequirementsSpecificationDiffPayload[] {
      return Object.values(state.diffs).filter((diff) => diff.status === "PROPOSED");
    },

    isReadyForDesign(state): boolean {
      return state.readiness?.status === "READY_FOR_DESIGN_EXPLORATION";
    },
  },

  actions: {
    resetProjectState(): void {
      this.current = null;
      this.history = [];
      this.diffs = {};
      this.traceability = null;
      this.coverage = null;
      this.gate = null;
      this.gateEvents = [];
      this.readiness = null;
      this.pending = emptyPending();
      this.error = null;
    },

    activateProject(projectId: string): void {
      if (this.projectId === projectId) {
        return;
      }

      this.projectId = projectId;
      this.projectEpoch += 1;
      this.resetProjectState();
    },

    clearError(): void {
      this.error = null;
    },

    isCurrent(projectId: string, epoch: number): boolean {
      return this.projectId === projectId && this.projectEpoch === epoch;
    },

    begin(operation: RequirementsOperation): void {
      this.pending[operation] = true;
      this.error = null;
    },

    finish(operation: RequirementsOperation, projectId: string, epoch: number): void {
      if (this.isCurrent(projectId, epoch)) {
        this.pending[operation] = false;
      }
    },

    capture(error: unknown, projectId: string, epoch: number): void {
      if (this.isCurrent(projectId, epoch)) {
        this.error = storeError(error);
      }
    },

    applyVersion(version: RequirementsSpecificationVersionPayload): void {
      this.current = version;
      this.history = upsertVersion(this.history, version);
    },

    applyDiff(diff: RequirementsSpecificationDiffPayload): void {
      this.diffs[diff.id] = diff;
    },

    async refresh(
      projectId: string,
      api: RequirementsApi,
      authorize: AuthorizedRequest,
      epoch: number,
    ): Promise<void> {
      const readiness = await authorize((token) => api.readiness(projectId, token));
      const [history, diffs] = await Promise.all([
        authorize((token) => api.history(projectId, token)),
        authorize((token) => api.revisionHistory(projectId, token)),
      ]);
      const version = readiness.version;
      const [traceability, coverage, gate, gateEvents] = await Promise.all([
        version === null
          ? Promise.resolve(null)
          : authorize((token) => api.traceability(projectId, token)),
        version === null
          ? Promise.resolve(null)
          : authorize((token) => api.coverage(projectId, token)),
        readiness.gate === null
          ? Promise.resolve(null)
          : authorize((token) => api.currentGate(projectId, token)),
        readiness.gate === null
          ? Promise.resolve([])
          : authorize((token) => api.gateEvents(projectId, token)),
      ]);

      if (!this.isCurrent(projectId, epoch)) {
        return;
      }

      this.readiness = readiness;
      this.current = version;
      this.history = [...history];
      this.diffs = Object.fromEntries(diffs.map((diff) => [diff.id, diff]));
      this.traceability = traceability;
      this.coverage = coverage;
      this.gate = gate;
      this.gateEvents = [...gateEvents];
    },

    async load(
      projectId: string,
      authorize: AuthorizedRequest,
      api: RequirementsApi = requirementsApi,
    ): Promise<void> {
      this.activateProject(projectId);
      const epoch = this.projectEpoch;
      this.begin("load");

      try {
        await this.refresh(projectId, api, authorize, epoch);
      } catch (error) {
        this.capture(error, projectId, epoch);
        throw error;
      } finally {
        this.finish("load", projectId, epoch);
      }
    },

    async generate(
      projectId: string,
      authorize: AuthorizedRequest,
      api: RequirementsApi = requirementsApi,
    ) {
      this.activateProject(projectId);
      const epoch = this.projectEpoch;
      this.begin("generate");

      try {
        const result = await authorize((token) => api.generate(projectId, token));

        if (this.isCurrent(projectId, epoch) && result.version !== null) {
          this.applyVersion(result.version);
          await this.refresh(projectId, api, authorize, epoch);
        }

        return result;
      } catch (error) {
        this.capture(error, projectId, epoch);
        throw error;
      } finally {
        this.finish("generate", projectId, epoch);
      }
    },

    async proposeRevision(
      projectId: string,
      specification: RequirementsSpecificationPayload,
      authorize: AuthorizedRequest,
      api: RequirementsApi = requirementsApi,
    ) {
      this.activateProject(projectId);
      const epoch = this.projectEpoch;
      this.begin("propose-revision");

      try {
        const result = await authorize((token) =>
          api.proposeRevision(projectId, { specification }, token),
        );

        if (this.isCurrent(projectId, epoch) && result.diff !== null) {
          this.applyDiff(result.diff);
        }

        return result;
      } catch (error) {
        this.capture(error, projectId, epoch);
        throw error;
      } finally {
        this.finish("propose-revision", projectId, epoch);
      }
    },

    async decideRevision(
      projectId: string,
      diffId: string,
      decision: RequirementsRevisionDecision,
      authorize: AuthorizedRequest,
      reason: string | null = null,
      api: RequirementsApi = requirementsApi,
    ) {
      this.activateProject(projectId);
      const epoch = this.projectEpoch;
      this.begin("decide-revision");

      try {
        const result = await authorize((token) =>
          api.decideRevision(
            projectId,
            diffId,
            {
              decision,
              reason,
            },
            token,
          ),
        );

        if (this.isCurrent(projectId, epoch)) {
          if (result.diff !== null) {
            this.applyDiff(result.diff);
          }

          if (result.version !== null) {
            this.applyVersion(result.version);
          }

          await this.refresh(projectId, api, authorize, epoch);
        }

        return result;
      } catch (error) {
        this.capture(error, projectId, epoch);
        throw error;
      } finally {
        this.finish("decide-revision", projectId, epoch);
      }
    },

    async submitGate(
      projectId: string,
      authorize: AuthorizedRequest,
      api: RequirementsApi = requirementsApi,
    ) {
      this.activateProject(projectId);
      const epoch = this.projectEpoch;
      this.begin("submit-gate");

      try {
        const result = await authorize((token) => api.submitGate(projectId, token));

        if (this.isCurrent(projectId, epoch)) {
          if (result.gate !== null) {
            this.gate = result.gate;
          }

          this.gateEvents = mergeEvents(this.gateEvents, result.events);
          await this.refresh(projectId, api, authorize, epoch);
        }

        return result;
      } catch (error) {
        this.capture(error, projectId, epoch);
        throw error;
      } finally {
        this.finish("submit-gate", projectId, epoch);
      }
    },

    async decideGate(
      projectId: string,
      action: RequirementsGateDecisionAction,
      authorize: AuthorizedRequest,
      reason: string | null = null,
      api: RequirementsApi = requirementsApi,
    ) {
      this.activateProject(projectId);
      const epoch = this.projectEpoch;
      this.begin("decide-gate");

      try {
        const result = await authorize((token) =>
          api.decideGate(
            projectId,
            {
              action,
              reason,
            },
            token,
          ),
        );

        if (this.isCurrent(projectId, epoch)) {
          if (result.gate !== null) {
            this.gate = result.gate;
          }

          if (result.event !== null) {
            this.gateEvents = mergeEvents(this.gateEvents, [result.event]);
          }

          await this.refresh(projectId, api, authorize, epoch);
        }

        return result;
      } catch (error) {
        this.capture(error, projectId, epoch);
        throw error;
      } finally {
        this.finish("decide-gate", projectId, epoch);
      }
    },
  },
});
