import { createPinia, setActivePinia } from "pinia";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { clearFollowedGenerations } from "../api/generationJobs";
import { UserModelingApiError, userModelingApi } from "../api/userModeling";
import { useUserModelingStore } from "./userModeling";
import type {
  ArchetypePayload,
  HumanGatePayload,
  PersonaVersionPayload,
  UserModelingReadinessPayload,
} from "../types/userModeling";

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

const archetype: ArchetypePayload = {
  persona_id: PERSONA_ID,
  version_id: PERSONA_VERSION_ID,
  version_number: 1,
  name: "Hotel Receptionist",
  description: "Checks in hotel guests",
  role: "Receptionist",
  goals: ["Fast check-in"],
  context: null,
  source: "OWNER_PROVIDED",
  confirmation_status: "CONFIRMED",
  archived: false,
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

  it("recovers saved personas before a User Twin snapshot exists", async () => {
    vi.spyOn(userModelingApi, "getReadiness").mockResolvedValue(readinessWithoutSnapshot);
    vi.spyOn(userModelingApi, "getSnapshotHistory").mockResolvedValue([]);
    vi.spyOn(userModelingApi, "getCurrentPersonas").mockResolvedValue([personaVersion]);
    const store = useUserModelingStore();
    await store.load(PROJECT_ID, ACCESS_TOKEN);
    expect(store.currentPersonas).toEqual([personaVersion]);
  });

  it("stays loading until the last of two loads that overlap has finished", async () => {
    let release: () => void = () => undefined;
    const waiting = new Promise<void>((resolve) => {
      release = resolve;
    });
    vi.spyOn(userModelingApi, "getReadiness").mockResolvedValue(readinessWithoutSnapshot);
    vi.spyOn(userModelingApi, "getSnapshotHistory").mockResolvedValue([]);
    vi.spyOn(userModelingApi, "getCurrentPersonas")
      .mockResolvedValueOnce([])
      .mockImplementationOnce(async () => {
        await waiting;
        return [personaVersion];
      });
    const store = useUserModelingStore();

    const earlier = store.load(PROJECT_ID, ACCESS_TOKEN);
    const later = store.load(PROJECT_ID, ACCESS_TOKEN);
    await earlier;

    expect(store.pending.load).toBe(true);
    expect(store.isBusy).toBe(true);

    release();
    await later;

    expect(store.pending.load).toBe(false);
    expect(store.currentPersonas).toEqual([personaVersion]);
  });

  it("preserves a submitted gate when a token-refresh load finishes afterward", async () => {
    const submitted: HumanGatePayload = {
      id: "gate-three",
      project_id: PROJECT_ID,
      owner_user_id: OWNER_ID,
      gate_type: "USER_MODELING",
      artifact: {
        project_id: PROJECT_ID,
        gate_type: "USER_MODELING",
        artifact_id: "snapshot-one",
        version: 1,
        content_hash: "c".repeat(64),
      },
      iteration: 1,
      max_iterations: 3,
      status: "PENDING_APPROVAL",
      event_sequence: 1,
      created_at: CREATED_AT,
      updated_at: CREATED_AT,
    };
    const afterSubmit = {
      ...readinessWithoutSnapshot,
      gate_exists: true,
      gate_id: submitted.id,
      gate_status: submitted.status,
    };
    const submitResponse = createDeferred();
    const staleHistory = createDeferred();
    const historyStarted = createDeferred();
    vi.spyOn(userModelingApi, "submitGate").mockImplementation(async () => {
      await submitResponse.promise;
      return { outcome: "APPLIED", gate: submitted, events: [], issue: null };
    });
    vi.spyOn(userModelingApi, "getReadiness")
      .mockResolvedValueOnce(readinessWithoutSnapshot)
      .mockResolvedValue(afterSubmit);
    vi.spyOn(userModelingApi, "getSnapshotHistory").mockImplementation(async () => {
      historyStarted.resolve();
      await staleHistory.promise;
      return [];
    });
    vi.spyOn(userModelingApi, "getCurrentPersonas").mockResolvedValue([personaVersion]);
    const store = useUserModelingStore();
    const submit = store.submitGate(PROJECT_ID, ACCESS_TOKEN);
    // Token renewal starts a load while the retried POST is still in flight.
    const staleLoad = store.load(PROJECT_ID, "renewed-token");
    await historyStarted.promise;
    submitResponse.resolve();
    await submit;
    expect(store.currentGate?.status).toBe("PENDING_APPROVAL");
    staleHistory.resolve();
    await staleLoad;
    expect(store.currentGate).toEqual(submitted);
    expect(store.readiness).toEqual(afterSubmit);
    expect(store.isBusy).toBe(false);
  });

  it("does not silently swallow a rejected model proposal", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue(
        fakeResponse({
          status: "REJECTED",
          proposal_issue: "INVALID_PROVIDER_OUTPUT",
          versions: [],
        }),
      ),
    );
    const store = useUserModelingStore();
    await expect(store.proposePersonas(PROJECT_ID, ACCESS_TOKEN)).rejects.toMatchObject({
      code: "INVALID_PROVIDER_OUTPUT",
    });
    expect(store.error?.code).toBe("INVALID_PROVIDER_OUTPUT");
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

      if (url.endsWith("/snapshots") || url.endsWith("/personas")) {
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

    expect(fetchMock).toHaveBeenCalledTimes(3);
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

      if (url.endsWith("/snapshots") || url.endsWith("/personas")) {
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

describe("manual archetypes", () => {
  beforeEach(() => setActivePinia(createPinia()));
  afterEach(() => vi.restoreAllMocks());

  it("loads the active roster even when no snapshot exists", async () => {
    vi.spyOn(userModelingApi, "getReadiness").mockResolvedValue({
      ...readinessWithoutSnapshot,
      archetypes_current: false,
    });
    vi.spyOn(userModelingApi, "getSnapshotHistory").mockResolvedValue([]);
    vi.spyOn(userModelingApi, "getCurrentPersonas").mockResolvedValue([personaVersion]);
    const get = vi.spyOn(userModelingApi, "getArchetypes").mockResolvedValue([archetype]);
    const store = useUserModelingStore();
    await store.load(PROJECT_ID, ACCESS_TOKEN);
    expect(get).toHaveBeenCalledWith(PROJECT_ID, ACCESS_TOKEN);
    expect(store.archetypes).toEqual([archetype]);
    expect(store.currentPersonas).toEqual([personaVersion]);
  });

  it("creates, edits and archives with the displayed version while refreshing readiness", async () => {
    const data = {
      name: archetype.name,
      description: archetype.description!,
      role: archetype.role!,
      goals: archetype.goals,
      context: archetype.context,
    };
    const edited = { ...archetype, version_id: "new-version", version_number: 2 };
    const create = vi.spyOn(userModelingApi, "createArchetype").mockResolvedValue(archetype);
    const edit = vi.spyOn(userModelingApi, "editArchetype").mockResolvedValue(edited);
    const archive = vi
      .spyOn(userModelingApi, "archiveArchetype")
      .mockResolvedValue({ ...edited, archived: true, version_number: 3 });
    vi.spyOn(userModelingApi, "getArchetypes")
      .mockResolvedValueOnce([archetype])
      .mockResolvedValueOnce([edited])
      .mockResolvedValueOnce([]);
    vi.spyOn(userModelingApi, "getCurrentPersonas")
      .mockResolvedValueOnce([personaVersion])
      .mockResolvedValueOnce([{ ...personaVersion, version_number: 2 }])
      .mockResolvedValueOnce([]);
    const readiness = vi
      .spyOn(userModelingApi, "getReadiness")
      .mockResolvedValue({ ...readinessWithoutSnapshot, archetypes_current: false });
    const generate = vi.spyOn(userModelingApi, "generateSnapshot");
    const store = useUserModelingStore();
    await store.saveArchetype(PROJECT_ID, data, ACCESS_TOKEN);
    expect(create).toHaveBeenCalledWith(PROJECT_ID, data, ACCESS_TOKEN);
    expect(store.archetypes).toEqual([archetype]);
    await store.saveArchetype(PROJECT_ID, data, ACCESS_TOKEN, archetype);
    expect(edit).toHaveBeenCalledWith(
      PROJECT_ID,
      PERSONA_ID,
      { ...data, based_on_version_number: 1 },
      ACCESS_TOKEN,
    );
    expect(store.archetypes).toEqual([edited]);
    await store.archiveArchetype(PROJECT_ID, edited, ACCESS_TOKEN);
    expect(archive).toHaveBeenCalledWith(
      PROJECT_ID,
      PERSONA_ID,
      { based_on_version_number: 2 },
      ACCESS_TOKEN,
    );
    expect(store.archetypes).toEqual([]);
    expect(store.currentPersonas).toEqual([]);
    expect(store.readiness?.archetypes_current).toBe(false);
    expect(readiness).toHaveBeenCalledTimes(3);
    expect(generate).not.toHaveBeenCalled();
    expect(store.isBusy).toBe(false);
  });

  it("retains the roster and exposes a version conflict without a silent retry", async () => {
    const conflict = new UserModelingApiError("ARCHETYPE_VERSION_CONFLICT", {
      code: "ARCHETYPE_VERSION_CONFLICT",
      status: 409,
      payload: null,
    });
    const edit = vi.spyOn(userModelingApi, "editArchetype").mockRejectedValue(conflict);
    const get = vi.spyOn(userModelingApi, "getArchetypes");
    const store = useUserModelingStore();
    store.activateProject(PROJECT_ID);
    store.archetypes = [archetype];
    await expect(
      store.saveArchetype(
        PROJECT_ID,
        { name: "Reception", description: "Guests", role: "Desk", goals: [], context: null },
        ACCESS_TOKEN,
        archetype,
      ),
    ).rejects.toBe(conflict);
    expect(edit).toHaveBeenCalledTimes(1);
    expect(get).not.toHaveBeenCalled();
    expect(store.archetypes).toEqual([archetype]);
    expect(store.error?.code).toBe("ARCHETYPE_VERSION_CONFLICT");
    expect(store.isBusy).toBe(false);
  });

  it("ignores a completed mutation from a project that is no longer active", async () => {
    const deferred = createDeferred();
    vi.spyOn(userModelingApi, "archiveArchetype").mockImplementation(async () => {
      await deferred.promise;
      return { ...archetype, archived: true };
    });
    const get = vi.spyOn(userModelingApi, "getArchetypes");
    const store = useUserModelingStore();
    const mutation = store.archiveArchetype(PROJECT_ID, archetype, ACCESS_TOKEN);
    store.activateProject(SECOND_PROJECT_ID);
    deferred.resolve();
    await mutation;
    expect(get).not.toHaveBeenCalled();
    expect(store.projectId).toBe(SECOND_PROJECT_ID);
    expect(store.archetypes).toBeNull();
    expect(store.error).toBeNull();
    expect(store.isBusy).toBe(false);
  });
});

describe("User Modeling generations in the background", () => {
  const JOB_ID = "00000000-0000-4000-8000-0000000000aa";

  function job(operation: string, answer: { status_code: number; body: unknown } | null) {
    return {
      job_id: JOB_ID,
      kind: "REQUEST",
      operation,
      status: answer === null ? "RUNNING" : answer.status_code < 400 ? "SUCCEEDED" : "FAILED",
      stage: answer === null ? "GENERATING" : null,
      attempt: 1,
      started_at: "2026-09-28T10:00:00+00:00",
      finished_at: answer === null ? null : "2026-09-28T10:01:00+00:00",
      alternative_id: null,
      result: null,
      failure: null,
      response: answer,
    };
  }

  function background(operation: string, answer: { status_code: number; body: unknown }) {
    return vi.fn(async (input: Parameters<typeof fetch>[0], init?: Parameters<typeof fetch>[1]) => {
      const url = requestUrl(input);

      if (init?.method === "POST") {
        return fakeResponse(job(operation, null), 202);
      }

      if (url.endsWith(`/generation-jobs/${JOB_ID}`)) {
        return fakeResponse(job(operation, answer));
      }

      return fakeResponse(readinessWithoutSnapshot);
    });
  }

  async function settle<T>(promise: Promise<T>): Promise<T | unknown> {
    const settled = promise.catch((error: unknown) => error);
    await vi.advanceTimersByTimeAsync(2000);
    return settled;
  }

  beforeEach(() => {
    setActivePinia(createPinia());
    vi.useFakeTimers();
  });

  afterEach(() => {
    vi.useRealTimers();
    vi.unstubAllGlobals();
    clearFollowedGenerations();
  });

  it("proposes the profiles through a job and keeps them like a direct answer", async () => {
    const proposal = {
      status: "CREATED",
      issue: null,
      candidate_issue: null,
      proposal_issue: null,
      versions: [personaVersion],
    };
    const fetchMock = background("PERSONA_PROPOSAL", { status_code: 200, body: proposal });
    vi.stubGlobal("fetch", fetchMock);
    const store = useUserModelingStore();

    const result = await settle(store.proposePersonas(PROJECT_ID, ACCESS_TOKEN));

    expect(result).toEqual(proposal);
    expect(store.personaVersions).toEqual([personaVersion]);
    const [, postInit] = fetchMock.mock.calls[0] ?? [];
    expect(postInit?.headers).toMatchObject({ Prefer: "respond-async" });
    expect(fetchMock.mock.calls.filter(([, init]) => init?.method === "POST")).toHaveLength(1);
  });

  it("rejects a refused proposal of the job with the same error as a direct answer", async () => {
    const rejected = {
      status: "REJECTED",
      issue: null,
      candidate_issue: null,
      proposal_issue: "INVALID_PROVIDER_OUTPUT",
      versions: [],
    };
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(fakeResponse(rejected)));
    const expected = await userModelingApi
      .proposePersonas(PROJECT_ID, ACCESS_TOKEN)
      .catch((error: unknown) => error);
    vi.stubGlobal("fetch", background("PERSONA_PROPOSAL", { status_code: 200, body: rejected }));
    const store = useUserModelingStore();

    const actual = await settle(store.proposePersonas(PROJECT_ID, ACCESS_TOKEN));

    expect(expected).toBeInstanceOf(UserModelingApiError);
    expect(actual).toBeInstanceOf(UserModelingApiError);
    expect(actual).toMatchObject({
      message: (expected as UserModelingApiError).message,
      status: (expected as UserModelingApiError).status,
      code: "INVALID_PROVIDER_OUTPUT",
    });
    expect(store.error?.code).toBe("INVALID_PROVIDER_OUTPUT");
  });

  it("reports a refused generation of the twins like a direct answer", async () => {
    const refusal = { detail: { code: "PERSONA_CONFIRMATION_REQUIRED" } };
    vi.stubGlobal("fetch", background("USER_TWIN_GENERATION", { status_code: 409, body: refusal }));
    const store = useUserModelingStore();

    const actual = await settle(store.generateSnapshot(PROJECT_ID, ACCESS_TOKEN));

    expect(actual).toBeInstanceOf(UserModelingApiError);
    expect(store.error).toEqual({
      message: "PERSONA_CONFIRMATION_REQUIRED",
      code: "PERSONA_CONFIRMATION_REQUIRED",
      status: 409,
    });
    expect(store.pending["generate-snapshot"]).toBe(false);
  });
});
