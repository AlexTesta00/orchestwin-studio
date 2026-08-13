import { createPinia, setActivePinia } from "pinia";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { UserModelingApiError, userModelingApi } from "../api/userModeling";
import { useUserModelingStore } from "./userModeling";
import type { PersonaVersionPayload, UserModelingReadinessPayload } from "../types/userModeling";

const PROJECT_ID = "00000000-0000-4000-8000-000000000010";

const SECOND_PROJECT_ID = "00000000-0000-4000-8000-000000000011";

const OWNER_ID = "00000000-0000-4000-8000-000000000001";

const PERSONA_ID = "00000000-0000-4000-8000-000000000020";

const PERSONA_VERSION_ID = "00000000-0000-4000-8000-000000000021";

const ACCESS_TOKEN = "test-access-token";

const CREATED_AT = "2026-08-13T15:00:00+00:00";

const readinessWithoutSnapshot: UserModelingReadinessPayload = {
  snapshot_exists: false,
  snapshot_version_id: null,
  snapshot_version_number: null,
  snapshot_content_hash: null,

  gate_exists: false,
  gate_id: null,
  gate_status: null,

  approved_current_snapshot: false,
  workflow_state: "USER_MODELING_REQUIRED",

  twins: [],
};

const personaVersion: PersonaVersionPayload = {
  id: PERSONA_VERSION_ID,
  project_id: PROJECT_ID,
  persona_id: PERSONA_ID,
  version_number: 1,
  based_on_version_number: null,
  content_hash: "a".repeat(64),
  created_by_user_id: OWNER_ID,
  created_at: CREATED_AT,

  profile: {
    name: "Hotel Receptionist",
    source: "SYSTEM_PROPOSED",
    kind: "PROTO_PERSONA",
    confirmation_status: "PENDING_CONFIRMATION",
    rejection_reason: null,

    observations: [
      {
        observation_key: "persona.role",

        value: {
          kind: "TEXT",
          text: "Hotel receptionist",
          items: [],
          reason: null,
        },

        epistemic_status: "USER_PROVIDED",

        confidence: 1,

        provenance: [
          {
            source_kind: "PROJECT_BRIEF",
            source_id: "brief-version",
            source_version: 1,
            content_hash: "b".repeat(64),
            locator: "target_users[0]",
            summary: "Project target user",
          },
        ],

        human_validation: "NOT_REQUIRED",

        rationale: null,
      },
    ],
  },
};

function fakeResponse(payload: unknown, status = 200): Response {
  return {
    ok: status >= 200 && status < 300,

    status,

    text: async () => JSON.stringify(payload),
  } as Response;
}

function requestUrl(input: Parameters<typeof fetch>[0]): string {
  return typeof input === "string" ? input : input.toString();
}

function requireFirstItem<T>(values: readonly T[], label: string): T {
  const value = values[0];

  if (value === undefined) {
    throw new Error(`${label} was expected but not found`);
  }

  return value;
}

interface Deferred {
  promise: Promise<void>;
  resolve: () => void;
}

function createDeferred(): Deferred {
  let resolvePromise: (() => void) | undefined;

  const promise = new Promise<void>((resolve) => {
    resolvePromise = resolve;
  });

  return {
    promise,

    resolve() {
      if (resolvePromise === undefined) {
        throw new Error("Deferred resolver was not initialized");
      }

      resolvePromise();
    },
  };
}

