import { mount } from "@vue/test-utils";
import { createPinia, setActivePinia } from "pinia";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { defineComponent, h, nextTick, ref } from "vue";

import {
  clearFollowedGenerations,
  GenerationJobsApiError,
  sendGeneration,
  type GenerationJobsApi,
  type GenerationRequestJob,
} from "../api/generationJobs";
import {
  settledCode,
  useGenerationJobsStore,
  useGenerationResume,
  type GenerationResume,
  type GenerationSettlement,
} from "./generationJobs";
import type { GenerationOperation } from "../types/designMockups";

const PROJECT_ID = "00000000-0000-4000-8000-000000000010";
const OTHER_PROJECT_ID = "00000000-0000-4000-8000-000000000011";
const JOB_ID = "00000000-0000-4000-8000-0000000000aa";
const MOCKUP_JOB_ID = "00000000-0000-4000-8000-0000000000bb";

const authorize = <T>(operation: (accessToken: string) => Promise<T>): Promise<T> =>
  operation("token");

function job(overrides: Partial<GenerationRequestJob> = {}): GenerationRequestJob {
  return {
    job_id: JOB_ID,
    kind: "REQUEST",
    operation: "REQUIREMENTS_PROPOSAL",
    status: "RUNNING",
    stage: "GENERATING",
    attempt: 1,
    started_at: "2026-09-28T10:00:00+00:00",
    finished_at: null,
    alternative_id: null,
    failure: null,
    response: null,
    ...overrides,
  };
}

function finished(statusCode: number, body: unknown): GenerationRequestJob {
  return job({
    status: statusCode < 400 ? "SUCCEEDED" : "FAILED",
    stage: null,
    finished_at: "2026-09-28T10:02:00+00:00",
    response: { status_code: statusCode, body },
  });
}

function fakeApi(running: GenerationRequestJob[], reads: (GenerationRequestJob | Error)[]) {
  const api = {
    list: vi.fn(async () => running),
    job: vi.fn(async () => {
      const next = reads.shift();

      if (next === undefined) {
        return job();
      }

      if (next instanceof Error) {
        throw next;
      }

      return next;
    }),
  } satisfies GenerationJobsApi;

  return api;
}

function refusal(status: number, code: string): GenerationJobsApiError {
  return new GenerationJobsApiError(code, { status, code, payload: null });
}

function host(
  operations: readonly GenerationOperation[],
  api: GenerationJobsApi,
  onSettled: (settlement: GenerationSettlement) => unknown,
  projectId = ref(PROJECT_ID),
) {
  let exposed: GenerationResume | null = null;
  const wrapper = mount(
    defineComponent({
      setup() {
        exposed = useGenerationResume({
          projectId: () => projectId.value,
          operations,
          authorize,
          onSettled,
          api,
        });
        return () => h("div");
      },
    }),
  );

  if (exposed === null) {
    throw new Error("The resume was not created");
  }

  return { wrapper, resume: exposed as GenerationResume, projectId };
}

