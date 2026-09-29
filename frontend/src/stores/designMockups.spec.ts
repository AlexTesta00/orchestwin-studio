import { createPinia, setActivePinia } from "pinia";
import { effectScope } from "vue";

import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import {
  BASE_DESIGN_PACKAGE,
  DESIGN_ALTERNATIVE_ID,
  DESIGN_PROJECT_ID,
  SECOND_DESIGN_ALTERNATIVE_ID,
  UNSELECTED_DESIGN_VERSION,
} from "@/test/designFixtures";

import { DesignMockupsApiError, type DesignMockupsApi } from "../api/designMockups";
import type { DesignReviewPinsApi } from "../api/designReviewPins";
import type { DesignPackagePayload, DesignPackageVersionPayload } from "../types/design";
import type {
  BoundGeneratedMockupPayload,
  GenerationJobPayload,
  MockupDocumentPayload,
  MockupResultPayload,
  ReviewPinsPayload,
} from "../types/designMockups";
import {
  GENERATION_JOB_NOT_FOUND,
  GENERATION_POLL_TIMEOUT,
  MOCKUP_STATUS_UNAVAILABLE,
  POLL_INTERVAL_MILLISECONDS,
  POLL_LIMIT_MILLISECONDS,
  generationFailureMessage,
  generationReasonMessages,
  useDesignMockupsStore,
  type AuthorizedMockupRequest,
} from "./designMockups";

const PROJECT = DESIGN_PROJECT_ID;
const OTHER_PROJECT = "00000000-0000-4000-8000-000000000999";
const FIRST = DESIGN_ALTERNATIVE_ID;
const SECOND = SECOND_DESIGN_ALTERNATIVE_ID;
const HASH_ONE = "1".repeat(64);
const HASH_TWO = "2".repeat(64);
const STARTED_AT = "2026-09-29T09:12:03+00:00";

const authorize: AuthorizedMockupRequest = (operation) => operation("token");

function versionId(hash: string): string {
  return `00000000-0000-4000-8000-${hash.slice(0, 12)}`;
}

function generatedMockup(alternativeId: string): BoundGeneratedMockupPayload {
  return {
    mockup: {
      contract_version: 1,
      design_alternative_id: alternativeId,
      title: "Reservation desk",
      styles: ".desk{display:grid}",
      screens: [{ code: "SCR-001", title: "Desk", state: "DEFAULT", markup: "<h1>Desk</h1>" }],
    },
    requirement_ids_by_code: {},
  };
}

function version(
  hash: string,
  overrides: Partial<DesignPackagePayload> = {},
): DesignPackageVersionPayload {
  return {
    ...UNSELECTED_DESIGN_VERSION,
    id: versionId(hash),
    content_hash: hash,
    package: { ...BASE_DESIGN_PACKAGE, ...overrides },
  };
}

function appliedVersion(hash: string, alternativeId: string): DesignPackageVersionPayload {
  return version(hash, {
    owner_selected_alternative_id: alternativeId,
    generated_mockup: generatedMockup(alternativeId),
  });
}

function regeneratedVersion(hash: string, alternativeIds: string[]): DesignPackageVersionPayload {
  const [template] = BASE_DESIGN_PACKAGE.alternatives;

  return version(hash, {
    alternatives: alternativeIds.map((id, index) => ({
      ...template!,
      id,
      code: `DES-00${index + 1}`,
    })),
  });
}

function result(
  alternativeId: string,
  hash: string,
  generationId = `generation-${alternativeId.slice(-3)}-${hash.slice(0, 1)}`,
  generated = true,
): MockupResultPayload {
  return {
    status: "MOCKUP_GENERATED",
    generation_id: generationId,
    design_version_id: versionId(hash),
    design_content_hash: hash,
    package: {
      ...BASE_DESIGN_PACKAGE,
      owner_selected_alternative_id: alternativeId,
      generated_mockup: generated ? generatedMockup(alternativeId) : null,
    },
    approach: generated ? "Dashboard with the loans first" : null,
    changes: [],
    warnings: [],
    cost_microusd: generated ? 412000 : null,
  };
}

function job(
  status: GenerationJobPayload["status"],
  overrides: Partial<GenerationJobPayload> = {},
): GenerationJobPayload {
  return {
    job_id: `job-${FIRST}`,
    kind: "MOCKUP",
    status,
    stage: status === "RUNNING" ? "GENERATING" : null,
    attempt: 1,
    started_at: STARTED_AT,
    finished_at: status === "RUNNING" ? null : "2026-09-29T09:15:03+00:00",
    alternative_id: FIRST,
    result: null,
    failure: null,
    ...overrides,
  };
}

function document(entryScreen = "SCR-001", contentHash = "c".repeat(64)): MockupDocumentPayload {
  return {
    html: `<!doctype html><title>${entryScreen}</title>`,
    content_hash: contentHash,
    source: "latest",
    alternative_id: FIRST,
    title: "Reservation desk",
    entry_screen: entryScreen,
    screens: [
      { code: "SCR-001", title: "Desk", state: "DEFAULT" },
      { code: "SCR-002", title: "Loans", state: "DEFAULT" },
    ],
  };
}

function apiError(status: number, code: string | null): DesignMockupsApiError {
  return new DesignMockupsApiError(code ?? `failed with ${status}`, {
    status,
    code,
    payload: code === null ? null : { detail: { code } },
  });
}

function fakeApi() {
  return {
    capabilities: vi.fn<DesignMockupsApi["capabilities"]>(async () => ({
      generated_mockups: true,
      iterations: true,
      model: "claude-opus-5-5",
    })),
    startJob: vi.fn<DesignMockupsApi["startJob"]>(async (_project, request) =>
      job("RUNNING", {
        job_id: `job-${request.alternative_id}`,
        alternative_id: request.alternative_id,
      }),
    ),
    job: vi.fn<DesignMockupsApi["job"]>(async (_project, jobId) =>
      job("RUNNING", { job_id: jobId }),
    ),
    latest: vi.fn<DesignMockupsApi["latest"]>(async () => null),
    document: vi.fn<DesignMockupsApi["document"]>(async () => {
      throw apiError(404, "GENERATED_MOCKUP_NOT_FOUND");
    }),
  };
}

