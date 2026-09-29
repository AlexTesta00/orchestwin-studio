import { createPinia, setActivePinia } from "pinia";

import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import {
  BASE_DESIGN_PACKAGE,
  DESIGN_ALTERNATIVE_ID,
  DESIGN_PROJECT_ID,
  UNSELECTED_DESIGN_VERSION,
} from "@/test/designFixtures";

import { DesignIterationsApiError, type DesignIterationsApi } from "../api/designIterations";
import type { DesignMockupsApi } from "../api/designMockups";
import type { DesignPackageVersionPayload } from "../types/design";
import type {
  BoundGeneratedMockupPayload,
  DesignIterationPayload,
  GenerationJobPayload,
  MockupResultPayload,
} from "../types/designMockups";
import {
  DESIGN_CONTEXT_CHANGED,
  normalizedIterationRequest,
  useDesignIterationsStore,
} from "./designIterations";
import {
  GENERATION_JOB_NOT_FOUND,
  GENERATION_POLL_TIMEOUT,
  POLL_INTERVAL_MILLISECONDS,
  POLL_LIMIT_MILLISECONDS,
  type AuthorizedMockupRequest,
} from "./designMockups";

const PROJECT = DESIGN_PROJECT_ID;
const OTHER_PROJECT = "00000000-0000-4000-8000-000000000999";
const SELECTED = DESIGN_ALTERNATIVE_ID;
const HASH_TWO = "2".repeat(64);
const HASH_THREE = "3".repeat(64);
const REQUEST = "Sposta il pulsante principale in alto";
const RULE = "Il pulsante principale resta in alto";

const authorize: AuthorizedMockupRequest = (operation) => operation("token");

function versionId(hash: string): string {
  return `00000000-0000-4000-8000-${hash.slice(0, 12)}`;
}

function generatedMockup(): BoundGeneratedMockupPayload {
  return {
    mockup: {
      contract_version: 1,
      design_alternative_id: SELECTED,
      title: "Reservation desk",
      styles: ".desk{display:grid}",
      screens: [{ code: "SCR-001", title: "Desk", state: "DEFAULT", markup: "<h1>Desk</h1>" }],
    },
    requirement_ids_by_code: {},
  };
}

function appliedVersion(hash: string, generated = true): DesignPackageVersionPayload {
  return {
    ...UNSELECTED_DESIGN_VERSION,
    id: versionId(hash),
    content_hash: hash,
    package: {
      ...BASE_DESIGN_PACKAGE,
      owner_selected_alternative_id: SELECTED,
      generated_mockup: generated ? generatedMockup() : null,
      owner_assertions: [],
    },
  };
}

function proposal(hash = HASH_TWO, generationId = "iteration-1"): MockupResultPayload {
  return {
    status: "MOCKUP_GENERATED",
    generation_id: generationId,
    design_version_id: versionId(hash),
    design_content_hash: hash,
    package: {
      ...appliedVersion(hash).package,
      owner_assertions: [RULE],
    },
    approach: "Keep the dashboard, move the main action to the top bar",
    changes: ["The main button is now in the top bar"],
    warnings: [{ code: "LIST_TOO_SHORT", screen_code: "SCR-002", detail: "1 item" }],
    cost_microusd: 458000,
  };
}

function job(
  status: GenerationJobPayload["status"],
  overrides: Partial<GenerationJobPayload> = {},
): GenerationJobPayload {
  return {
    job_id: "iteration-job-1",
    kind: "ITERATION",
    status,
    stage: status === "RUNNING" ? "GENERATING" : null,
    attempt: 1,
    started_at: "2026-09-29T09:20:00+00:00",
    finished_at: status === "RUNNING" ? null : "2026-09-29T09:24:00+00:00",
    alternative_id: SELECTED,
    result: null,
    failure: null,
    ...overrides,
  };
}

