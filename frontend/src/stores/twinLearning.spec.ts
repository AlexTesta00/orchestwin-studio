import { createPinia, setActivePinia } from "pinia";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { TwinLearningApiError, type TwinLearningApi } from "../api/twinLearning";
import type { LearningTwinPayload, TwinLearningPayload } from "../types/twinLearning";
import { type AuthorizedRequest, useTwinLearningStore } from "./twinLearning";

const PROJECT_ID = "11111111-1111-4111-8111-111111111111";
const SECOND_PROJECT_ID = "22222222-2222-4222-8222-222222222222";
const TOKEN = "test-token-not-real";

interface Deferred<T> {
  promise: Promise<T>;
  resolve: (value: T) => void;
  reject: (reason: unknown) => void;
}

function deferred<T>(): Deferred<T> {
  let resolve!: (value: T) => void;
  let reject!: (reason: unknown) => void;
  const promise = new Promise<T>((onResolve, onReject) => {
    resolve = onResolve;
    reject = onReject;
  });

  return { promise, resolve, reject };
}

const TWIN: LearningTwinPayload = {
  twin_id: "33333333-3333-4333-8333-333333333333",
  twin_name: "Reception staff",
  profile_version_number: 1,
  development_version_number: 1,
  label: "1.1",
  observations: [
    {
      code: "OBS-001",
      statement: "Reception staff look for a new guest at the top of the list.",
      basis: "Two findings on the acceptance tests.",
      source: "TWIN_CRITIQUE",
      about: { requirement: "REQ-003", screen: null },
      contradicts_profile: null,
      added_in_version: 1,
      approved_at: "2026-09-29T10:00:00+00:00",
      update_id: "44444444-4444-4444-8444-444444444444",
    },
  ],
  retired: [],
  pending_update: null,
  new_material: { changes: 0, tests: 0 },
};

function learning(overrides: Partial<TwinLearningPayload> = {}): TwinLearningPayload {
  return { project_id: PROJECT_ID, update_available: true, twins: [TWIN], ...overrides };
}

const authorize: AuthorizedRequest = async <T>(
  operation: (accessToken: string) => Promise<T>,
): Promise<T> => operation(TOKEN);

function fakeApi(read: TwinLearningApi["overview"] = async () => learning()) {
  return { overview: vi.fn<TwinLearningApi["overview"]>(read) };
}

function failure(status: number, code: string): TwinLearningApiError {
  return new TwinLearningApiError("The twin learning request failed", {
    status,
    code,
    payload: null,
  });
}