function activeStore(target: DesignPackageVersionPayload = version(HASH_ONE)) {
  const store = useDesignMockupsStore();
  store.activate(PROJECT, target);
  return store;
}

async function tick(times = 1): Promise<void> {
  await vi.advanceTimersByTimeAsync(POLL_INTERVAL_MILLISECONDS * times);
}

function reload(): void {
  setActivePinia(createPinia());
}

describe("design mockups store", () => {
  beforeEach(() => {
    sessionStorage.clear();
    vi.useFakeTimers({ now: new Date("2026-09-29T09:12:10Z") });
    setActivePinia(createPinia());
  });

  afterEach(() => {
    vi.useRealTimers();
    sessionStorage.clear();
  });

  it("starts one job for an alternative without a mockup and polls it until it is ready", async () => {
    const api = fakeApi();
    const store = activeStore();
    const ready = result(FIRST, HASH_ONE);
    api.job
      .mockResolvedValueOnce(job("RUNNING", { stage: "VALIDATING" }))
      .mockResolvedValueOnce(job("SUCCEEDED", { result: ready }));

    const outcome = await store.ensure(FIRST, authorize, { api, draw: true });

    expect(outcome).toBe("started");
    expect(api.latest).toHaveBeenCalledWith(PROJECT, FIRST, "token");
    expect(api.document).toHaveBeenCalledWith(
      PROJECT,
      { alternative_id: FIRST, source: "latest" },
      "token",
    );
    expect(api.startJob).toHaveBeenCalledTimes(1);
    expect(api.startJob).toHaveBeenCalledWith(
      PROJECT,
      {
        design_version_id: versionId(HASH_ONE),
        design_content_hash: HASH_ONE,
        alternative_id: FIRST,
      },
      "token",
    );
    expect(store.entry(FIRST)).toMatchObject({ state: "drawing", startedAt: STARTED_AT });
    expect(store.isDrawing).toBe(true);

    await tick();
    expect(api.job).toHaveBeenCalledTimes(1);
    expect(store.entry(FIRST)).toMatchObject({ state: "drawing", job: { stage: "VALIDATING" } });

    await tick();
    expect(store.entry(FIRST)).toEqual({ state: "ready", result: ready });
    expect(store.applicableResult(FIRST)).toEqual(ready);
    expect(store.drawnBefore(FIRST)).toBe(true);

    await tick(5);
    expect(api.job).toHaveBeenCalledTimes(2);
    expect(api.startJob).toHaveBeenCalledTimes(1);
  });

  it("starts a single job when two components ask for the same mockup at once", async () => {
    const api = fakeApi();
    const store = activeStore();

    const outcomes = await Promise.all([
      store.ensure(FIRST, authorize, { api, draw: true }),
      store.ensure(FIRST, authorize, { api, draw: true }),
      store.ensure(SECOND, authorize, { api, draw: true }),
    ]);

    expect(outcomes).toEqual(["started", "started", "started"]);
    expect(api.capabilities).toHaveBeenCalledTimes(1);
    expect(api.startJob).toHaveBeenCalledTimes(2);
    expect(api.startJob.mock.calls.map((call) => call[1].alternative_id)).toEqual([FIRST, SECOND]);
    expect(await store.ensure(FIRST, authorize, { api })).toBe("running");
    expect(api.startJob).toHaveBeenCalledTimes(2);
  });

  it("does not draw an alternative that already has an accepted mockup", async () => {
    const api = fakeApi();
    const accepted = result(FIRST, HASH_ONE);
    api.latest.mockResolvedValue(accepted);
    const store = activeStore();

    expect(await store.ensure(FIRST, authorize, { api })).toBe("ready");
    expect(await store.ensure(FIRST, authorize, { api })).toBe("ready");

    expect(store.entry(FIRST)).toEqual({ state: "ready", result: accepted });
    expect(api.latest).toHaveBeenCalledTimes(1);
    expect(api.startJob).not.toHaveBeenCalled();
  });

  it("follows a job that is already running on the server instead of starting another", async () => {
    const api = fakeApi();
    const running = job("RUNNING", { started_at: "2026-09-29T09:02:00+00:00", attempt: 2 });
    api.startJob.mockResolvedValue(running);
    const store = activeStore();

    expect(await store.ensure(FIRST, authorize, { api, draw: true })).toBe("started");
    expect(store.entry(FIRST)).toMatchObject({
      state: "drawing",
      startedAt: "2026-09-29T09:02:00+00:00",
    });
    expect(await store.ensure(FIRST, authorize, { api })).toBe("running");
    expect(api.startJob).toHaveBeenCalledTimes(1);
  });

  it("resumes the running job after a reload without starting a new one", async () => {
    const first = fakeApi();
    await activeStore().ensure(FIRST, authorize, { api: first, draw: true });
    expect(first.startJob).toHaveBeenCalledTimes(1);

    reload();
    const api = fakeApi();
    api.job
      .mockResolvedValueOnce(job("RUNNING"))
      .mockResolvedValueOnce(job("SUCCEEDED", { result: result(FIRST, HASH_ONE) }));
    const store = activeStore();

    expect(await store.ensure(FIRST, authorize, { api })).toBe("running");
    expect(api.job).toHaveBeenCalledWith(PROJECT, `job-${FIRST}`, "token");
    expect(store.entry(FIRST).state).toBe("drawing");

    await tick();
    expect(store.entry(FIRST).state).toBe("ready");
    expect(api.startJob).not.toHaveBeenCalled();
  });

  it("shows again, after a reload, why the last job failed and does not retry by itself", async () => {
    const first = fakeApi();
    await activeStore().ensure(FIRST, authorize, { api: first, draw: true });

    reload();
    const api = fakeApi();
    api.job.mockResolvedValue(
      job("REJECTED", {
        failure: {
          code: "MOCKUP_QUALITY_REJECTED",
          reasons: [{ code: "TABLE_TOO_SHORT", screen_code: "SCR-002", detail: "2 rows" }],
        },
      }),
    );
    const store = activeStore();

    expect(await store.ensure(FIRST, authorize, { api })).toBe("attempted");
    expect(store.entry(FIRST)).toMatchObject({
      state: "rejected",
      code: "MOCKUP_QUALITY_REJECTED",
      reasons: [{ code: "TABLE_TOO_SHORT" }],
    });
    expect(api.startJob).not.toHaveBeenCalled();
  });

  it("recovers an accepted mockup after a reload and does not start the job again", async () => {
    const first = fakeApi();
    await activeStore().ensure(FIRST, authorize, { api: first, draw: true });

    reload();
    const api = fakeApi();
    api.job.mockRejectedValue(apiError(404, GENERATION_JOB_NOT_FOUND));
    api.latest.mockResolvedValue(result(FIRST, HASH_ONE));
    const store = activeStore();

    expect(await store.ensure(FIRST, authorize, { api })).toBe("ready");
    expect(store.entry(FIRST).state).toBe("ready");
    expect(api.startJob).not.toHaveBeenCalled();
  });

  it("does not draw again after a reload when the job is lost and nothing was accepted", async () => {
    const first = fakeApi();
    await activeStore().ensure(FIRST, authorize, { api: first, draw: true });

    reload();
    const api = fakeApi();
    api.job.mockRejectedValue(apiError(404, GENERATION_JOB_NOT_FOUND));
    const store = activeStore();

    expect(await store.ensure(FIRST, authorize, { api })).toBe("earlier");
    expect(store.entry(FIRST).state).toBe("idle");
    expect(store.drawnBefore(FIRST)).toBe(true);
    expect(api.startJob).not.toHaveBeenCalled();
  });

  it("keeps a failed job failed until the person asks to retry", async () => {
    const api = fakeApi();
    api.job.mockResolvedValue(
      job("FAILED", { failure: { code: "PROVIDER_UNAVAILABLE", reasons: [] } }),
    );
    const store = activeStore();

    await store.ensure(FIRST, authorize, { api, draw: true });
    await tick();
    expect(store.entry(FIRST)).toMatchObject({ state: "failed", code: "PROVIDER_UNAVAILABLE" });

    expect(await store.ensure(FIRST, authorize, { api, draw: true })).toBe("attempted");
    expect(api.startJob).toHaveBeenCalledTimes(1);

    api.job.mockResolvedValue(
      job("FAILED", { failure: { code: "PROVIDER_UNAVAILABLE", reasons: [] } }),
    );
    expect(await store.retry(FIRST, authorize, { api })).toBe("started");
    expect(api.startJob).toHaveBeenCalledTimes(2);
    expect(store.entry(FIRST).state).toBe("drawing");
  });

  it("does not start a new job on retry when the known job is still running or succeeded", async () => {
    const api = fakeApi();
    const store = activeStore();
    await store.ensure(FIRST, authorize, { api, draw: true });
    await vi.advanceTimersByTimeAsync(POLL_LIMIT_MILLISECONDS + POLL_INTERVAL_MILLISECONDS);
    expect(store.entry(FIRST)).toMatchObject({ state: "failed", code: GENERATION_POLL_TIMEOUT });

    expect(await store.retry(FIRST, authorize, { api })).toBe("running");
    expect(store.entry(FIRST).state).toBe("drawing");

    api.job.mockResolvedValue(job("SUCCEEDED", { result: result(FIRST, HASH_ONE) }));
    await tick();
    expect(store.entry(FIRST).state).toBe("ready");
    expect(await store.retry(FIRST, authorize, { api })).toBe("ready");
    expect(api.startJob).toHaveBeenCalledTimes(1);
  });

  it("gives up polling after twenty minutes without spending again", async () => {
    const api = fakeApi();
    const store = activeStore();
    await store.ensure(FIRST, authorize, { api, draw: true });

    await vi.advanceTimersByTimeAsync(POLL_LIMIT_MILLISECONDS - POLL_INTERVAL_MILLISECONDS);
    expect(store.entry(FIRST).state).toBe("drawing");
    const polls = api.job.mock.calls.length;
    expect(polls).toBeGreaterThan(390);

    await tick(2);
    expect(store.entry(FIRST)).toMatchObject({ state: "failed", code: GENERATION_POLL_TIMEOUT });
    await tick(10);
    expect(api.job.mock.calls.length).toBeLessThanOrEqual(polls + 1);
    expect(await store.ensure(FIRST, authorize, { api, draw: true })).toBe("attempted");
    expect(api.startJob).toHaveBeenCalledTimes(1);
  });

  it("keeps polling through a network error or a server error", async () => {
    const api = fakeApi();
    api.job
      .mockRejectedValueOnce(new TypeError("Failed to fetch"))
      .mockRejectedValueOnce(apiError(503, null))
      .mockResolvedValueOnce(job("SUCCEEDED", { result: result(FIRST, HASH_ONE) }));
    const store = activeStore();
    await store.ensure(FIRST, authorize, { api, draw: true });

    await tick(2);
    expect(store.entry(FIRST).state).toBe("drawing");
    await tick();
    expect(store.entry(FIRST).state).toBe("ready");
  });

  it("marks a job that the Studio forgot and never replaces it by itself", async () => {
    const api = fakeApi();
    api.job.mockRejectedValue(apiError(404, GENERATION_JOB_NOT_FOUND));
    const store = activeStore();
    await store.ensure(FIRST, authorize, { api, draw: true });

    await tick();
    expect(store.entry(FIRST)).toMatchObject({ state: "failed", code: GENERATION_JOB_NOT_FOUND });
    expect(await store.ensure(FIRST, authorize, { api, draw: true })).toBe("attempted");
    expect(api.startJob).toHaveBeenCalledTimes(1);
  });

  it("takes the accepted mockup when the Studio forgot a job that had finished", async () => {
    const api = fakeApi();
    api.job.mockRejectedValue(apiError(404, GENERATION_JOB_NOT_FOUND));
    const store = activeStore();
    await store.ensure(FIRST, authorize, { api, draw: true });
    api.latest.mockResolvedValue(result(FIRST, HASH_ONE));

    await tick();
    expect(store.entry(FIRST).state).toBe("ready");
  });

  it("stops a job with a failure that polling cannot fix", async () => {
    const api = fakeApi();
    api.job.mockRejectedValue(apiError(403, "PROJECT_ACCESS_DENIED"));
    const store = activeStore();
    await store.ensure(FIRST, authorize, { api, draw: true });

    await tick();
    expect(store.entry(FIRST)).toMatchObject({ state: "failed", code: "PROJECT_ACCESS_DENIED" });
    await tick(3);
    expect(api.job).toHaveBeenCalledTimes(1);
  });

  it.each([
    [409, "DESIGN_CONTEXT_CHANGED"],
    [422, "DESIGN_ALTERNATIVE_NOT_FOUND"],
    [422, "GENERATED_MOCKUP_REQUIRES_VISUAL_LANGUAGE"],
    [429, "TOO_MANY_GENERATIONS"],
    [402, "GENERATION_BUDGET_EXCEEDED"],
    [503, "GENERATION_BUDGET_UNAVAILABLE"],
    [503, "REAL_MOCKUP_MODEL_NOT_CONFIGURED"],
  ])(
    "shows the refusal %i %s in plain words and never asks again by itself",
    async (status, code) => {
      const api = fakeApi();
      api.startJob.mockRejectedValue(apiError(status, code));
      const store = activeStore();

      expect(await store.ensure(FIRST, authorize, { api, draw: true })).toBe("refused");
      expect(store.entry(FIRST)).toEqual({ state: "failed", code, reasons: [], job: null });
      expect(await store.ensure(FIRST, authorize, { api, draw: true })).toBe("attempted");
      expect(api.startJob).toHaveBeenCalledTimes(1);
      expect(generationFailureMessage(code, "it")).not.toBe(
        generationFailureMessage("SOMETHING_UNKNOWN", "it"),
      );
      expect(generationFailureMessage(code, "en")).not.toBe(
        generationFailureMessage("SOMETHING_UNKNOWN", "en"),
      );
    },
  );

  it.each(["GENERATION_BUDGET_EXCEEDED", "GENERATION_BUDGET_UNAVAILABLE"])(
    "shows %s when it arrives as the failure of a job",
    async (code) => {
      const api = fakeApi();
      api.job.mockResolvedValue(job("FAILED", { failure: { code, reasons: [] } }));
      const store = activeStore();
      await store.ensure(FIRST, authorize, { api, draw: true });

      await tick();

      expect(store.entry(FIRST)).toMatchObject({ state: "failed", code });
      expect(await store.ensure(FIRST, authorize, { api, draw: true })).toBe("attempted");
      expect(api.startJob).toHaveBeenCalledTimes(1);
    },
  );

  it("keeps the code and the reasons of a discarded answer", async () => {
    const api = fakeApi();
    const reasons = [
      { code: "TABLE_TOO_SHORT", screen_code: "SCR-002", detail: "2 body rows" },
      { code: "LOW_CONTRAST", screen_code: "SCR-001", detail: ".badge 2.10" },
      { code: "TABLE_TOO_SHORT", screen_code: "SCR-003", detail: "1 body row" },
    ];
    api.job.mockResolvedValue(
      job("REJECTED", { failure: { code: "MOCKUP_QUALITY_REJECTED", reasons } }),
    );
    const store = activeStore();
    await store.ensure(FIRST, authorize, { api, draw: true });

    await tick();

    const entry = store.entry(FIRST);
    expect(entry).toMatchObject({ state: "rejected", code: "MOCKUP_QUALITY_REJECTED", reasons });
    expect(entry.state === "rejected" && generationReasonMessages(entry.reasons, "it")).toEqual([
      "Una tabella aveva troppo poche righe per sembrare vera.",
      "Un testo non si leggeva bene sul suo sfondo.",
    ]);
  });

  it("keeps drawing the old design when the design changes and does not draw it twice", async () => {
    const api = fakeApi();
    const store = activeStore();
    await store.ensure(FIRST, authorize, { api, draw: true });
    store.activate(PROJECT, version(HASH_TWO));

    api.job.mockResolvedValue(job("SUCCEEDED", { result: result(FIRST, HASH_ONE) }));
    await tick();

    expect(store.entry(FIRST).state).toBe("ready");
    expect(store.applicableResult(FIRST)).toBeNull();
    expect(await store.ensure(FIRST, authorize, { api, draw: true })).toBe("earlier");
    expect(api.startJob).toHaveBeenCalledTimes(1);
  });

  it("starts again on the new design when the old one was refused because it had changed", async () => {
    const api = fakeApi();
    api.startJob.mockRejectedValueOnce(apiError(409, "DESIGN_CONTEXT_CHANGED"));
    const store = activeStore();
    expect(await store.ensure(FIRST, authorize, { api, draw: true })).toBe("refused");

    store.activate(PROJECT, version(HASH_TWO));

    expect(store.entry(FIRST).state).toBe("idle");
    expect(await store.ensure(FIRST, authorize, { api, draw: true })).toBe("started");
    expect(api.startJob).toHaveBeenCalledTimes(2);
    expect(api.startJob.mock.calls[1]?.[1]).toEqual({
      design_version_id: versionId(HASH_TWO),
      design_content_hash: HASH_TWO,
      alternative_id: FIRST,
    });
  });

  it("does not start a job for a design that changed while it was checking", async () => {
    const api = fakeApi();
    let answer: (value: MockupResultPayload | null) => void = () => undefined;
    api.latest.mockImplementationOnce(
      () =>
        new Promise<MockupResultPayload | null>((resolve) => {
          answer = resolve;
        }),
    );
    const store = activeStore();

    const stale = store.ensure(FIRST, authorize, { api, draw: true });
    await vi.advanceTimersByTimeAsync(0);
    store.activate(PROJECT, version(HASH_TWO));
    const fresh = store.ensure(FIRST, authorize, { api, draw: true });
    answer(null);

    expect(await stale).toBe("inactive");
    expect(await fresh).toBe("started");
    expect(api.startJob).toHaveBeenCalledTimes(1);
    expect(api.startJob.mock.calls[0]?.[1].design_content_hash).toBe(HASH_TWO);
  });

  it("forgets alternatives replaced by a regeneration and draws the new ones", async () => {
    const api = fakeApi();
    const store = activeStore();
    await store.ensure(FIRST, authorize, { api, draw: true });
    const renewed = "00000000-0000-4000-8000-000000000201";

    store.activate(PROJECT, regeneratedVersion(HASH_TWO, [renewed]));
    await tick(3);

    expect(store.entries[FIRST]).toBeUndefined();
    expect(api.job).not.toHaveBeenCalled();
    expect(await store.ensure(FIRST, authorize, { api, draw: true })).toBe("inactive");
    expect(await store.ensure(renewed, authorize, { api, draw: true })).toBe("started");
    expect(api.startJob).toHaveBeenCalledTimes(2);
  });

  it("never draws the alternative whose mockup is applied in the current design", async () => {
    const api = fakeApi();
    const store = activeStore(appliedVersion(HASH_TWO, FIRST));

    expect(store.appliedAlternativeId).toBe(FIRST);
    expect(await store.ensure(FIRST, authorize, { api })).toBe("applied");
    expect(await store.retry(FIRST, authorize, { api })).toBe("applied");
    expect(api.latest).not.toHaveBeenCalled();
    expect(api.startJob).not.toHaveBeenCalled();
    expect(store.drawnBefore(FIRST)).toBe(true);
  });

  it("never draws another alternative by itself once a design is applied", async () => {
    const api = fakeApi();
    const store = activeStore(appliedVersion(HASH_TWO, FIRST));

    expect(await store.ensure(SECOND, authorize, { api })).toBe("chosen");
    expect(api.latest).toHaveBeenCalledWith(PROJECT, SECOND, "token");
    expect(api.startJob).not.toHaveBeenCalled();
    expect(store.entry(SECOND).state).toBe("idle");

    expect(await store.retry(SECOND, authorize, { api })).toBe("started");
    expect(api.startJob).toHaveBeenCalledTimes(1);
  });

  it("still follows the job of another alternative that runs when a design is applied", async () => {
    await activeStore(version(HASH_ONE)).ensure(SECOND, authorize, {
      api: fakeApi(),
      draw: true,
    });
    reload();
    const api = fakeApi();
    const store = activeStore(appliedVersion(HASH_TWO, FIRST));

    expect(await store.ensure(SECOND, authorize, { api })).toBe("running");
    expect(store.entry(SECOND).state).toBe("drawing");
    expect(api.startJob).not.toHaveBeenCalled();
  });

  it("does not draw an alternative whose mockup exists for an earlier design", async () => {
    const api = fakeApi();
    api.document.mockResolvedValue(document());
    const store = activeStore(appliedVersion(HASH_TWO, FIRST));

    expect(await store.ensure(SECOND, authorize, { api })).toBe("earlier");

    expect(api.startJob).not.toHaveBeenCalled();
    expect(store.drawnBefore(SECOND)).toBe(true);
    expect(store.documentFor(SECOND)?.content_hash).toBe("c".repeat(64));
  });

  it("draws an earlier alternative for the current design only when the person asks", async () => {
    const api = fakeApi();
    api.document.mockResolvedValue(document());
    const store = activeStore(appliedVersion(HASH_TWO, FIRST));
    await store.ensure(SECOND, authorize, { api });

    expect(await store.retry(SECOND, authorize, { api })).toBe("started");
    expect(api.startJob).toHaveBeenCalledTimes(1);
  });

  it("treats a declarative mockup as accepted and draws a generated one only on request", async () => {
    const api = fakeApi();
    const declarative = result(FIRST, HASH_ONE, "declarative-1", false);
    api.latest.mockResolvedValue(declarative);
    const store = activeStore();

    expect(await store.ensure(FIRST, authorize, { api })).toBe("ready");
    expect(api.startJob).not.toHaveBeenCalled();

    expect(await store.retry(FIRST, authorize, { api })).toBe("started");
    expect(api.startJob).toHaveBeenCalledTimes(1);
  });

  it("does not redraw a generated mockup that is ready for the current design", async () => {
    const api = fakeApi();
    api.latest.mockResolvedValue(result(FIRST, HASH_ONE));
    const store = activeStore();
    await store.ensure(FIRST, authorize, { api });

    expect(await store.retry(FIRST, authorize, { api })).toBe("ready");
    expect(api.startJob).not.toHaveBeenCalled();
  });

  it("does nothing when the capabilities say that mockups are not generated", async () => {
    const api = fakeApi();
    api.capabilities.mockResolvedValue({
      generated_mockups: false,
      iterations: false,
      model: null,
    });
    const store = activeStore();

    expect(await store.ensure(FIRST, authorize, { api })).toBe("unavailable");
    expect(await store.retry(FIRST, authorize, { api })).toBe("unavailable");
    expect(store.generatedMockupsEnabled).toBe(false);
    expect(api.latest).not.toHaveBeenCalled();
    expect(api.startJob).not.toHaveBeenCalled();
  });

  it("does nothing when the capabilities cannot be read", async () => {
    const api = fakeApi();
    api.capabilities.mockRejectedValue(apiError(404, null));
    const store = activeStore();

    expect(await store.ensure(FIRST, authorize, { api })).toBe("unavailable");
    expect(store.capabilities).toBeNull();
    expect(store.capabilitiesError).toBe(MOCKUP_STATUS_UNAVAILABLE);
    expect(api.startJob).not.toHaveBeenCalled();
  });

  it("does nothing without a project or a design", async () => {
    const api = fakeApi();
    const store = useDesignMockupsStore();

    expect(await store.ensure(FIRST, authorize, { api })).toBe("inactive");
    store.activate(PROJECT, null);
    expect(await store.ensure(FIRST, authorize, { api })).toBe("inactive");
    store.activate(PROJECT, version(HASH_ONE));
    expect(await store.ensure("unknown-alternative", authorize, { api })).toBe("inactive");
    expect(api.startJob).not.toHaveBeenCalled();
  });

  it("never starts a job when it cannot check whether one already exists", async () => {
    const api = fakeApi();
    api.latest.mockRejectedValueOnce(apiError(500, null));
    const store = activeStore();

    expect(await store.ensure(FIRST, authorize, { api, draw: true })).toBe("failed");
    expect(store.entry(FIRST)).toMatchObject({ state: "failed", code: MOCKUP_STATUS_UNAVAILABLE });
    expect(api.startJob).not.toHaveBeenCalled();

    api.document.mockRejectedValueOnce(new TypeError("Failed to fetch"));
    expect(await store.ensure(FIRST, authorize, { api, draw: true })).toBe("failed");
    expect(api.startJob).not.toHaveBeenCalled();

    expect(await store.ensure(FIRST, authorize, { api, draw: true })).toBe("started");
    expect(api.startJob).toHaveBeenCalledTimes(1);
  });

  it("does not trust a remembered job that cannot be read", async () => {
    await activeStore().ensure(FIRST, authorize, { api: fakeApi(), draw: true });
    reload();
    const api = fakeApi();
    api.job.mockRejectedValue(apiError(502, null));
    const store = activeStore();

    expect(await store.ensure(FIRST, authorize, { api })).toBe("failed");
    expect(api.startJob).not.toHaveBeenCalled();
  });

  it("stops polling when the component that asked for it is gone", async () => {
    const api = fakeApi();
    const store = activeStore();
    const component = new AbortController();
    await store.ensure(FIRST, authorize, { api, signal: component.signal, draw: true });

    await tick();
    expect(api.job).toHaveBeenCalledTimes(1);
    component.abort();
    await tick(5);
    expect(api.job).toHaveBeenCalledTimes(1);
    expect(store.entry(FIRST).state).toBe("drawing");

    const next = new AbortController();
    expect(await store.ensure(FIRST, authorize, { api, signal: next.signal })).toBe("running");
    await tick();
    expect(api.job).toHaveBeenCalledTimes(2);
    expect(api.startJob).toHaveBeenCalledTimes(1);
    next.abort();
  });

  it("keeps polling while another component still watches the job", async () => {
    const api = fakeApi();
    const store = activeStore();
    const card = new AbortController();
    const dialog = new AbortController();
    await Promise.all([
      store.ensure(FIRST, authorize, { api, signal: card.signal, draw: true }),
      store.ensure(FIRST, authorize, { api, signal: dialog.signal, draw: true }),
    ]);

    card.abort();
    await tick(2);
    expect(api.job).toHaveBeenCalledTimes(2);
    dialog.abort();
    await tick(2);
    expect(api.job).toHaveBeenCalledTimes(2);
  });

  it("binds polling to the scope of the component that asked", async () => {
    const api = fakeApi();
    const store = activeStore();
    const scope = effectScope();

    await scope.run(() => store.ensure(FIRST, authorize, { api, draw: true }));
    await tick();
    expect(api.job).toHaveBeenCalledTimes(1);

    scope.stop();
    await tick(3);
    expect(api.job).toHaveBeenCalledTimes(1);
  });

  it("stops everything and ignores late answers when the project changes", async () => {
    const api = fakeApi();
    let answer: (value: GenerationJobPayload) => void = () => undefined;
    api.startJob.mockImplementationOnce(
      () =>
        new Promise<GenerationJobPayload>((resolve) => {
          answer = resolve;
        }),
    );
    const store = activeStore();
    const pending = store.ensure(FIRST, authorize, { api, draw: true });
    await vi.advanceTimersByTimeAsync(0);

    store.activate(OTHER_PROJECT, null);
    answer(job("RUNNING"));

    expect(await pending).toBe("inactive");
    expect(store.entries).toEqual({});
    await tick(3);
    expect(api.job).not.toHaveBeenCalled();

    store.activate(PROJECT, version(HASH_ONE));
    expect(await store.ensure(FIRST, authorize, { api })).toBe("running");
    expect(api.startJob).toHaveBeenCalledTimes(1);
  });

  it("caches documents by content hash and entry screen", async () => {
    const api = fakeApi();
    api.latest.mockResolvedValue(result(FIRST, HASH_ONE));
    api.document.mockImplementation(async (_project, query) =>
      document(query.entry_screen ?? "SCR-001"),
    );
    const store = activeStore();
    await store.ensure(FIRST, authorize, { api });
    api.document.mockClear();

    const [first, again] = await Promise.all([
      store.loadDocument(FIRST, authorize, { api, entryScreen: "SCR-002" }),
      store.loadDocument(FIRST, authorize, { api, entryScreen: "SCR-002" }),
    ]);
    await store.loadDocument(FIRST, authorize, { api, entryScreen: "SCR-002" });

    expect(first).toBe(again);
    expect(api.document).toHaveBeenCalledTimes(1);
    expect(api.document).toHaveBeenCalledWith(
      PROJECT,
      { alternative_id: FIRST, source: "latest", entry_screen: "SCR-002" },
      "token",
    );
    expect(store.documentFor(FIRST, { entryScreen: "SCR-002" })?.html).toContain("SCR-002");
    expect(Object.keys(store.documents)).toEqual([`${"c".repeat(64)}|SCR-002`]);

    await store.loadDocument(FIRST, authorize, { api });
    await store.loadDocument(FIRST, authorize, { api, source: "applied" });
    await store.loadDocument(FIRST, authorize, { api, entryScreen: "SCR-002", force: true });
    expect(api.document).toHaveBeenCalledTimes(4);
    expect(api.document.mock.calls[2]?.[1]).toEqual({ alternative_id: FIRST, source: "applied" });
    expect(store.documentFor(SECOND)).toBeNull();
  });

  it("asks for the document again when a new mockup replaces the old one", async () => {
    const api = fakeApi();
    api.latest.mockResolvedValue(result(FIRST, HASH_ONE, "generation-old", false));
    api.document.mockResolvedValue(document());
    const store = activeStore();
    await store.ensure(FIRST, authorize, { api });
    await store.loadDocument(FIRST, authorize, { api });
    api.latest.mockResolvedValue(null);

    await store.retry(FIRST, authorize, { api });
    api.job.mockResolvedValue(
      job("SUCCEEDED", { result: result(FIRST, HASH_ONE, "generation-new") }),
    );
    await tick();
    await store.loadDocument(FIRST, authorize, { api });

    expect(api.document).toHaveBeenCalledTimes(2);

    await store.loadDocument(FIRST, authorize, { api, revision: "iteration-1" });
    expect(api.document).toHaveBeenCalledTimes(3);
    expect(store.documentFor(FIRST, { revision: "iteration-1" })).not.toBeNull();
  });

  it("rejects a document request without a project", async () => {
    const store = useDesignMockupsStore();

    await expect(store.loadDocument(FIRST, authorize)).rejects.toThrow();
    await expect(store.loadReviewDocument("run-1", authorize)).rejects.toThrow();
    await expect(store.loadReviewPins("run-1", authorize)).rejects.toThrow();
  });

  it("loads the pins and the document of a review and forgets them after a decision", async () => {
    const pins: ReviewPinsPayload = {
      design_version_id: versionId(HASH_ONE),
      pins: [
        {
          number: 1,
          element_code: "ELM-014",
          screen_code: "SCR-001",
          twin_id: "twin-1",
          finding_id: "UTF-001",
          severity: "major",
          label: "The confirmation is hidden",
        },
      ],
      unanchored: [],
    };
    const reviewApi = {
      pins: vi.fn<DesignReviewPinsApi["pins"]>(async () => pins),
      document: vi.fn<DesignReviewPinsApi["document"]>(async (_project, _run, entry) => ({
        ...document(entry ?? "SCR-001", "d".repeat(64)),
        source: "review" as const,
      })),
    };
    const store = activeStore();

    expect(await store.loadReviewPins("run-1", authorize, { api: reviewApi })).toEqual(pins);
    await store.loadReviewPins("run-1", authorize, { api: reviewApi });
    await store.loadReviewDocument("run-1", authorize, { api: reviewApi, entryScreen: "SCR-002" });
    await store.loadReviewDocument("run-1", authorize, { api: reviewApi, entryScreen: "SCR-002" });
    await store.loadReviewDocument("run-1", authorize, { api: reviewApi });

    expect(reviewApi.pins).toHaveBeenCalledTimes(1);
    expect(reviewApi.document.mock.calls.map((call) => call[2])).toEqual(["SCR-002", null]);
    expect(store.pinsFor("run-1")).toEqual(pins);
    expect(store.reviewDocumentFor("run-1", "SCR-002")?.source).toBe("review");

    store.forgetReview("run-1");
    expect(store.pinsFor("run-1")).toBeNull();
    await store.loadReviewPins("run-1", authorize, { api: reviewApi });
    await store.loadReviewDocument("run-1", authorize, { api: reviewApi, entryScreen: "SCR-002" });
    expect(reviewApi.pins).toHaveBeenCalledTimes(2);
    expect(reviewApi.document).toHaveBeenCalledTimes(3);
  });

  it("clears everything on reset", async () => {
    const api = fakeApi();
    const store = activeStore();
    store.markPrepared(PROJECT, versionId(HASH_ONE), HASH_ONE);
    await store.ensure(FIRST, authorize, { api, draw: true });

    store.reset();
    await tick(3);

    expect(store.projectId).toBeNull();
    expect(store.entries).toEqual({});
    expect(store.wasPrepared(PROJECT, versionId(HASH_ONE), HASH_ONE)).toBe(false);
    expect(api.job).not.toHaveBeenCalled();
  });

  it("starts nothing for an older design without mockups and says that the mockup is missing", async () => {
    const api = fakeApi();
    const store = activeStore();

    expect(await store.ensure(FIRST, authorize, { api })).toBe("missing");
    expect(await store.ensure(SECOND, authorize, { api })).toBe("missing");

    expect(api.latest).toHaveBeenCalledWith(PROJECT, FIRST, "token");
    expect(api.startJob).not.toHaveBeenCalled();
    expect(store.entry(FIRST).state).toBe("idle");
    expect(store.isChecking(FIRST)).toBe(false);
    expect(store.drawnBefore(FIRST)).toBe(false);
    expect(await store.ensure(FIRST, authorize, { api })).toBe("missing");
    expect(api.startJob).not.toHaveBeenCalled();

    expect(await store.retry(FIRST, authorize, { api })).toBe("started");
    expect(api.startJob).toHaveBeenCalledTimes(1);
    expect(api.startJob.mock.calls[0]?.[1].alternative_id).toBe(FIRST);
  });

  it("draws both mockups of a design prepared in this session with one request each", async () => {
    const api = fakeApi();
    const store = activeStore();
    store.markPrepared(PROJECT, versionId(HASH_ONE), HASH_ONE);

    expect(store.wasPrepared(PROJECT, versionId(HASH_ONE), HASH_ONE)).toBe(true);
    expect(store.wasPrepared(PROJECT, versionId(HASH_TWO), HASH_TWO)).toBe(false);
    expect(
      await Promise.all([
        store.ensure(FIRST, authorize, { api, draw: true }),
        store.ensure(SECOND, authorize, { api, draw: true }),
      ]),
    ).toEqual(["started", "started"]);
    expect(
      await Promise.all([
        store.ensure(FIRST, authorize, { api, draw: true }),
        store.ensure(SECOND, authorize, { api, draw: true }),
      ]),
    ).toEqual(["running", "running"]);

    expect(api.startJob).toHaveBeenCalledTimes(2);
    expect(api.startJob.mock.calls.map((call) => call[1].alternative_id)).toEqual([FIRST, SECOND]);

    reload();
    expect(activeStore().wasPrepared(PROJECT, versionId(HASH_ONE), HASH_ONE)).toBe(false);
  });

  it("resumes both drawings after a reload in the middle and starts nothing", async () => {
    const first = fakeApi();
    const before = activeStore();
    await before.ensure(FIRST, authorize, { api: first, draw: true });
    await before.ensure(SECOND, authorize, { api: first, draw: true });
    expect(first.startJob).toHaveBeenCalledTimes(2);

    reload();
    const api = fakeApi();
    const store = activeStore();

    expect(await store.ensure(FIRST, authorize, { api })).toBe("running");
    expect(await store.ensure(SECOND, authorize, { api })).toBe("running");
    expect(api.job.mock.calls.map((call) => call[1])).toEqual([`job-${FIRST}`, `job-${SECOND}`]);
    expect(store.entry(FIRST).state).toBe("drawing");
    expect(store.entry(SECOND).state).toBe("drawing");
    expect(api.startJob).not.toHaveBeenCalled();
  });

  it("waits for a check without drawing before a request that may draw", async () => {
    const api = fakeApi();
    const store = activeStore();

    const outcomes = await Promise.all([
      store.ensure(FIRST, authorize, { api }),
      store.ensure(FIRST, authorize, { api, draw: true }),
      store.ensure(FIRST, authorize, { api }),
    ]);

    expect(outcomes).toEqual(["missing", "started", "started"]);
    expect(api.startJob).toHaveBeenCalledTimes(1);
  });
});