describe("User Modeling frontend state", () => {
  beforeEach(() => {
    setActivePinia(createPinia());
  });

  afterEach(() => {
    vi.unstubAllGlobals();
    vi.restoreAllMocks();
  });

  it("sends the authenticated request to the C12 readiness endpoint", async () => {
    const fetchMock = vi.fn(
      async (input: Parameters<typeof fetch>[0], init?: Parameters<typeof fetch>[1]) => {
        void input;
        void init;

        return fakeResponse(readinessWithoutSnapshot);
      },
    );

    vi.stubGlobal("fetch", fetchMock);

    const result = await userModelingApi.getReadiness(PROJECT_ID, ACCESS_TOKEN);

    expect(result.workflow_state).toBe("USER_MODELING_REQUIRED");

    expect(fetchMock).toHaveBeenCalledTimes(1);

    const firstCall = requireFirstItem(fetchMock.mock.calls, "First fetch call");

    const [input, init] = firstCall;

    expect(requestUrl(input)).toBe(`/api/v1/projects/${PROJECT_ID}/user-modeling/readiness`);

    expect(init?.method).toBe("GET");

    expect(init?.credentials).toBe("include");

    expect(init?.headers).toMatchObject({
      Accept: "application/json",
      Authorization: `Bearer ${ACCESS_TOKEN}`,
    });
  });

  it("loads empty User Modeling state without treating missing snapshot as an error", async () => {
    const fetchMock = vi.fn(async (input: Parameters<typeof fetch>[0]) => {
      const url = requestUrl(input);

      if (url.endsWith("/readiness")) {
        return fakeResponse(readinessWithoutSnapshot);
      }

      if (url.endsWith("/snapshots")) {
        return fakeResponse([]);
      }

      throw new Error(`Unexpected request: ${url}`);
    });

    vi.stubGlobal("fetch", fetchMock);

    const store = useUserModelingStore();

    await store.load(PROJECT_ID, ACCESS_TOKEN);

    expect(store.projectId).toBe(PROJECT_ID);

    expect(store.currentSnapshot).toBeNull();

    expect(store.currentGate).toBeNull();

    expect(store.snapshotHistory).toEqual([]);

    expect(store.readiness).toEqual(readinessWithoutSnapshot);

    expect(store.isReadyForRequirements).toBe(false);

    expect(store.isBusy).toBe(false);

    expect(store.error).toBeNull();

    expect(fetchMock).toHaveBeenCalledTimes(2);
  });

  it("keeps proposed proto-personas in Pinia before a snapshot exists", async () => {
    const fetchMock = vi.fn(async (input: Parameters<typeof fetch>[0]) => {
      const url = requestUrl(input);

      expect(url.endsWith("/personas/proposals")).toBe(true);

      return fakeResponse({
        status: "CREATED",
        issue: null,
        candidate_issue: null,
        proposal_issue: null,
        versions: [personaVersion],
      });
    });

    vi.stubGlobal("fetch", fetchMock);

    const store = useUserModelingStore();

    const result = await store.proposePersonas(PROJECT_ID, ACCESS_TOKEN);

    expect(result.status).toBe("CREATED");

    expect(store.personaVersions).toHaveLength(1);

    expect(store.currentPersonas).toHaveLength(1);

    const currentPersona = requireFirstItem(store.currentPersonas, "Current persona");

    expect(currentPersona.profile.confirmation_status).toBe("PENDING_CONFIRMATION");

    const currentObservation = requireFirstItem(
      currentPersona.profile.observations,
      "Current persona observation",
    );

    expect(currentObservation.epistemic_status).toBe("USER_PROVIDED");

    expect(currentObservation.confidence).toBe(1);

    const evidenceReference = requireFirstItem(
      currentObservation.provenance,
      "Observation provenance",
    );

    expect(evidenceReference.source_kind).toBe("PROJECT_BRIEF");
  });

  it("preserves API conflict codes in store error state", async () => {
    const fetchMock = vi.fn(async () =>
      fakeResponse(
        {
          detail: {
            code: "PERSONA_CONFIRMATION_REQUIRED",
          },
        },
        409,
      ),
    );

    vi.stubGlobal("fetch", fetchMock);

    const store = useUserModelingStore();

    await expect(store.generateSnapshot(PROJECT_ID, ACCESS_TOKEN)).rejects.toBeInstanceOf(
      UserModelingApiError,
    );

    expect(store.error).toEqual({
      message: "PERSONA_CONFIRMATION_REQUIRED",
      code: "PERSONA_CONFIRMATION_REQUIRED",
      status: 409,
    });

    expect(store.pending["generate-snapshot"]).toBe(false);

    expect(store.isBusy).toBe(false);
  });

  it("does not let a stale project request overwrite a newly activated project", async () => {
    const firstRequest = createDeferred();

    const fetchMock = vi.fn(async (input: Parameters<typeof fetch>[0]) => {
      const url = requestUrl(input);

      if (url.includes(PROJECT_ID) && url.endsWith("/readiness")) {
        await firstRequest.promise;

        return fakeResponse(readinessWithoutSnapshot);
      }

      if (url.includes(SECOND_PROJECT_ID) && url.endsWith("/readiness")) {
        return fakeResponse({
          ...readinessWithoutSnapshot,

          workflow_state: "USER_MODELING_REVIEW_REQUIRED",
        });
      }

      if (url.endsWith("/snapshots")) {
        return fakeResponse([]);
      }

      throw new Error(`Unexpected request: ${url}`);
    });

    vi.stubGlobal("fetch", fetchMock);

    const store = useUserModelingStore();

    const staleLoad = store.load(PROJECT_ID, ACCESS_TOKEN);

    store.activateProject(SECOND_PROJECT_ID);

    const currentLoad = store.load(SECOND_PROJECT_ID, ACCESS_TOKEN);

    await currentLoad;

    firstRequest.resolve();

    await staleLoad;

    expect(store.projectId).toBe(SECOND_PROJECT_ID);

    expect(store.readiness?.workflow_state).toBe("USER_MODELING_REVIEW_REQUIRED");

    expect(store.error).toBeNull();
  });
});