describe("generation jobs store", () => {
  beforeEach(() => {
    setActivePinia(createPinia());
    vi.useFakeTimers();
    clearFollowedGenerations();
  });

  afterEach(() => {
    vi.useRealTimers();
    clearFollowedGenerations();
  });

  it("shows a job that this tab follows while it runs", async () => {
    const store = useGenerationJobsStore();
    const fetchImpl = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      void input;
      const body = init?.method === "POST" ? job() : finished(201, { status: "CREATED" });
      return new Response(JSON.stringify(body), { status: init?.method === "POST" ? 202 : 200 });
    });

    const pending = sendGeneration(
      `/api/v1/projects/${PROJECT_ID}/requirements/proposals`,
      { method: "POST", headers: { Authorization: "Bearer token" } },
      { fetchImpl, basePath: "/api/v1", projectId: PROJECT_ID },
    );
    await vi.advanceTimersByTimeAsync(0);

    expect(store.runningFor(PROJECT_ID, ["REQUIREMENTS_PROPOSAL"])?.job_id).toBe(JOB_ID);
    expect(store.runningFor(PROJECT_ID, ["DESIGN_PROPOSAL"])).toBeNull();
    expect(store.runningFor(OTHER_PROJECT_ID, ["REQUIREMENTS_PROPOSAL"])).toBeNull();
    expect(store.isOwn(JOB_ID)).toBe(true);

    await vi.advanceTimersByTimeAsync(2000);
    await pending;

    expect(store.runningFor(PROJECT_ID, ["REQUIREMENTS_PROPOSAL"])).toBeNull();
  });

  it("resumes the running jobs of the operations it is asked for", async () => {
    const store = useGenerationJobsStore();
    const mockup = job({ job_id: MOCKUP_JOB_ID, kind: "MOCKUP", operation: "MOCKUP" });
    const api = fakeApi([mockup, job()], []);

    const found = await store.resume(PROJECT_ID, ["REQUIREMENTS_PROPOSAL"], authorize, api);

    expect(found.map((item) => item.job_id)).toEqual([JOB_ID]);
    expect(api.list).toHaveBeenCalledWith(PROJECT_ID, "token", "RUNNING");
    expect(store.runningFor(PROJECT_ID, ["REQUIREMENTS_PROPOSAL"])?.job_id).toBe(JOB_ID);
    expect(store.isOwn(JOB_ID)).toBe(false);
  });

  it("shares the reading of the running jobs only while it is in flight", async () => {
    const store = useGenerationJobsStore();
    const api = fakeApi([job()], []);

    await Promise.all([
      store.resume(PROJECT_ID, ["REQUIREMENTS_PROPOSAL"], authorize, api),
      store.resume(PROJECT_ID, ["DESIGN_EVALUATION"], authorize, api),
    ]);

    expect(api.list).toHaveBeenCalledOnce();

    await store.resume(PROJECT_ID, ["DESIGN_PROPOSAL"], authorize, api);

    expect(api.list).toHaveBeenCalledTimes(2);
  });

  it("asks again after a failed reading of the running jobs", async () => {
    const store = useGenerationJobsStore();
    const api = fakeApi([job()], []);
    api.list.mockRejectedValueOnce(new TypeError("Failed to fetch"));

    await expect(
      store.resume(PROJECT_ID, ["REQUIREMENTS_PROPOSAL"], authorize, api),
    ).rejects.toThrow("Failed to fetch");
    const found = await store.resume(PROJECT_ID, ["REQUIREMENTS_PROPOSAL"], authorize, api);

    expect(found.map((item) => item.job_id)).toEqual([JOB_ID]);
    expect(api.list).toHaveBeenCalledTimes(2);
  });

  it("waits for a resumed job and retries a failed reading of the job", async () => {
    const store = useGenerationJobsStore();
    const api = fakeApi(
      [job()],
      [new TypeError("Failed to fetch"), refusal(503, "UNAVAILABLE"), job(), finished(201, {})],
    );
    await store.resume(PROJECT_ID, ["REQUIREMENTS_PROPOSAL"], authorize, api);

    const settlement = store.wait(PROJECT_ID, JOB_ID, authorize, api);
    await vi.advanceTimersByTimeAsync(8000);

    await expect(settlement).resolves.toEqual({ kind: "finished", job: finished(201, {}) });
    expect(api.job).toHaveBeenCalledTimes(4);
    expect(store.runningFor(PROJECT_ID, ["REQUIREMENTS_PROPOSAL"])).toBeNull();
  });

  it("reports a resumed job that the Studio no longer knows as lost", async () => {
    const store = useGenerationJobsStore();
    const api = fakeApi([job()], [refusal(404, "GENERATION_JOB_NOT_FOUND")]);
    await store.resume(PROJECT_ID, ["REQUIREMENTS_PROPOSAL"], authorize, api);

    const settlement = store.wait(PROJECT_ID, JOB_ID, authorize, api);
    await vi.advanceTimersByTimeAsync(2000);

    await expect(settlement).resolves.toEqual({ kind: "lost" });
  });

  it("stops at a refusal that is not temporary", async () => {
    const store = useGenerationJobsStore();
    const api = fakeApi([job()], [refusal(403, "FORBIDDEN")]);
    await store.resume(PROJECT_ID, ["REQUIREMENTS_PROPOSAL"], authorize, api);

    const settlement = store.wait(PROJECT_ID, JOB_ID, authorize, api);
    await vi.advanceTimersByTimeAsync(2000);

    await expect(settlement).resolves.toEqual({ kind: "refused", code: "FORBIDDEN" });
  });

  it("gives up after twenty minutes", async () => {
    const store = useGenerationJobsStore();
    const api = fakeApi([job()], []);
    await store.resume(PROJECT_ID, ["REQUIREMENTS_PROPOSAL"], authorize, api);

    const settlement = store.wait(PROJECT_ID, JOB_ID, authorize, api);
    await vi.advanceTimersByTimeAsync(20 * 60 * 1000 + 3000);

    await expect(settlement).resolves.toEqual({ kind: "expired" });
  });

  it("stops waiting when another project opens", async () => {
    const store = useGenerationJobsStore();
    const api = fakeApi([job()], []);
    await store.resume(PROJECT_ID, ["REQUIREMENTS_PROPOSAL"], authorize, api);

    const settlement = store.wait(PROJECT_ID, JOB_ID, authorize, api);
    store.activate(OTHER_PROJECT_ID);
    await vi.advanceTimersByTimeAsync(2000);

    await expect(settlement).resolves.toEqual({ kind: "inactive" });
    expect(api.job).not.toHaveBeenCalled();
  });

  it("shares one wait for the same job", async () => {
    const store = useGenerationJobsStore();
    const api = fakeApi([job()], [finished(201, {})]);
    await store.resume(PROJECT_ID, ["REQUIREMENTS_PROPOSAL"], authorize, api);

    const first = store.wait(PROJECT_ID, JOB_ID, authorize, api);
    const second = store.wait(PROJECT_ID, JOB_ID, authorize, api);

    await vi.advanceTimersByTimeAsync(2000);

    expect(await second).toEqual(await first);
    expect(api.job).toHaveBeenCalledOnce();
  });

  it("reads the outcome of a finished job like the step would read the answer", () => {
    expect(settledCode(finished(201, { status: "CREATED" }))).toBeNull();
    expect(settledCode(finished(409, { detail: { code: "DESIGN_DISCUSSION_OPEN" } }))).toBe(
      "DESIGN_DISCUSSION_OPEN",
    );
    expect(settledCode(finished(401, { detail: "invalid_authentication" }))).toBe(
      "invalid_authentication",
    );
    expect(settledCode(finished(500, "Internal Server Error"))).toBe("GENERATION_FAILED");
    expect(
      settledCode(finished(200, { status: "REJECTED", proposal_issue: "INVALID_PROVIDER_OUTPUT" })),
    ).toBe("INVALID_PROVIDER_OUTPUT");
    expect(
      settledCode(
        job({
          status: "FAILED",
          failure: { code: "GENERATION_JOB_CANCELLED", reasons: [] },
        }),
      ),
    ).toBe("GENERATION_JOB_CANCELLED");
  });

  it("reads the reason of a proposal refused in a job before the code of the refusal", () => {
    const refused = (detail: Record<string, unknown>) => settledCode(finished(409, { detail }));

    expect(refused({ code: "PROPOSAL_REJECTED", proposal_issue: "UX_DESIGNER_REQUIRED" })).toBe(
      "UX_DESIGNER_REQUIRED",
    );
    expect(refused({ proposal_issue: "REQUIREMENTS_ANALYST_REQUIRED" })).toBe(
      "REQUIREMENTS_ANALYST_REQUIRED",
    );
    expect(refused({ code: "PROPOSAL_REJECTED" })).toBe("PROPOSAL_REJECTED");
    expect(refused({ code: "PROPOSAL_REJECTED", proposal_issue: null })).toBe("PROPOSAL_REJECTED");
    expect(refused({ code: "PROPOSAL_REJECTED", proposal_issue: 409 })).toBe("PROPOSAL_REJECTED");
    expect(refused({ code: "PROPOSAL_REJECTED", proposal_issue: "" })).toBe("PROPOSAL_REJECTED");
    expect(refused({ code: "REQUIREMENTS_UNCHANGED" })).toBe("REQUIREMENTS_UNCHANGED");
    expect(refused({ proposal_issue: 409 })).toBe("GENERATION_FAILED");
  });
});

