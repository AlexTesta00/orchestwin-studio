import { createPinia, setActivePinia } from "pinia";
import { beforeEach, describe, expect, it } from "vitest";

import type { ArchitectureApi } from "../api/architecture";
import {
  ARCHITECTURE_DIFF,
  ARCHITECTURE_PACKAGE,
  ARCHITECTURE_PROJECT_ID,
  ARCHITECTURE_READINESS,
  ARCHITECTURE_VERSION,
  PENDING_ARCHITECTURE_GATE,
} from "../test/architectureFixtures";
import type { ArchitectureReadinessPayload } from "../types/architecture";
import { type AuthorizedRequest, useArchitectureStore } from "./architecture";

const SECOND_PROJECT_ID = "00000000-0000-4000-8000-000000000299";

function fakeApi(
  readiness: ArchitectureReadinessPayload = ARCHITECTURE_READINESS,
): ArchitectureApi {
  return {
    generate: async () => ({
      status: "CREATED",
      version: ARCHITECTURE_VERSION,
      issue: null,
      proposal_issue: null,
      persistence_status: "APPENDED",
    }),
    current: async () => ARCHITECTURE_VERSION,
    history: async () => [ARCHITECTURE_VERSION],
    proposeRevision: async () => ({
      status: "CREATED",
      diff: ARCHITECTURE_DIFF,
      version: null,
      issue: null,
      domain_issue: null,
      diff_persistence_status: "CREATED",
      version_persistence_status: null,
    }),
    revisionHistory: async () => [ARCHITECTURE_DIFF],
    getRevision: async () => ARCHITECTURE_DIFF,
    decideRevision: async () => ({
      status: "APPLIED",
      diff: { ...ARCHITECTURE_DIFF, status: "APPROVED" },
      version: ARCHITECTURE_VERSION,
      issue: null,
      domain_issue: null,
      diff_persistence_status: "UPDATED",
      version_persistence_status: "APPENDED",
    }),
    submitGate: async () => ({
      status: "SUBMITTED",
      gate: PENDING_ARCHITECTURE_GATE,
      events: [],
      issue: null,
    }),
    decideGate: async () => ({
      status: "APPLIED",
      gate: { ...PENDING_ARCHITECTURE_GATE, status: "APPROVED" },
      event: null,
      issue: null,
    }),
    currentGate: async () => PENDING_ARCHITECTURE_GATE,
    gateEvents: async () => [],
    readiness: async () => readiness,
  };
}

const authorize: AuthorizedRequest = async <T>(
  operation: (accessToken: string) => Promise<T>,
): Promise<T> => operation("access-token");

describe("Architecture store", () => {
  beforeEach(() => {
    setActivePinia(createPinia());
  });

  it("loads the current package, history, revisions, and Gate 6 state", async () => {
    const store = useArchitectureStore();

    await store.load(ARCHITECTURE_PROJECT_ID, authorize, fakeApi());

    expect(store.current).toEqual(ARCHITECTURE_VERSION);
    expect(store.history).toEqual([ARCHITECTURE_VERSION]);
    expect(store.diffHistory).toEqual([ARCHITECTURE_DIFF]);
    expect(store.gate).toEqual(PENDING_ARCHITECTURE_GATE);
    expect(store.criticalTestCount).toBe(1);
    expect(store.isReadyForImplementation).toBe(false);
    expect(store.error).toBeNull();
  });

  it("creates a complete owner-reviewable package revision", async () => {
    const store = useArchitectureStore();

    const result = await store.proposeRevision(
      ARCHITECTURE_PROJECT_ID,
      ARCHITECTURE_PACKAGE,
      authorize,
      fakeApi(),
    );

    expect(result.diff).toEqual(ARCHITECTURE_DIFF);
    expect(store.pendingDiffs).toEqual([ARCHITECTURE_DIFF]);
  });

  it("discards a stale response after the active project changes", async () => {
    let resolveReadiness!: (value: ArchitectureReadinessPayload) => void;
    const delayedReadiness = new Promise<ArchitectureReadinessPayload>((resolve) => {
      resolveReadiness = resolve;
    });
    const api = fakeApi();
    api.readiness = async () => delayedReadiness;
    const store = useArchitectureStore();
    const load = store.load(ARCHITECTURE_PROJECT_ID, authorize, api);

    store.activateProject(SECOND_PROJECT_ID);
    resolveReadiness(ARCHITECTURE_READINESS);
    await load;

    expect(store.projectId).toBe(SECOND_PROJECT_ID);
    expect(store.current).toBeNull();
    expect(store.history).toEqual([]);
  });
});