describe("Twin Learning store", () => {
  beforeEach(() => {
    setActivePinia(createPinia());
  });

  it("starts empty", () => {
    const store = useTwinLearningStore();

    expect(store.projectId).toBeNull();
    expect(store.overview).toBeNull();
    expect(store.absent).toBe(false);
    expect(store.loaded).toBe(false);
    expect(store.pending).toEqual({ load: false });
    expect(store.failure).toBeNull();
    expect(store.twins).toEqual([]);
    expect(store.updateAvailable).toBe(false);
  });

  it("loads what the twins of the project learned", async () => {
    const api = fakeApi();
    const store = useTwinLearningStore();

    const loaded = await store.load(PROJECT_ID, authorize, api);

    expect(api.overview).toHaveBeenCalledWith(PROJECT_ID, TOKEN);
    expect(loaded).toEqual(learning());
    expect(store.projectId).toBe(PROJECT_ID);
    expect(store.loaded).toBe(true);
    expect(store.absent).toBe(false);
    expect(store.twins).toEqual([TWIN]);
    expect(store.updateAvailable).toBe(true);
    expect(store.pending.load).toBe(false);
    expect(store.failure).toBeNull();
  });

  it("gives no twin while the user modeling is not approved and no model when none is connected", async () => {
    const store = useTwinLearningStore();

    await store.load(
      PROJECT_ID,
      authorize,
      fakeApi(async () => learning({ update_available: false, twins: [] })),
    );

    expect(store.loaded).toBe(true);
    expect(store.twins).toEqual([]);
    expect(store.updateAvailable).toBe(false);
  });

  it("reads once per project, also when the Studio does not serve what the twins learned", async () => {
    const api = fakeApi(async () => null);
    const store = useTwinLearningStore();

    await expect(store.load(PROJECT_ID, authorize, api)).resolves.toBeNull();
    await expect(store.load(PROJECT_ID, authorize, api)).resolves.toBeNull();

    expect(api.overview).toHaveBeenCalledTimes(1);
    expect(store.absent).toBe(true);
    expect(store.loaded).toBe(true);
    expect(store.twins).toEqual([]);
    expect(store.failure).toBeNull();
  });

  it("asks nothing more while the first read is in flight", async () => {
    const pending = deferred<TwinLearningPayload | null>();
    const api = fakeApi(() => pending.promise);
    const store = useTwinLearningStore();

    const first = store.load(PROJECT_ID, authorize, api);

    expect(store.pending.load).toBe(true);
    await expect(store.load(PROJECT_ID, authorize, api)).resolves.toBeNull();
    expect(api.overview).toHaveBeenCalledTimes(1);

    pending.resolve(learning());
    await expect(first).resolves.toEqual(learning());
    expect(store.pending.load).toBe(false);
  });

  it("reads again on reload, also after an answer without the route", async () => {
    const read = vi
      .fn<TwinLearningApi["overview"]>()
      .mockResolvedValueOnce(null)
      .mockResolvedValueOnce(learning());
    const store = useTwinLearningStore();

    await store.load(PROJECT_ID, authorize, { overview: read });
    const again = await store.reload(PROJECT_ID, authorize, { overview: read });

    expect(read).toHaveBeenCalledTimes(2);
    expect(again).toEqual(learning());
    expect(store.absent).toBe(false);
    expect(store.twins).toEqual([TWIN]);
  });

  it("keeps the newest answer when an older read ends later", async () => {
    const older = deferred<TwinLearningPayload | null>();
    const newer = learning({ update_available: false });
    const read = vi
      .fn<TwinLearningApi["overview"]>()
      .mockReturnValueOnce(older.promise)
      .mockResolvedValueOnce(newer);
    const store = useTwinLearningStore();

    const first = store.load(PROJECT_ID, authorize, { overview: read });
    await store.reload(PROJECT_ID, authorize, { overview: read });
    older.resolve(learning());
    await first;

    expect(store.overview).toEqual(newer);
    expect(store.pending.load).toBe(false);
  });

  it("captures and rethrows a failed read, keeps what it had and reads again on the next load", async () => {
    const unavailable = failure(503, "DATABASE_UNAVAILABLE");
    const read = vi
      .fn<TwinLearningApi["overview"]>()
      .mockRejectedValueOnce(unavailable)
      .mockResolvedValueOnce(learning())
      .mockRejectedValueOnce(unavailable);
    const store = useTwinLearningStore();

    await expect(store.load(PROJECT_ID, authorize, { overview: read })).rejects.toBe(unavailable);

    expect(store.failure).toEqual({
      message: "The twin learning request failed",
      code: "DATABASE_UNAVAILABLE",
      status: 503,
    });
    expect(store.loaded).toBe(false);
    expect(store.pending.load).toBe(false);

    await store.load(PROJECT_ID, authorize, { overview: read });

    expect(store.failure).toBeNull();
    expect(store.twins).toEqual([TWIN]);

    await expect(store.reload(PROJECT_ID, authorize, { overview: read })).rejects.toBe(unavailable);

    expect(read).toHaveBeenCalledTimes(3);
    expect(store.failure?.code).toBe("DATABASE_UNAVAILABLE");
    expect(store.twins).toEqual([TWIN]);
  });

  it("keeps the message of a failure that is not an answer of the Studio", async () => {
    const offline = new TypeError("Failed to fetch");
    const store = useTwinLearningStore();

    await expect(
      store.load(
        PROJECT_ID,
        authorize,
        fakeApi(async () => {
          throw offline;
        }),
      ),
    ).rejects.toBe(offline);

    expect(store.failure).toEqual({ message: "Failed to fetch", code: null, status: null });
  });

  it("reads the twins of another project and ignores the answer of the previous one", async () => {
    const answer = deferred<TwinLearningPayload | null>();
    const read = vi
      .fn<TwinLearningApi["overview"]>()
      .mockReturnValueOnce(answer.promise)
      .mockResolvedValueOnce(learning({ project_id: SECOND_PROJECT_ID, twins: [] }));
    const store = useTwinLearningStore();

    const first = store.load(PROJECT_ID, authorize, { overview: read });
    await store.load(SECOND_PROJECT_ID, authorize, { overview: read });
    answer.resolve(learning());
    await first;

    expect(read.mock.calls.map((call) => call[0])).toEqual([PROJECT_ID, SECOND_PROJECT_ID]);
    expect(store.projectId).toBe(SECOND_PROJECT_ID);
    expect(store.overview?.project_id).toBe(SECOND_PROJECT_ID);
    expect(store.twins).toEqual([]);
    expect(store.pending.load).toBe(false);
  });
});