const LISTED: DesignIterationPayload = {
  generation_id: "iteration-1",
  requested_at: "2026-09-29T09:20:00+00:00",
  request: REQUEST,
  assertions: [RULE],
  changes: ["The main button is now in the top bar"],
  status: "PROPOSED",
  base_design_version_number: 2,
  applied_design_version_number: null,
  cost_microusd: 458000,
};

function apiError(status: number, code: string | null): DesignIterationsApiError {
  return new DesignIterationsApiError(code ?? `failed with ${status}`, {
    status,
    code,
    payload: code === null ? null : { detail: { code } },
  });
}

function fakeApi() {
  return {
    startJob: vi.fn<DesignIterationsApi["startJob"]>(async () => job("RUNNING")),
    job: vi.fn<DesignIterationsApi["job"]>(async (_project, jobId) =>
      job("RUNNING", { job_id: jobId }),
    ),
    list: vi.fn<DesignIterationsApi["list"]>(async () => ({ items: [LISTED] })),
  };
}

function fakeMockupsApi() {
  return {
    capabilities: vi.fn<DesignMockupsApi["capabilities"]>(async () => ({
      generated_mockups: true,
      iterations: true,
      model: "claude-opus-5-5",
    })),
    startJob: vi.fn<DesignMockupsApi["startJob"]>(),
    job: vi.fn<DesignMockupsApi["job"]>(),
    latest: vi.fn<DesignMockupsApi["latest"]>(async () => null),
    document: vi.fn<DesignMockupsApi["document"]>(),
  };
}

function activeStore(version: DesignPackageVersionPayload = appliedVersion(HASH_TWO)) {
  const store = useDesignIterationsStore();
  store.activate(PROJECT, version);
  return store;
}

async function tick(times = 1): Promise<void> {
  await vi.advanceTimersByTimeAsync(POLL_INTERVAL_MILLISECONDS * times);
}

