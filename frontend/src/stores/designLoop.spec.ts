import { createPinia, setActivePinia } from "pinia";
import { beforeEach, describe, expect, it, vi } from "vitest";

import type { DesignLoopApi } from "../api/designLoop";
import { DesignLoopApiError } from "../api/designLoop";
import type { DesignEvaluationRunPayload, InsightApplicationPayload } from "../types/designLoop";
import { runFindings, useDesignLoopStore } from "./designLoop";

const authorize = <T>(operation: (accessToken: string) => Promise<T>) => operation("token");

function run(id: string): DesignEvaluationRunPayload {
  return {
    schema_version: 1,
    id,
    project_id: "project-1",
    owner_user_id: "owner-1",
    design_version_id: "version-1",
    design_version_number: 1,
    design_content_hash: "a".repeat(64),
    alternative_id: "alternative-1",
    alternative_code: "DES-001",
    bundle: {},
    responses: [],
    started_at: "2026-09-25T19:59:00Z",
    completed_at: "2026-09-25T20:00:00Z",
    content_hash: "e".repeat(64),
  };
}

const application: InsightApplicationPayload = {
  id: "application-1",
  project_id: "project-1",
  owner_user_id: "owner-1",
  source_kind: "DESIGN_CRITIQUE",
  source_id: "CRQ-001:0",
  source_twin_id: "twin-1",
  text: "Keep the labels visible.",
  target: "DESIGN",
  target_field: null,
  target_version_id: "version-2",
  target_version_number: 2,
  target_code: "DRK-002",
  created_at: "2026-09-25T20:00:00Z",
  content_hash: "c".repeat(64),
};

function fakeApi(): DesignLoopApi {
  return {
    evaluate: vi.fn(async () => run("run-2")),
    runs: vi.fn(async () => [run("run-1")]),
    comparison: vi.fn(async () => null),
    regenerate: vi.fn(async () => ({ status: "CREATED", issue: null }) as never),
    applyInsight: vi.fn(async () => application),
    applications: vi.fn(async () => [application]),
  };
}

describe("designLoop store", () => {
  beforeEach(() => {
    setActivePinia(createPinia());
  });

  it("loads runs and applications, evaluates and prepends the new run", async () => {
    const store = useDesignLoopStore();
    const api = fakeApi();
    await store.load("project-1", authorize, api);
    expect(store.loaded).toBe(true);
    expect(store.runs.map((item) => item.id)).toEqual(["run-1"]);
    expect(store.applications).toEqual([application]);
    const created = await store.evaluate("project-1", "version-1", "a".repeat(64), authorize, api);
    expect(created.id).toBe("run-2");
    expect(store.runs.map((item) => item.id)).toEqual(["run-2", "run-1"]);
    expect(store.latestRun?.id).toBe("run-2");
    expect(runFindings(created)).toEqual([]);
    expect(vi.mocked(api.comparison)).toHaveBeenCalledTimes(2);
  });

  it("records the evaluator availability and applied insights", async () => {
    const store = useDesignLoopStore();
    const api = fakeApi();
    vi.mocked(api.evaluate).mockRejectedValueOnce(
      new DesignLoopApiError("failed", {
        status: 503,
        code: "DESIGN_EVALUATOR_NOT_CONFIGURED",
        payload: null,
      }),
    );
    await expect(
      store.evaluate("project-1", "version-1", "a".repeat(64), authorize, api),
    ).rejects.toBeInstanceOf(DesignLoopApiError);
    expect(store.evaluatorUnavailable).toBe(true);
    expect(store.error).toBe("DESIGN_EVALUATOR_NOT_CONFIGURED");
    const applied = await store.apply(
      "project-1",
      {
        source_kind: "DESIGN_CRITIQUE",
        source_id: "CRQ-001:0",
        text: "Keep the labels visible.",
        target: "DESIGN",
      },
      authorize,
      api,
    );
    expect(applied).toEqual(application);
    expect(store.lastApplication).toEqual(application);
    expect(store.applications).toEqual([application]);
    expect(store.busy).toBeNull();
    const result = await store.regenerate("project-1", authorize, api);
    expect(result.status).toBe("CREATED");
    store.reset("project-2");
    expect(store.runs).toEqual([]);
    expect(store.projectId).toBe("project-2");
  });
});
