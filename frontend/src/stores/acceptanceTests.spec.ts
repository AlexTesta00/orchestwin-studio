import { createPinia, setActivePinia } from "pinia";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { AcceptanceTestsApiError, type AcceptanceTestsApi } from "../api/acceptanceTests";
import type {
  AcceptanceTestsOverviewPayload,
  TestCritiquePayload,
  TestRunPayload,
} from "../types/acceptanceTests";
import { type AuthorizedRequest, useAcceptanceTestsStore } from "./acceptanceTests";

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

const CRITIQUE: TestCritiquePayload = {
  twin_id: "33333333-3333-4333-8333-333333333333",
  twin_name: "Reception staff",
  verdict: "CONCERN",
  summary: "The list works, but I could not add a guest.",
  findings: [
    {
      severity: "HIGH",
      text: "The button to add a guest was never reached.",
      about: { criterion: "AC-002", requirement: "REQ-003", screen: "SCR-001" },
      action: "Check the button on the guest list.",
    },
  ],
};

const RUN: TestRunPayload = {
  id: "44444444-4444-4444-8444-444444444444",
  started_at: "2026-09-29T10:00:00+00:00",
  finished_at: "2026-09-29T10:04:00+00:00",
  recorded_at: "2026-09-29T10:04:05+00:00",
  application: { kind: "URL", address: "http://127.0.0.1:5173/" },
  browsers: [{ name: "chrome", version: "151.0.7922.76" }],
  reference: {
    requirements_version_number: 1,
    design_version_number: 4,
    alternative_code: "DES-002",
  },
  summary: { passed: 1, failed: 0, blocked: 1, not_covered: 0, not_run: 0 },
  criteria: [
    { code: "AC-001", status: "PASSED", paths: ["TP-001"] },
    { code: "AC-002", status: "BLOCKED", paths: ["TP-002"] },
  ],
  not_covered: [],
  results: [],
  critiques: [CRITIQUE],
  reviewed_at: "2026-09-29T10:06:00+00:00",
  cost_microusd: 350000,
};

function overview(latest: TestRunPayload | null = RUN): AcceptanceTestsOverviewPayload {
  return {
    project_id: PROJECT_ID,
    reference: { requirements: null, design: null },
    plan_available: true,
    plans: 1,
    runs: latest === null ? 0 : 1,
    latest_run: latest,
  };
}

const authorize: AuthorizedRequest = async <T>(
  operation: (accessToken: string) => Promise<T>,
): Promise<T> => operation(TOKEN);

function fakeApi(read: AcceptanceTestsApi["overview"] = async () => overview()) {
  return { overview: vi.fn<AcceptanceTestsApi["overview"]>(read) };
}

function failure(status: number, code: string): AcceptanceTestsApiError {
  return new AcceptanceTestsApiError("The acceptance tests request failed", {
    status,
    code,
    payload: null,
  });
}

