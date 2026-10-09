import { createPinia, setActivePinia } from "pinia";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import {
  BASE_DESIGN_PACKAGE,
  DESIGN_ALTERNATIVE_ID,
  DESIGN_PROJECT_ID,
  UNSELECTED_DESIGN_VERSION,
} from "@/test/designFixtures";

import type { DesignIterationItem, DesignIterationsApi } from "../api/designIterations";
import type { DesignMockupsApi } from "../api/designMockups";
import type { DesignPackageVersionPayload } from "../types/design";
import type { GenerationJobPayload } from "../types/designMockups";
import { useDesignIterationsStore } from "./designIterations";
import { POLL_INTERVAL_MILLISECONDS, type AuthorizedMockupRequest } from "./designMockups";

const PROJECT = DESIGN_PROJECT_ID;
const HASH = "2".repeat(64);
const VERSION_ID = "00000000-0000-4000-8000-000000004410";
const SOURCE_ID = "00000000-0000-4000-8000-000000004401";
const REDRAW =
  "Redraw the mockup so that it reproduces the look and the structure of the supplied design “Hotel desk”: same layout, colours and hierarchy of the content, with the screens and the requirements of the project.";

const authorize: AuthorizedMockupRequest = (operation) => operation("token");

const DRAWN: DesignPackageVersionPayload = {
  ...UNSELECTED_DESIGN_VERSION,
  id: VERSION_ID,
  content_hash: HASH,
  package: {
    ...BASE_DESIGN_PACKAGE,
    owner_selected_alternative_id: DESIGN_ALTERNATIVE_ID,
    generated_mockup: {
      mockup: {
        contract_version: 1,
        design_alternative_id: DESIGN_ALTERNATIVE_ID,
        title: "Reservation desk",
        styles: ".desk{display:grid}",
        screens: [{ code: "SCR-001", title: "Desk", state: "DEFAULT", markup: "<h1>Desk</h1>" }],
      },
      requirement_ids_by_code: {},
    },
    owner_assertions: [],
  },
};

function job(
  status: GenerationJobPayload["status"],
  overrides: Partial<GenerationJobPayload> = {},
): GenerationJobPayload {
  return {
    job_id: "redraw-job-1",
    kind: "ITERATION",
    status,
    stage: status === "RUNNING" ? "GENERATING" : null,
    attempt: 1,
    started_at: "2026-10-09T10:00:00+00:00",
    finished_at: status === "RUNNING" ? null : "2026-10-09T10:07:00+00:00",
    alternative_id: DESIGN_ALTERNATIVE_ID,
    result: null,
    failure: null,
    ...overrides,
  };
}

const LISTED: DesignIterationItem = {
  generation_id: "redraw-1",
  requested_at: "2026-10-09T10:00:00+00:00",
  request: REDRAW,
  assertions: [],
  changes: ["The layout follows the supplied design"],
  status: "PROPOSED",
  base_design_version_number: 2,
  applied_design_version_number: null,
  cost_microusd: 0,
  critique_source_id: SOURCE_ID,
};

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
    capabilities: vi.fn<DesignMockupsApi["capabilities"]>(),
    startJob: vi.fn<DesignMockupsApi["startJob"]>(),
    job: vi.fn<DesignMockupsApi["job"]>(),
    latest: vi.fn<DesignMockupsApi["latest"]>(async () => null),
    document: vi.fn<DesignMockupsApi["document"]>(),
  };
}

function activeStore() {
  const store = useDesignIterationsStore();
  store.activate(PROJECT, DRAWN);
  return store;
}

describe("design iterations store with a supplied design", () => {
  beforeEach(() => {
    sessionStorage.clear();
    vi.useFakeTimers({ now: new Date("2026-10-09T10:00:05Z") });
    setActivePinia(createPinia());
  });

  afterEach(() => {
    vi.useRealTimers();
    sessionStorage.clear();
  });

  it("puts the supplied design of a redraw in the body and keeps it with the request", async () => {
    const api = fakeApi();
    const store = activeStore();

    const outcome = await store.start(
      { request: REDRAW, assertions: [], target: null },
      authorize,
      { api },
      SOURCE_ID,
    );

    expect(outcome).toBe("started");
    expect(api.startJob).toHaveBeenCalledWith(
      PROJECT,
      {
        design_version_id: VERSION_ID,
        design_content_hash: HASH,
        request: REDRAW,
        assertions: [],
        critique_source_id: SOURCE_ID,
      },
      "token",
    );
    expect(store.request).toEqual({ request: REDRAW, assertions: [], critiqueSourceId: SOURCE_ID });
    expect(store.state).toBe("drawing");
  });

  it.each([
    ["no supplied design", undefined],
    ["a supplied design left out", null],
  ] as const)("leaves the body as it was with %s", async (_case, source) => {
    const api = fakeApi();
    const store = activeStore();

    if (source === undefined) {
      await store.start({ request: REDRAW }, authorize, { api });
    } else {
      await store.start({ request: REDRAW }, authorize, { api }, source);
    }

    expect(Object.keys(api.startJob.mock.calls[0]?.[1] ?? {})).toEqual([
      "design_version_id",
      "design_content_hash",
      "request",
      "assertions",
    ]);
    expect(store.request).toEqual({ request: REDRAW, assertions: [] });
  });

  it("refuses a blank supplied design without calling the server", async () => {
    const api = fakeApi();
    const store = activeStore();

    expect(await store.start({ request: REDRAW }, authorize, { api }, "   ")).toBe("invalid");
    expect(api.startJob).not.toHaveBeenCalled();
    expect(store.state).toBe("idle");
  });

  it("sends the supplied design again when a failed redraw is retried", async () => {
    const api = fakeApi();
    api.job.mockResolvedValue(job("FAILED", { failure: { code: "TIMEOUT", reasons: [] } }));
    const store = activeStore();
    await store.start({ request: REDRAW }, authorize, { api }, SOURCE_ID);

    await vi.advanceTimersByTimeAsync(POLL_INTERVAL_MILLISECONDS);
    expect(store.state).toBe("failed");
    expect(await store.retry(authorize, { api })).toBe("started");

    expect(api.startJob).toHaveBeenCalledTimes(2);
    expect(api.startJob.mock.calls[1]?.[1]).toEqual(api.startJob.mock.calls[0]?.[1]);
    expect(api.startJob.mock.calls[1]?.[1].critique_source_id).toBe(SOURCE_ID);
  });

  it("keeps the supplied design of a running redraw across a reload", async () => {
    await activeStore().start({ request: REDRAW }, authorize, { api: fakeApi() }, SOURCE_ID);

    setActivePinia(createPinia());
    const api = fakeApi();
    api.job.mockResolvedValue(job("FAILED", { failure: { code: "TIMEOUT", reasons: [] } }));
    const store = activeStore();

    expect(await store.recover(authorize, { api, mockupsApi: fakeMockupsApi() })).toBe("failed");
    expect(store.request).toEqual({ request: REDRAW, assertions: [], critiqueSourceId: SOURCE_ID });
    expect(await store.retry(authorize, { api })).toBe("started");
    expect(api.startJob.mock.calls[0]?.[1]).toMatchObject({ critique_source_id: SOURCE_ID });
  });

  it("lists the iterations with the supplied design they come from", async () => {
    const api = fakeApi();
    const store = activeStore();

    expect(await store.loadList(authorize, { api })).toEqual([LISTED]);
    expect(store.items[0]?.critique_source_id).toBe(SOURCE_ID);
  });
});