describe("messages of the generations", () => {
  const codes = [
    "MOCKUP_QUALITY_REJECTED",
    "UNSAFE_MOCKUP_OUTPUT",
    "MOCKUP_LANGUAGE_MISMATCH",
    "MOCKUP_SCREEN_COUNT",
    "MOCKUP_COVERAGE_TOO_LOW",
    "GENERATED_MOCKUP_REQUIRES_VISUAL_LANGUAGE",
    "GENERATION_BUDGET_EXCEEDED",
    "GENERATION_BUDGET_UNAVAILABLE",
    "TOO_MANY_GENERATIONS",
    "REAL_MOCKUP_MODEL_NOT_CONFIGURED",
    "DESIGN_CONTEXT_CHANGED",
    "DESIGN_ALTERNATIVE_NOT_FOUND",
    "GENERATION_JOB_NOT_FOUND",
    "GENERATED_MOCKUP_NOT_FOUND",
    "GENERATED_MOCKUP_REQUIRED",
    "ITERATION_REQUEST_INVALID",
    "GENERATION_POLL_TIMEOUT",
    "MOCKUP_STATUS_UNAVAILABLE",
    "PROVIDER_UNAVAILABLE",
    "TIMEOUT",
    "RATE_LIMITED",
    "INCOMPLETE_OUTPUT",
    "PROVIDER_REFUSED",
  ];
  const reasons = [
    "UNREACHABLE_SCREEN",
    "NO_TRANSITION",
    "SELF_LINK",
    "UNKNOWN_REQUIREMENT",
    "UNTRACED_CONTROL",
    "UNTRACED_SCREEN",
    "UNLABELLED_CONTROL",
    "UNNAMED_ACTION",
    "TABLE_WITHOUT_HEADERS",
    "HEADING_COUNT",
    "SCREEN_TOO_EMPTY",
    "TABLE_TOO_SHORT",
    "EMPTY_CELL",
    "SELECT_TOO_SHORT",
    "PLACEHOLDER_TEXT",
    "LOW_CONTRAST",
    "UNREADABLE_TEXT_COLOUR",
    "DATED_BACKGROUND",
    "HEADING_LEVEL_SKIPPED",
    "LIST_TOO_SHORT",
    "EMPTY_CONTAINER",
    "DECORATIVE_ICON_EXPOSED",
    "BACKGROUND_WITHOUT_TEXT_COLOUR",
    "NO_RESPONSIVE_RULE",
    "SINGLE_STATE",
  ];

  it("gives every code of the contract its own sentence in Italian and in English", () => {
    for (const locale of ["it", "en"] as const) {
      const generic = generationFailureMessage("NOT_A_CODE", locale);
      const sentences = codes.map((code) => generationFailureMessage(code, locale));

      expect(sentences.every((sentence) => sentence !== generic)).toBe(true);
      expect(new Set(sentences).size).toBe(sentences.length);
      expect(sentences.every((sentence) => !/[A-Z]{3,}_[A-Z]/.test(sentence))).toBe(true);
    }
  });

  it("uses the sentences chosen by the owner", () => {
    expect(generationFailureMessage("GENERATION_BUDGET_EXCEEDED", "it")).toBe(
      "Il tetto di spesa impostato non basta per questa generazione.",
    );
    expect(generationFailureMessage("UNSAFE_MOCKUP_OUTPUT", "it")).toBe(
      "La risposta conteneva elementi che lo Studio non accetta.",
    );
    expect(generationFailureMessage("GENERATION_BUDGET_UNAVAILABLE", "it")).toContain(
      "non ha avviato la generazione",
    );
    expect(generationFailureMessage("GENERATION_BUDGET_UNAVAILABLE", "en")).toContain(
      "could not check the spending ceiling",
    );
  });

  it("explains every reason of the review and has a generic sentence for the unknown ones", () => {
    for (const locale of ["it", "en"] as const) {
      const unknown = generationReasonMessages(
        [{ code: "FORBIDDEN_ELEMENT", screen_code: null, detail: "" }],
        locale,
      );
      const sentences = generationReasonMessages(
        reasons.map((code) => ({ code, screen_code: "SCR-001", detail: "" })),
        locale,
      );

      expect(sentences).toHaveLength(reasons.length);
      expect(sentences).not.toContain(unknown[0]);
    }
    expect(generationFailureMessage(null, "en")).toBe(generationFailureMessage("NOPE", "en"));
    expect(generationFailureMessage(undefined, "it")).toBe(
      "Non è stato possibile completare la richiesta. Puoi riprovare.",
    );
    expect(generationFailureMessage("LOW_CONTRAST", "it")).toBe(
      "Un testo non si leggeva bene sul suo sfondo.",
    );
  });
});