describe("Acceptance Tests store", () => {
  beforeEach(() => {
    setActivePinia(createPinia());
  });

  it("starts empty", () => {
    const store = useAcceptanceTestsStore();

    expect(store.projectId).toBeNull();
    expect(store.overview).toBeNull();
    expect(store.pending).toEqual({ load: false });
    expect(store.failure).toBeNull();
    expect(store.latestRun).toBeNull();
    expect(store.criteria).toEqual([]);
    expect(store.critiques).toEqual([]);
  });

  it("loads the overview of the project and exposes the latest run, its criteria and critiques", async () => {
    const api = fakeApi();
    const store = useAcceptanceTestsStore();

    const loaded = await store.load(PROJECT_ID, authorize, api);

    expect(api.overview).toHaveBeenCalledWith(PROJECT_ID, TOKEN);
    expect(loaded).toEqual(overview());
    expect(store.projectId).toBe(PROJECT_ID);
    expect(store.overview).toEqual(overview());
    expect(store.latestRun?.id).toBe(RUN.id);
    expect(store.criteria.map((item) => [item.code, item.status])).toEqual([
      ["AC-001", "PASSED"],
      ["AC-002", "BLOCKED"],
    ]);
    expect(store.critiques).toEqual([CRITIQUE]);
    expect(store.pending.load).toBe(false);
    expect(store.failure).toBeNull();
  });

  it("gives no run, no criteria and no critiques when nothing was recorded", async () => {
    const store = useAcceptanceTestsStore();

    await store.load(
      PROJECT_ID,
      authorize,
      fakeApi(async () => overview(null)),
    );

    expect(store.overview?.runs).toBe(0);
    expect(store.latestRun).toBeNull();
    expect(store.criteria).toEqual([]);
    expect(store.critiques).toEqual([]);
  });

  it("gives no critiques for a run that the twins have not reviewed", async () => {
    const store = useAcceptanceTestsStore();

    await store.load(
      PROJECT_ID,
      authorize,
      fakeApi(async () => overview({ ...RUN, critiques: [], reviewed_at: null })),
    );

    expect(store.criteria).toHaveLength(2);
    expect(store.critiques).toEqual([]);
  });

  it("reads the overview once per project", async () => {
    const api = fakeApi();
    const store = useAcceptanceTestsStore();

    await store.load(PROJECT_ID, authorize, api);
    const again = await store.load(PROJECT_ID, authorize, api);

    expect(api.overview).toHaveBeenCalledTimes(1);
    expect(again).toEqual(overview());
  });

  it("asks nothing more while the first read is in flight", async () => {
    const pending = deferred<AcceptanceTestsOverviewPayload>();
    const api = fakeApi(() => pending.promise);
    const store = useAcceptanceTestsStore();

    const first = store.load(PROJECT_ID, authorize, api);

    expect(store.pending.load).toBe(true);
    await expect(store.load(PROJECT_ID, authorize, api)).resolves.toBeNull();
    expect(api.overview).toHaveBeenCalledTimes(1);

    pending.resolve(overview());
    await expect(first).resolves.toEqual(overview());

    expect(store.pending.load).toBe(false);
    expect(store.latestRun?.id).toBe(RUN.id);
  });

  it("reads the overview of another project and the first one again after the switch", async () => {
    const api = fakeApi(async (projectId) => ({ ...overview(), project_id: projectId }));
    const store = useAcceptanceTestsStore();

    await store.load(PROJECT_ID, authorize, api);
    await store.load(SECOND_PROJECT_ID, authorize, api);

    expect(api.overview.mock.calls.map((call) => call[0])).toEqual([PROJECT_ID, SECOND_PROJECT_ID]);
    expect(store.projectId).toBe(SECOND_PROJECT_ID);
    expect(store.overview?.project_id).toBe(SECOND_PROJECT_ID);

    await store.load(PROJECT_ID, authorize, api);

    expect(api.overview).toHaveBeenCalledTimes(3);
    expect(store.overview?.project_id).toBe(PROJECT_ID);
  });

  it("captures and rethrows a failed read, then reads again on the next load", async () => {
    const missing = failure(404, "PROJECT_NOT_FOUND");
    const read = vi
      .fn<AcceptanceTestsApi["overview"]>()
      .mockRejectedValueOnce(missing)
      .mockResolvedValueOnce(overview());
    const store = useAcceptanceTestsStore();

    await expect(store.load(PROJECT_ID, authorize, { overview: read })).rejects.toBe(missing);

    expect(store.failure).toEqual({
      message: "The acceptance tests request failed",
      code: "PROJECT_NOT_FOUND",
      status: 404,
    });
    expect(store.overview).toBeNull();
    expect(store.pending.load).toBe(false);

    await store.load(PROJECT_ID, authorize, { overview: read });

    expect(read).toHaveBeenCalledTimes(2);
    expect(store.failure).toBeNull();
    expect(store.latestRun?.id).toBe(RUN.id);
  });

  it("keeps the message of a failure that is not an answer of the Studio", async () => {
    const offline = new TypeError("Failed to fetch");
    const store = useAcceptanceTestsStore();

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

  it("ignores the answer and the failure of a previous project", async () => {
    const answer = deferred<AcceptanceTestsOverviewPayload>();
    const refusal = deferred<AcceptanceTestsOverviewPayload>();
    const missing = failure(404, "PROJECT_NOT_FOUND");
    const read = vi
      .fn<AcceptanceTestsApi["overview"]>()
      .mockReturnValueOnce(answer.promise)
      .mockReturnValueOnce(refusal.promise);
    const store = useAcceptanceTestsStore();

    const answered = store.load(PROJECT_ID, authorize, { overview: read });
    store.activateProject(SECOND_PROJECT_ID);
    const refused = expect(store.load(PROJECT_ID, authorize, { overview: read })).rejects.toBe(
      missing,
    );
    store.activateProject(SECOND_PROJECT_ID);

    answer.resolve(overview());
    refusal.reject(missing);
    await expect(answered).resolves.toEqual(overview());
    await refused;

    expect(read).toHaveBeenCalledTimes(2);
    expect(store.projectId).toBe(SECOND_PROJECT_ID);
    expect(store.overview).toBeNull();
    expect(store.failure).toBeNull();
    expect(store.pending.load).toBe(false);
  });
});
