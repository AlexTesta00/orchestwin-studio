import { defineStore } from "pinia";

import { UserModelingApiError, userModelingApi } from "../api/userModeling";
import type {
  GateCommandPayload,
  GateDecisionAction,
  HumanGateEventPayload,
  HumanGatePayload,
  PersonaOwnerDecision,
  PersonaVersionPayload,
  ProfileReplacementRequest,
  ProfileRevisionDecision,
  UserModelingReadinessPayload,
  UserModelingSnapshotVersionPayload,
  UserTwinProfileDiffPayload,
  UserTwinVersionPayload,
} from "../types/userModeling";

export type UserModelingOperation =
  | "load"
  | "propose-personas"
  | "decide-persona"
  | "generate-snapshot"
  | "propose-revision"
  | "load-revision"
  | "decide-revision"
  | "submit-gate"
  | "decide-gate";

export interface UserModelingStoreError {
  message: string;
  code: string | null;
  status: number | null;
}

interface UserModelingState {
  projectId: string | null;
  projectEpoch: number;

  personaVersions: PersonaVersionPayload[];
  twinVersions: UserTwinVersionPayload[];

  currentSnapshot: UserModelingSnapshotVersionPayload | null;

  snapshotHistory: UserModelingSnapshotVersionPayload[];

  currentGate: HumanGatePayload | null;
  gateEvents: HumanGateEventPayload[];

  readiness: UserModelingReadinessPayload | null;

  diffs: Record<string, UserTwinProfileDiffPayload>;

  pending: Record<UserModelingOperation, boolean>;

  error: UserModelingStoreError | null;
}

function emptyPendingState(): Record<UserModelingOperation, boolean> {
  return {
    load: false,
    "propose-personas": false,
    "decide-persona": false,
    "generate-snapshot": false,
    "propose-revision": false,
    "load-revision": false,
    "decide-revision": false,
    "submit-gate": false,
    "decide-gate": false,
  };
}

function toStoreError(error: unknown): UserModelingStoreError {
  if (error instanceof UserModelingApiError) {
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
    message: "An unexpected User Modeling error occurred",
    code: null,
    status: null,
  };
}

function upsertPersona(
  values: PersonaVersionPayload[],
  candidate: PersonaVersionPayload,
): PersonaVersionPayload[] {
  const existingIndex = values.findIndex((value) => value.persona_id === candidate.persona_id);

  if (existingIndex < 0) {
    return [...values, candidate];
  }

  const result = [...values];

  result[existingIndex] = candidate;

  return result;
}

function upsertTwin(
  values: UserTwinVersionPayload[],
  candidate: UserTwinVersionPayload,
): UserTwinVersionPayload[] {
  const existingIndex = values.findIndex((value) => value.twin_id === candidate.twin_id);

  if (existingIndex < 0) {
    return [...values, candidate];
  }

  const result = [...values];

  result[existingIndex] = candidate;

  return result;
}

function upsertSnapshot(
  values: UserModelingSnapshotVersionPayload[],
  candidate: UserModelingSnapshotVersionPayload,
): UserModelingSnapshotVersionPayload[] {
  const existingIndex = values.findIndex((value) => value.id === candidate.id);

  const result =
    existingIndex < 0
      ? [...values, candidate]
      : values.map((value, index) => (index === existingIndex ? candidate : value));

  return result.sort((left, right) => left.version_number - right.version_number);
}

function mergeGateEvents(
  current: HumanGateEventPayload[],
  incoming: HumanGateEventPayload[],
): HumanGateEventPayload[] {
  const byId = new Map<string, HumanGateEventPayload>();

  for (const event of current) {
    byId.set(event.id, event);
  }

  for (const event of incoming) {
    byId.set(event.id, event);
  }

  return Array.from(byId.values()).sort(
    (left, right) => left.sequence_number - right.sequence_number,
  );
}

