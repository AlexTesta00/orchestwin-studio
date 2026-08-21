import { defineStore } from "pinia";

import { ArchitectureApiError, architectureApi, type ArchitectureApi } from "../api/architecture";
import type {
  ArchitectureGateDecisionAction,
  ArchitecturePackageDiffPayload,
  ArchitecturePackagePayload,
  ArchitecturePackageVersionPayload,
  ArchitectureReadinessPayload,
  ArchitectureRevisionDecision,
  HumanGateEventPayload,
  HumanGatePayload,
} from "../types/architecture";

export type AuthorizedRequest = <T>(operation: (accessToken: string) => Promise<T>) => Promise<T>;

export type ArchitectureOperation =
  "load" | "generate" | "propose-revision" | "decide-revision" | "submit-gate" | "decide-gate";

export interface ArchitectureStoreError {
  message: string;
  code: string | null;
  status: number | null;
}

interface ArchitectureState {
  projectId: string | null;
  projectEpoch: number;
  current: ArchitecturePackageVersionPayload | null;
  history: ArchitecturePackageVersionPayload[];
  diffs: Record<string, ArchitecturePackageDiffPayload>;
  gate: HumanGatePayload | null;
  gateEvents: HumanGateEventPayload[];
  readiness: ArchitectureReadinessPayload | null;
  pending: Record<ArchitectureOperation, boolean>;
  error: ArchitectureStoreError | null;
}

function emptyPending(): Record<ArchitectureOperation, boolean> {
  return {
    load: false,
    generate: false,
    "propose-revision": false,
    "decide-revision": false,
    "submit-gate": false,
    "decide-gate": false,
  };
}

function storeError(error: unknown): ArchitectureStoreError {
  if (error instanceof ArchitectureApiError) {
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
    message: "An unexpected Architecture error occurred",
    code: null,
    status: null,
  };
}

function upsertVersion(
  versions: ArchitecturePackageVersionPayload[],
  candidate: ArchitecturePackageVersionPayload,
): ArchitecturePackageVersionPayload[] {
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

export const useArchitectureStore = defineStore("architecture", {
  state: (): ArchitectureState => ({
    projectId: null,
    projectEpoch: 0,
    current: null,
    history: [],
    diffs: {},
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

    diffHistory(state): ArchitecturePackageDiffPayload[] {
      return Object.values(state.diffs).sort((left, right) =>
        left.created_at.localeCompare(right.created_at),
      );
    },

    pendingDiffs(state): ArchitecturePackageDiffPayload[] {
      return Object.values(state.diffs).filter((diff) => diff.status === "PROPOSED");
    },

    isReadyForImplementation(state): boolean {
      return state.readiness?.status === "READY_FOR_IMPLEMENTATION";
    },

    criticalTestCount(state): number {
      return (
        state.current?.package.test_plan.test_cases.filter((testCase) =>
          ["CRITICAL", "HIGH"].includes(testCase.priority),
        ).length ?? 0
      );
    },
  },

  actions: {
    resetProjectState(): void {
      this.current = null;
      this.history = [];
      this.diffs = {};
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

    begin(operation: ArchitectureOperation): void {
      this.pending[operation] = true;
      this.error = null;
    },

    finish(operation: ArchitectureOperation, projectId: string, epoch: number): void {
      if (this.isCurrent(projectId, epoch)) {
        this.pending[operation] = false;
      }
    },

    capture(error: unknown, projectId: string, epoch: number): void {
      if (this.isCurrent(projectId, epoch)) {
        this.error = storeError(error);
      }
    },

    applyVersion(version: ArchitecturePackageVersionPayload): void {
      this.current = version;
      this.history = upsertVersion(this.history, version);
    },

    applyDiff(diff: ArchitecturePackageDiffPayload): void {
      this.diffs[diff.id] = diff;
    },

    async refresh(
      projectId: string,
      api: ArchitectureApi,
      authorize: AuthorizedRequest,
      epoch: number,
    ): Promise<void> {
      const readiness = await authorize((token) => api.readiness(projectId, token));
      const [history, diffs] = await Promise.all([
        authorize((token) => api.history(projectId, token)),
        authorize((token) => api.revisionHistory(projectId, token)),
      ]);
      const [gate, gateEvents] = await Promise.all([
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
      this.current = readiness.version;
      this.history = [...history];
      this.diffs = Object.fromEntries(diffs.map((diff) => [diff.id, diff]));
      this.gate = gate;
      this.gateEvents = [...gateEvents];
    },

    async load(
      projectId: string,
      authorize: AuthorizedRequest,
      api: ArchitectureApi = architectureApi,
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
      api: ArchitectureApi = architectureApi,
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
      packageValue: ArchitecturePackagePayload,
      authorize: AuthorizedRequest,
      api: ArchitectureApi = architectureApi,
    ) {
      this.activateProject(projectId);
      const epoch = this.projectEpoch;
      this.begin("propose-revision");

      try {
        const result = await authorize((token) =>
          api.proposeRevision(projectId, { package: packageValue }, token),
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
      decision: ArchitectureRevisionDecision,
      authorize: AuthorizedRequest,
      reason: string | null = null,
      api: ArchitectureApi = architectureApi,
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
      api: ArchitectureApi = architectureApi,
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
      action: ArchitectureGateDecisionAction,
      authorize: AuthorizedRequest,
      reason: string | null = null,
      api: ArchitectureApi = architectureApi,
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