describe("useGenerationResume", () => {
  beforeEach(() => {
    setActivePinia(createPinia());
    vi.useFakeTimers();
    clearFollowedGenerations();
  });

  afterEach(() => {
    vi.useRealTimers();
    clearFollowedGenerations();
  });

  it("waits for the running job of its step and lets the step reload when it ends", async () => {
    const api = fakeApi([job()], [job({ stage: "VALIDATING" }), finished(201, {})]);
    const onSettled = vi.fn();
    const { resume, wrapper } = host(["REQUIREMENTS_PROPOSAL"], api, onSettled);

    expect(resume.checked.value).toBe(false);
    await vi.advanceTimersByTimeAsync(0);

    expect(resume.checked.value).toBe(true);
    expect(resume.job.value?.job_id).toBe(JOB_ID);

    await vi.advanceTimersByTimeAsync(2000);
    expect(resume.job.value?.stage).toBe("VALIDATING");

    await vi.advanceTimersByTimeAsync(2000);
    expect(resume.job.value).toBeNull();
    expect(onSettled).toHaveBeenCalledWith({ kind: "finished", job: finished(201, {}) });
    expect(resume.failure.value).toBeNull();
    wrapper.unmount();
  });

  it("says why a resumed generation did not succeed", async () => {
    const refused = finished(503, { detail: { code: "PROVIDER_UNAVAILABLE" } });
    const api = fakeApi(
      [job({ operation: "DESIGN_EVALUATION" })],
      [job({ ...refused, operation: "DESIGN_EVALUATION" })],
    );
    const onSettled = vi.fn();
    const { resume } = host(["DESIGN_EVALUATION"], api, onSettled);

    await vi.advanceTimersByTimeAsync(2000);

    expect(resume.failure.value).toEqual({
      operation: "DESIGN_EVALUATION",
      code: "PROVIDER_UNAVAILABLE",
      lost: false,
    });
    expect(onSettled).toHaveBeenCalledOnce();
    resume.dismiss();
    expect(resume.failure.value).toBeNull();
  });

  it("names a resumed generation that was interrupted as lost", async () => {
    const api = fakeApi([job()], [refusal(404, "GENERATION_JOB_NOT_FOUND")]);
    const onSettled = vi.fn();
    const { resume } = host(["REQUIREMENTS_PROPOSAL"], api, onSettled);

    await vi.advanceTimersByTimeAsync(2000);

    expect(resume.failure.value).toEqual({
      operation: "REQUIREMENTS_PROPOSAL",
      code: "GENERATION_JOB_NOT_FOUND",
      lost: true,
    });
    expect(onSettled).toHaveBeenCalledWith({ kind: "lost" });
  });

  it("names a cancelled generation of this tab as lost and lets the step reload", async () => {
    const api = fakeApi([], []);
    const onSettled = vi.fn();
    const { resume } = host(["REQUIREMENTS_PROPOSAL"], api, onSettled);
    await vi.advanceTimersByTimeAsync(0);
    const cancelled = job({
      status: "FAILED",
      stage: null,
      failure: { code: "GENERATION_JOB_CANCELLED", reasons: [] },
    });
    const fetchImpl = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      void input;
      const body = init?.method === "POST" ? job() : cancelled;
      return new Response(JSON.stringify(body), { status: init?.method === "POST" ? 202 : 200 });
    });

    const pending = sendGeneration(
      `/api/v1/projects/${PROJECT_ID}/requirements/proposals`,
      { method: "POST", headers: { Authorization: "Bearer token" } },
      { fetchImpl, basePath: "/api/v1", projectId: PROJECT_ID },
    );
    await vi.advanceTimersByTimeAsync(0);
    expect(resume.job.value?.job_id).toBe(JOB_ID);
    await vi.advanceTimersByTimeAsync(2000);
    const response = await pending;

    expect(response.status).toBe(500);
    expect(resume.job.value).toBeNull();
    expect(resume.failure.value).toMatchObject({ code: "GENERATION_JOB_NOT_FOUND", lost: true });
    expect(onSettled).toHaveBeenCalledWith({ kind: "lost" });
    expect(api.job).not.toHaveBeenCalled();
  });

  it("does not block its step when the running jobs cannot be read", async () => {
    const api = fakeApi([], []);
    api.list.mockRejectedValueOnce(refusal(405, "METHOD_NOT_ALLOWED"));
    const { resume } = host(["REQUIREMENTS_PROPOSAL"], api, vi.fn());

    await vi.advanceTimersByTimeAsync(0);

    expect(resume.checked.value).toBe(true);
    expect(resume.job.value).toBeNull();
  });

  it("checks again when the project changes and ignores the jobs of the previous one", async () => {
    const api = fakeApi([job()], []);
    const onSettled = vi.fn();
    const { resume, projectId } = host(["REQUIREMENTS_PROPOSAL"], api, onSettled);
    await vi.advanceTimersByTimeAsync(0);
    expect(resume.job.value?.job_id).toBe(JOB_ID);

    api.list.mockResolvedValueOnce([]);
    projectId.value = OTHER_PROJECT_ID;
    await nextTick();
    await vi.advanceTimersByTimeAsync(2000);

    expect(api.list).toHaveBeenLastCalledWith(OTHER_PROJECT_ID, "token", "RUNNING");
    expect(resume.job.value).toBeNull();
    expect(onSettled).not.toHaveBeenCalled();
  });
});