describe("design iterations store", () => {
  beforeEach(() => {
    sessionStorage.clear();
    vi.useFakeTimers({ now: new Date("2026-09-29T09:20:05Z") });
    setActivePinia(createPinia());
  });

  afterEach(() => {
    vi.useRealTimers();
    sessionStorage.clear();
  });

  it("starts an iteration on the applied design, polls it and keeps the proposed result", async () => {
    const api = fakeApi();
    api.job
      .mockResolvedValueOnce(job("RUNNING", { stage: "RETRYING", attempt: 2 }))
      .mockResolvedValueOnce(job("SUCCEEDED", { result: proposal() }));
    const store = activeStore();

    const outcome = await store.start(
      { request: `  ${REQUEST} `, assertions: [RULE, " ", `${RULE} `] },
      authorize,
      { api },
    );

    expect(outcome).toBe("started");
    expect(api.startJob).toHaveBeenCalledWith(
      PROJECT,
      {
        design_version_id: versionId(HASH_TWO),
        design_content_hash: HASH_TWO,
        request: REQUEST,
        assertions: [RULE],
      },
      "token",
    );
    expect(store.state).toBe("drawing");
    expect(store.startedAt).toBe("2026-09-29T09:20:00+00:00");
    expect(store.request).toEqual({ request: REQUEST, assertions: [RULE] });
    expect(store.isBusy).toBe(true);

    await tick();
    expect(store.job).toMatchObject({ stage: "RETRYING", attempt: 2 });
    await tick();

    expect(store.state).toBe("ready");
    expect(store.result).toEqual(proposal());
    expect(store.isApplicable).toBe(true);
    expect(api.list).toHaveBeenCalledTimes(1);
    expect(store.items).toEqual([LISTED]);
    await tick(3);
    expect(api.job).toHaveBeenCalledTimes(2);
  });

  it("sends a request only once, even when it is asked twice at the same time", async () => {
    const api = fakeApi();
    const store = activeStore();

    const outcomes = await Promise.all([
      store.start({ request: REQUEST }, authorize, { api }),
      store.start({ request: REQUEST }, authorize, { api }),
    ]);

    expect(outcomes).toEqual(["started", "started"]);
    expect(await store.start({ request: "Another change" }, authorize, { api })).toBe("running");
    expect(api.startJob).toHaveBeenCalledTimes(1);
  });

  it("keeps a proposal until the person replaces it on purpose", async () => {
    const api = fakeApi();
    api.job.mockResolvedValue(job("SUCCEEDED", { result: proposal() }));
    const store = activeStore();
    await store.start({ request: REQUEST }, authorize, { api });
    await tick();

    expect(await store.start({ request: "Another change" }, authorize, { api })).toBe("pending");
    expect(await store.retry(authorize, { api })).toBe("pending");
    expect(api.startJob).toHaveBeenCalledTimes(1);

    api.job.mockResolvedValue(job("RUNNING"));
    expect(
      await store.start({ request: "Another change" }, authorize, { api, replace: true }),
    ).toBe("started");
    expect(api.startJob).toHaveBeenCalledTimes(2);
    expect(store.result).toBeNull();
  });

  it.each([
    ["an empty request", { request: "   " }],
    ["a request that is too long", { request: "x".repeat(1001) }],
    ["six rules", { request: REQUEST, assertions: ["a", "b", "c", "d", "e", "f"] }],
    ["a rule that is too long", { request: REQUEST, assertions: ["r".repeat(301)] }],
  ])("refuses %s without calling the server", async (_label, input) => {
    const api = fakeApi();
    const store = activeStore();

    expect(await store.start(input, authorize, { api })).toBe("invalid");
    expect(api.startJob).not.toHaveBeenCalled();
    expect(store.state).toBe("idle");
  });

  it("counts characters as the server does", () => {
    expect(normalizedIterationRequest({ request: "😀".repeat(1000) })).not.toBeNull();
    expect(normalizedIterationRequest({ request: "😀".repeat(1001) })).toBeNull();
    expect(
      normalizedIterationRequest({ request: "ok", assertions: ["a", "b", "c", "d", "e", "e"] }),
    ).toEqual({ request: "ok", assertions: ["a", "b", "c", "d", "e"] });
  });

  it("asks nothing when the design has no applied generated mockup or no project", async () => {
    const api = fakeApi();
    const store = activeStore(appliedVersion(HASH_TWO, false));

    expect(await store.start({ request: REQUEST }, authorize, { api })).toBe("unavailable");
    store.activate(PROJECT, null);
    expect(await store.start({ request: REQUEST }, authorize, { api })).toBe("inactive");
    expect(await store.retry(authorize, { api })).toBe("inactive");
    expect(api.startJob).not.toHaveBeenCalled();
  });

  it.each([
    [409, DESIGN_CONTEXT_CHANGED],
    [409, "GENERATED_MOCKUP_REQUIRED"],
    [422, "ITERATION_REQUEST_INVALID"],
    [429, "TOO_MANY_GENERATIONS"],
    [402, "GENERATION_BUDGET_EXCEEDED"],
    [503, "GENERATION_BUDGET_UNAVAILABLE"],
    [503, "REAL_MOCKUP_MODEL_NOT_CONFIGURED"],
  ])("keeps the request when the Studio refuses it with %i %s", async (status, code) => {
    const api = fakeApi();
    api.startJob.mockRejectedValueOnce(apiError(status, code));
    const store = activeStore();

    expect(await store.start({ request: REQUEST, assertions: [RULE] }, authorize, { api })).toBe(
      "refused",
    );
    expect(store.state).toBe("failed");
    expect(store.failure).toEqual({ code, reasons: [] });
    expect(store.request).toEqual({ request: REQUEST, assertions: [RULE] });
    expect(store.job).toBeNull();

    expect(await store.retry(authorize, { api })).toBe("started");
    expect(api.startJob).toHaveBeenCalledTimes(2);
    expect(api.startJob.mock.calls[1]?.[1]).toMatchObject({ request: REQUEST, assertions: [RULE] });
  });

  it.each([
    ["REJECTED", "MOCKUP_QUALITY_REJECTED", "rejected"],
    ["FAILED", "GENERATION_BUDGET_EXCEEDED", "failed"],
    ["FAILED", "GENERATION_BUDGET_UNAVAILABLE", "failed"],
  ] as const)("shows a %s job with %s and its reasons", async (status, code, state) => {
    const api = fakeApi();
    const reasons = [{ code: "LOW_CONTRAST", screen_code: "SCR-001", detail: ".badge 2.10" }];
    api.job.mockResolvedValue(job(status, { failure: { code, reasons } }));
    const store = activeStore();
    await store.start({ request: REQUEST }, authorize, { api });

    await tick();

    expect(store.state).toBe(state);
    expect(store.failure).toEqual({ code, reasons });
    expect(store.result).toBeNull();
    expect(api.list).toHaveBeenCalledTimes(1);
  });

  it("checks the known job before sending the request again", async () => {
    const api = fakeApi();
    const store = activeStore();
    await store.start({ request: REQUEST }, authorize, { api });
    await vi.advanceTimersByTimeAsync(POLL_LIMIT_MILLISECONDS + POLL_INTERVAL_MILLISECONDS);
    expect(store.failure?.code).toBe(GENERATION_POLL_TIMEOUT);

    expect(await store.retry(authorize, { api })).toBe("running");
    expect(api.startJob).toHaveBeenCalledTimes(1);

    api.job.mockResolvedValue(job("SUCCEEDED", { result: proposal() }));
    await tick();
    expect(store.state).toBe("ready");
  });

  it("recovers a result that succeeded while polling had stopped", async () => {
    const api = fakeApi();
    const store = activeStore();
    await store.start({ request: REQUEST }, authorize, { api });
    await vi.advanceTimersByTimeAsync(POLL_LIMIT_MILLISECONDS + POLL_INTERVAL_MILLISECONDS);
    api.job.mockResolvedValue(job("SUCCEEDED", { result: proposal() }));

    expect(await store.retry(authorize, { api })).toBe("ready");
    expect(api.startJob).toHaveBeenCalledTimes(1);
  });

  it("sends the same request again after a failure when the person asks", async () => {
    const api = fakeApi();
    api.job.mockResolvedValue(job("FAILED", { failure: { code: "TIMEOUT", reasons: [] } }));
    const store = activeStore();
    await store.start({ request: REQUEST, assertions: [RULE] }, authorize, { api });
    await tick();

    expect(await store.retry(authorize, { api })).toBe("started");
    expect(api.startJob).toHaveBeenCalledTimes(2);
    expect(store.state).toBe("drawing");
  });

  it("does not propose a result made for a design that changed meanwhile", async () => {
    const api = fakeApi();
    const store = activeStore();
    await store.start({ request: REQUEST }, authorize, { api });
    store.activate(PROJECT, appliedVersion(HASH_THREE));
    api.job.mockResolvedValue(job("SUCCEEDED", { result: proposal(HASH_TWO) }));

    await tick();

    expect(store.state).toBe("failed");
    expect(store.failure?.code).toBe(DESIGN_CONTEXT_CHANGED);
    expect(store.result).toBeNull();
    expect(store.isApplicable).toBe(false);

    api.job.mockResolvedValue(job("SUCCEEDED", { result: proposal(HASH_TWO) }));
    expect(await store.retry(authorize, { api })).toBe("started");
    expect(api.startJob.mock.calls[1]?.[1]).toMatchObject({ design_content_hash: HASH_THREE });
  });

  it("drops the proposal once it is applied or the design moves on", async () => {
    const api = fakeApi();
    api.job.mockResolvedValue(job("SUCCEEDED", { result: proposal() }));
    const store = activeStore();
    await store.start({ request: REQUEST }, authorize, { api });
    await tick();
    expect(store.state).toBe("ready");

    store.activate(PROJECT, appliedVersion(HASH_THREE));

    expect(store.state).toBe("idle");
    expect(store.result).toBeNull();
    expect(store.request).toBeNull();
  });

  it("settles an applied proposal and discards an unwanted one", async () => {
    const api = fakeApi();
    api.job.mockResolvedValue(job("SUCCEEDED", { result: proposal() }));
    const store = activeStore();
    await store.start({ request: REQUEST }, authorize, { api });
    await tick();

    store.settleApplied();
    expect(store.state).toBe("idle");
    expect(store.result).toBeNull();

    await store.start({ request: REQUEST }, authorize, { api });
    await tick();
    store.discard();
    expect(store.state).toBe("idle");
    expect(store.result).toBeNull();
  });

  it("does not discard a job that is still drawing", async () => {
    const api = fakeApi();
    const store = activeStore();
    await store.start({ request: REQUEST }, authorize, { api });

    store.discard();

    expect(store.state).toBe("drawing");
    await tick();
    expect(api.job).toHaveBeenCalledTimes(1);
  });

  it("resumes the running iteration after a reload without sending it again", async () => {
    await activeStore().start({ request: REQUEST, assertions: [RULE] }, authorize, {
      api: fakeApi(),
    });

    setActivePinia(createPinia());
    const api = fakeApi();
    api.job
      .mockResolvedValueOnce(job("RUNNING"))
      .mockResolvedValueOnce(job("SUCCEEDED", { result: proposal() }));
    const store = activeStore();

    expect(await store.recover(authorize, { api, mockupsApi: fakeMockupsApi() })).toBe("running");
    expect(store.request).toEqual({ request: REQUEST, assertions: [RULE] });
    expect(store.state).toBe("drawing");
    await tick();
    expect(store.state).toBe("ready");
    expect(api.startJob).not.toHaveBeenCalled();
  });

  it("recovers the proposal after a reload when the job is gone", async () => {
    await activeStore().start({ request: REQUEST }, authorize, { api: fakeApi() });

    setActivePinia(createPinia());
    const api = fakeApi();
    api.job.mockRejectedValue(apiError(404, GENERATION_JOB_NOT_FOUND));
    const mockupsApi = fakeMockupsApi();
    mockupsApi.latest.mockResolvedValue(proposal());
    const store = activeStore();

    expect(await store.recover(authorize, { api, mockupsApi })).toBe("ready");
    expect(mockupsApi.latest).toHaveBeenCalledWith(PROJECT, SELECTED, "token");
    expect(store.result).toEqual(proposal());
    expect(api.startJob).not.toHaveBeenCalled();
  });

  it("does not bring back a discarded proposal, a first mockup or a stale one", async () => {
    const api = fakeApi();
    api.job.mockResolvedValue(job("SUCCEEDED", { result: proposal() }));
    const first = activeStore();
    await first.start({ request: REQUEST }, authorize, { api });
    await tick();
    first.discard();

    setActivePinia(createPinia());
    const mockupsApi = fakeMockupsApi();
    mockupsApi.latest
      .mockResolvedValueOnce(proposal())
      .mockResolvedValueOnce({ ...proposal(HASH_TWO, "first-mockup"), changes: [] })
      .mockResolvedValueOnce(proposal(HASH_THREE, "stale"));
    const store = activeStore();

    expect(await store.recover(authorize, { api, mockupsApi })).toBe("inactive");
    expect(await store.recover(authorize, { api, mockupsApi })).toBe("inactive");
    expect(await store.recover(authorize, { api, mockupsApi })).toBe("inactive");
    expect(store.state).toBe("idle");
  });

  it("shows a remembered failure after a reload and keeps its request for a retry", async () => {
    await activeStore().start({ request: REQUEST }, authorize, { api: fakeApi() });

    setActivePinia(createPinia());
    const api = fakeApi();
    api.job.mockResolvedValue(
      job("REJECTED", { failure: { code: "UNSAFE_MOCKUP_OUTPUT", reasons: [] } }),
    );
    const store = activeStore();

    expect(await store.recover(authorize, { api, mockupsApi: fakeMockupsApi() })).toBe("failed");
    expect(store.state).toBe("rejected");
    expect(store.request?.request).toBe(REQUEST);
  });

  it("does not guess when the remembered job cannot be read", async () => {
    await activeStore().start({ request: REQUEST }, authorize, { api: fakeApi() });

    setActivePinia(createPinia());
    const api = fakeApi();
    api.job.mockRejectedValue(apiError(502, null));
    const store = activeStore();

    expect(await store.recover(authorize, { api, mockupsApi: fakeMockupsApi() })).toBe("failed");
    expect(store.state).toBe("failed");
    expect(api.startJob).not.toHaveBeenCalled();
  });

  it("marks a job that the Studio forgot while polling", async () => {
    const api = fakeApi();
    api.job.mockRejectedValue(apiError(404, GENERATION_JOB_NOT_FOUND));
    const store = activeStore();
    await store.start({ request: REQUEST }, authorize, { api, mockupsApi: fakeMockupsApi() });

    await tick();

    expect(store.state).toBe("failed");
    expect(store.failure?.code).toBe(GENERATION_JOB_NOT_FOUND);
  });

  it("keeps polling through transient errors and stops on a lasting one", async () => {
    const api = fakeApi();
    api.job
      .mockRejectedValueOnce(new TypeError("Failed to fetch"))
      .mockRejectedValueOnce(apiError(401, "invalid_authentication"));
    const store = activeStore();
    await store.start({ request: REQUEST }, authorize, { api });

    await tick();
    expect(store.state).toBe("drawing");
    await tick();
    expect(store.state).toBe("failed");
    expect(store.failure?.code).toBe("invalid_authentication");
    await tick(3);
    expect(api.job).toHaveBeenCalledTimes(2);
  });

  it("stops polling when the component that asked for it is gone", async () => {
    const api = fakeApi();
    const store = activeStore();
    const panel = new AbortController();
    await store.start({ request: REQUEST }, authorize, { api, signal: panel.signal });

    await tick();
    panel.abort();
    await tick(4);
    expect(api.job).toHaveBeenCalledTimes(1);

    const next = new AbortController();
    expect(await store.recover(authorize, { api, signal: next.signal })).toBe("running");
    await tick();
    expect(api.job).toHaveBeenCalledTimes(2);
    next.abort();
  });

  it("lists the iterations and reports when the list cannot be read", async () => {
    const api = fakeApi();
    const store = activeStore();

    expect(await store.loadList(authorize, { api })).toEqual([LISTED]);
    expect(store.loaded).toBe(true);
    expect(store.listing).toBe(false);

    api.list.mockRejectedValueOnce(apiError(503, null));
    await expect(store.loadList(authorize, { api })).rejects.toBeInstanceOf(
      DesignIterationsApiError,
    );
    expect(store.listError).toBe("DESIGN_ITERATIONS_UNAVAILABLE");
    expect(store.items).toEqual([LISTED]);
  });

  it("ignores late answers after the project changes", async () => {
    const api = fakeApi();
    let answer: (value: GenerationJobPayload) => void = () => undefined;
    api.startJob.mockImplementationOnce(
      () =>
        new Promise<GenerationJobPayload>((resolve) => {
          answer = resolve;
        }),
    );
    const store = activeStore();
    const pending = store.start({ request: REQUEST }, authorize, { api });
    await vi.advanceTimersByTimeAsync(0);

    store.activate(OTHER_PROJECT, null);
    answer(job("RUNNING"));

    expect(await pending).toBe("inactive");
    expect(store.state).toBe("idle");
    expect(store.starting).toBe(false);
    await tick(2);
    expect(api.job).not.toHaveBeenCalled();
    expect(await useDesignIterationsStore().loadList(authorize, { api })).toEqual([LISTED]);
    store.reset();
    expect(store.projectId).toBeNull();
    expect(await store.loadList(authorize, { api })).toEqual([]);
  });
});