export const useUserModelingStore = defineStore("userModeling", {
  state: (): UserModelingState => ({
    projectId: null,
    projectEpoch: 0,

    personaVersions: [],
    twinVersions: [],

    currentSnapshot: null,
    snapshotHistory: [],

    currentGate: null,
    gateEvents: [],

    readiness: null,

    diffs: {},

    pending: emptyPendingState(),

    error: null,
  }),

  getters: {
    isBusy(state): boolean {
      return Object.values(state.pending).some(Boolean);
    },

    currentPersonas(state): PersonaVersionPayload[] {
      if (state.currentSnapshot !== null) {
        return state.currentSnapshot.snapshot.persona_versions;
      }

      return state.personaVersions;
    },

    currentTwins(state): UserTwinVersionPayload[] {
      if (state.currentSnapshot !== null) {
        return state.currentSnapshot.snapshot.twin_versions;
      }

      return state.twinVersions;
    },

    isCurrentSnapshotApproved(state): boolean {
      return state.readiness?.approved_current_snapshot ?? false;
    },

    isReadyForRequirements(state): boolean {
      return state.readiness?.workflow_state === "READY_FOR_REQUIREMENTS_DEFINITION";
    },
  },

  actions: {
    resetProjectState(): void {
      this.personaVersions = [];
      this.twinVersions = [];

      this.currentSnapshot = null;
      this.snapshotHistory = [];

      this.currentGate = null;
      this.gateEvents = [];

      this.readiness = null;
      this.diffs = {};

      this.pending = emptyPendingState();

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

    isRequestCurrent(projectId: string, epoch: number): boolean {
      return this.projectId === projectId && this.projectEpoch === epoch;
    },

    beginOperation(operation: UserModelingOperation): void {
      this.pending[operation] = true;
      this.error = null;
    },

    endOperation(operation: UserModelingOperation, projectId: string, epoch: number): void {
      if (!this.isRequestCurrent(projectId, epoch)) {
        return;
      }

      this.pending[operation] = false;
    },

    captureError(error: unknown, projectId: string, epoch: number): void {
      if (!this.isRequestCurrent(projectId, epoch)) {
        return;
      }

      this.error = toStoreError(error);
    },

    applySnapshot(snapshot: UserModelingSnapshotVersionPayload): void {
      this.currentSnapshot = snapshot;

      this.personaVersions = [...snapshot.snapshot.persona_versions];

      this.twinVersions = [...snapshot.snapshot.twin_versions];

      this.snapshotHistory = upsertSnapshot(this.snapshotHistory, snapshot);
    },

    applyGateResult(result: GateCommandPayload): void {
      if (result.gate !== null) {
        this.currentGate = result.gate;
      }

      this.gateEvents = mergeGateEvents(this.gateEvents, result.events);
    },

    async refreshReadiness(projectId: string, accessToken: string, epoch: number): Promise<void> {
      const readiness = await userModelingApi.getReadiness(projectId, accessToken);

      if (this.isRequestCurrent(projectId, epoch)) {
        this.readiness = readiness;
      }
    },

    async load(projectId: string, accessToken: string): Promise<void> {
      this.activateProject(projectId);

      const epoch = this.projectEpoch;

      this.beginOperation("load");

      try {
        const readiness = await userModelingApi.getReadiness(projectId, accessToken);

        const [currentSnapshot, snapshotHistory, currentGate, gateEvents] = await Promise.all([
          readiness.snapshot_exists
            ? userModelingApi.getCurrentSnapshot(projectId, accessToken)
            : Promise.resolve(null),

          userModelingApi.getSnapshotHistory(projectId, accessToken),

          readiness.gate_exists
            ? userModelingApi.getCurrentGate(projectId, accessToken)
            : Promise.resolve(null),

          readiness.gate_exists
            ? userModelingApi.getGateEvents(projectId, accessToken)
            : Promise.resolve([]),
        ]);

        if (!this.isRequestCurrent(projectId, epoch)) {
          return;
        }

        this.readiness = readiness;

        this.snapshotHistory = [...snapshotHistory];

        this.currentSnapshot = currentSnapshot;

        this.currentGate = currentGate;

        this.gateEvents = [...gateEvents];

        if (currentSnapshot !== null) {
          this.personaVersions = [...currentSnapshot.snapshot.persona_versions];

          this.twinVersions = [...currentSnapshot.snapshot.twin_versions];
        }
      } catch (error) {
        this.captureError(error, projectId, epoch);

        throw error;
      } finally {
        this.endOperation("load", projectId, epoch);
      }
    },

    async proposePersonas(projectId: string, accessToken: string) {
      this.activateProject(projectId);

      const epoch = this.projectEpoch;

      this.beginOperation("propose-personas");

      try {
        const result = await userModelingApi.proposePersonas(projectId, accessToken);

        if (this.isRequestCurrent(projectId, epoch)) {
          this.personaVersions = [...result.versions];
        }

        return result;
      } catch (error) {
        this.captureError(error, projectId, epoch);

        throw error;
      } finally {
        this.endOperation("propose-personas", projectId, epoch);
      }
    },

    async decidePersona(
      projectId: string,
      personaId: string,
      decision: PersonaOwnerDecision,
      accessToken: string,
      reason: string | null = null,
    ) {
      this.activateProject(projectId);

      const epoch = this.projectEpoch;

      this.beginOperation("decide-persona");

      try {
        const result = await userModelingApi.decidePersona(
          projectId,
          personaId,
          {
            decision,
            reason,
          },
          accessToken,
        );

        if (this.isRequestCurrent(projectId, epoch) && result.version !== null) {
          this.personaVersions = upsertPersona(this.personaVersions, result.version);
        }

        return result;
      } catch (error) {
        this.captureError(error, projectId, epoch);

        throw error;
      } finally {
        this.endOperation("decide-persona", projectId, epoch);
      }
    },

    async generateSnapshot(projectId: string, accessToken: string) {
      this.activateProject(projectId);

      const epoch = this.projectEpoch;

      this.beginOperation("generate-snapshot");

      try {
        const result = await userModelingApi.generateSnapshot(projectId, accessToken);

        if (this.isRequestCurrent(projectId, epoch)) {
          if (result.snapshot_version !== null) {
            this.applySnapshot(result.snapshot_version);
          } else {
            this.twinVersions = [...result.twin_versions];
          }

          await this.refreshReadiness(projectId, accessToken, epoch);
        }

        return result;
      } catch (error) {
        this.captureError(error, projectId, epoch);

        throw error;
      } finally {
        this.endOperation("generate-snapshot", projectId, epoch);
      }
    },

    async proposeRevision(
      projectId: string,
      twinId: string,
      replacements: ProfileReplacementRequest[],
      accessToken: string,
    ) {
      this.activateProject(projectId);

      const epoch = this.projectEpoch;

      this.beginOperation("propose-revision");

      try {
        const result = await userModelingApi.proposeRevision(
          projectId,
          twinId,
          {
            replacements,
          },
          accessToken,
        );

        if (this.isRequestCurrent(projectId, epoch) && result.diff !== null) {
          this.diffs[result.diff.id] = result.diff;
        }

        return result;
      } catch (error) {
        this.captureError(error, projectId, epoch);

        throw error;
      } finally {
        this.endOperation("propose-revision", projectId, epoch);
      }
    },

    async loadRevision(projectId: string, diffId: string, accessToken: string) {
      this.activateProject(projectId);

      const epoch = this.projectEpoch;

      this.beginOperation("load-revision");

      try {
        const diff = await userModelingApi.getRevision(projectId, diffId, accessToken);

        if (this.isRequestCurrent(projectId, epoch)) {
          this.diffs[diff.id] = diff;
        }

        return diff;
      } catch (error) {
        this.captureError(error, projectId, epoch);

        throw error;
      } finally {
        this.endOperation("load-revision", projectId, epoch);
      }
    },

    async decideRevision(
      projectId: string,
      diffId: string,
      decision: ProfileRevisionDecision,
      accessToken: string,
      reason: string | null = null,
    ) {
      this.activateProject(projectId);

      const epoch = this.projectEpoch;

      this.beginOperation("decide-revision");

      try {
        const result = await userModelingApi.decideRevision(
          projectId,
          diffId,
          {
            decision,
            reason,
          },
          accessToken,
        );

        if (this.isRequestCurrent(projectId, epoch)) {
          if (result.diff !== null) {
            this.diffs[result.diff.id] = result.diff;
          }

          if (result.twin_version !== null) {
            this.twinVersions = upsertTwin(this.twinVersions, result.twin_version);
          }

          if (result.snapshot_version !== null) {
            this.applySnapshot(result.snapshot_version);
          }

          await this.refreshReadiness(projectId, accessToken, epoch);
        }

        return result;
      } catch (error) {
        this.captureError(error, projectId, epoch);

        throw error;
      } finally {
        this.endOperation("decide-revision", projectId, epoch);
      }
    },

    async submitGate(projectId: string, accessToken: string) {
      this.activateProject(projectId);

      const epoch = this.projectEpoch;

      this.beginOperation("submit-gate");

      try {
        const result = await userModelingApi.submitGate(projectId, accessToken);

        if (this.isRequestCurrent(projectId, epoch)) {
          this.applyGateResult(result);

          await this.refreshReadiness(projectId, accessToken, epoch);
        }

        return result;
      } catch (error) {
        this.captureError(error, projectId, epoch);

        throw error;
      } finally {
        this.endOperation("submit-gate", projectId, epoch);
      }
    },

    async decideGate(
      projectId: string,
      action: GateDecisionAction,
      accessToken: string,
      reason: string | null = null,
    ) {
      this.activateProject(projectId);

      const epoch = this.projectEpoch;

      this.beginOperation("decide-gate");

      try {
        const result = await userModelingApi.decideGate(
          projectId,
          {
            action,
            reason,
          },
          accessToken,
        );

        if (this.isRequestCurrent(projectId, epoch)) {
          this.applyGateResult(result);

          await this.refreshReadiness(projectId, accessToken, epoch);
        }

        return result;
      } catch (error) {
        this.captureError(error, projectId, epoch);

        throw error;
      } finally {
        this.endOperation("decide-gate", projectId, epoch);
      }
    },
  },
});
