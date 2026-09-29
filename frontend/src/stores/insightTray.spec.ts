import { createPinia, setActivePinia } from "pinia";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { DesignLoopApiError, type InsightBatchApi } from "../api/designLoop";
import type {
  InsightApplicationPayload,
  InsightBatchApplicationRequest,
} from "../types/designLoop";
import { MAX_TRAY_ITEMS, type InsightTrayItem, useInsightTrayStore } from "./insightTray";

const authorize = <T>(operation: (accessToken: string) => Promise<T>) => operation("token");

function item(overrides: Partial<InsightTrayItem> = {}): InsightTrayItem {
  return {
    sourceKind: "TWIN_CHAT_INSIGHT",
    sourceId: "turn-1:0",
    sourceTwinId: "twin-1",
    text: "Guests arrive in groups.",
    briefField: "functional_requirements",
    ...overrides,
  };
}

function application(sourceId: string): InsightApplicationPayload {
  return {
    id: `application-${sourceId}`,
    project_id: "project-1",
    owner_user_id: "owner-1",
    source_kind: "TWIN_CHAT_INSIGHT",
    source_id: sourceId,
    source_twin_id: "twin-1",
    text: "Guests arrive in groups.",
    target: "BRIEF",
    target_field: "functional_requirements",
    target_version_id: "brief-3",
    target_version_number: 3,
    target_code: null,
    created_at: "2026-09-28T10:00:00Z",
    content_hash: "c".repeat(64),
  };
}

function fakeApi(): InsightBatchApi {
  return {
    applyInsightBatch: vi.fn(async (_projectId: string, body: InsightBatchApplicationRequest) => ({
      applications: body.items.map((entry) => application(entry.source_id)),
      brief_version_number: 3,
    })),
  };
}

describe("insight tray store", () => {
  beforeEach(() => {
    setActivePinia(createPinia());
  });

  it("keeps one entry per source and per project", () => {
    const tray = useInsightTrayStore();
    expect(tray.isVisible("project-1")).toBe(false);
    expect(tray.add("project-1", item())).toBe(true);
    expect(tray.add("project-1", item({ text: "Changed", briefField: "goals" }))).toBe(false);
    expect(tray.add("project-1", item({ sourceKind: "DESIGN_CRITIQUE" }))).toBe(true);
    expect(tray.add("project-2", item())).toBe(true);
    expect(tray.itemsOf("project-1").map((entry) => entry.sourceKind)).toEqual([
      "TWIN_CHAT_INSIGHT",
      "DESIGN_CRITIQUE",
    ]);
    expect(tray.itemOf("project-1", "TWIN_CHAT_INSIGHT", "turn-1:0")?.text).toBe(
      "Guests arrive in groups.",
    );
    expect(tray.itemOf("project-1", "SYNTHETIC_FINDING", "turn-1:0")).toBeNull();
    expect(tray.isVisible("project-1")).toBe(true);
    tray.remove("project-1", "DESIGN_CRITIQUE", "turn-1:0");
    expect(tray.itemsOf("project-1")).toHaveLength(1);
    tray.clear("project-1");
    expect(tray.itemsOf("project-1")).toEqual([]);
    expect(tray.isVisible("project-1")).toBe(false);
    expect(tray.itemsOf("project-2")).toHaveLength(1);
  });

  it("refuses more insights than one batch can bring into the brief", () => {
    const tray = useInsightTrayStore();
    for (let index = 0; index < MAX_TRAY_ITEMS; index += 1) {
      expect(tray.add("project-1", item({ sourceId: `turn-${index}:0` }))).toBe(true);
    }
    expect(tray.isFull("project-1")).toBe(true);
    expect(tray.add("project-1", item({ sourceId: "turn-99:0" }))).toBe(false);
    expect(tray.itemsOf("project-1")).toHaveLength(MAX_TRAY_ITEMS);
    expect(tray.isFull("project-2")).toBe(false);
  });

  it("brings every insight into the brief in one call and keeps the result", async () => {
    const tray = useInsightTrayStore();
    const api = fakeApi();
    tray.add("project-1", item());
    tray.add(
      "project-1",
      item({
        sourceId: "turn-2:0",
        sourceTwinId: null,
        text: "Show the queue.",
        briefField: "goals",
      }),
    );
    tray.add("project-2", item());
    const pending = tray.applyAll("project-1", api, authorize);
    expect(tray.isApplying("project-1")).toBe(true);
    expect(tray.add("project-1", item({ sourceId: "turn-3:0" }))).toBe(false);
    await expect(pending).resolves.toEqual({ count: 2, briefVersionNumber: 3 });
    expect(api.applyInsightBatch).toHaveBeenCalledTimes(1);
    expect(vi.mocked(api.applyInsightBatch).mock.calls[0]).toEqual([
      "project-1",
      {
        items: [
          {
            source_kind: "TWIN_CHAT_INSIGHT",
            source_id: "turn-1:0",
            source_twin_id: "twin-1",
            text: "Guests arrive in groups.",
            target: "BRIEF",
            brief_field: "functional_requirements",
          },
          {
            source_kind: "TWIN_CHAT_INSIGHT",
            source_id: "turn-2:0",
            source_twin_id: null,
            text: "Show the queue.",
            target: "BRIEF",
            brief_field: "goals",
          },
        ],
      },
      "token",
    ]);
    expect(tray.isApplying("project-1")).toBe(false);
    expect(tray.itemsOf("project-1")).toEqual([]);
    expect(tray.resultOf("project-1")).toEqual({ count: 2, briefVersionNumber: 3 });
    expect(tray.isVisible("project-1")).toBe(true);
    expect(tray.itemsOf("project-2")).toHaveLength(1);
    expect(tray.resultOf("project-2")).toBeNull();
    tray.dismissResult("project-1");
    expect(tray.isVisible("project-1")).toBe(false);
    expect(await tray.applyAll("project-1", api, authorize)).toBeNull();
    expect(api.applyInsightBatch).toHaveBeenCalledTimes(1);
  });

  it("keeps the insights, the error code and the offending sources when the batch is refused", async () => {
    const tray = useInsightTrayStore();
    const api = fakeApi();
    vi.mocked(api.applyInsightBatch)
      .mockRejectedValueOnce(
        new DesignLoopApiError("failed", {
          status: 409,
          code: "INSIGHT_ALREADY_APPLIED",
          payload: { detail: { code: "INSIGHT_ALREADY_APPLIED", sources: ["turn-2:0", 7] } },
        }),
      )
      .mockRejectedValueOnce(new Error("network down"));
    tray.add("project-1", item());
    tray.add("project-1", item({ sourceId: "turn-2:0" }));
    await expect(tray.applyAll("project-1", api, authorize)).rejects.toBeInstanceOf(
      DesignLoopApiError,
    );
    expect(tray.itemsOf("project-1")).toHaveLength(2);
    expect(tray.resultOf("project-1")).toBeNull();
    expect(tray.failureOf("project-1")).toEqual({
      code: "INSIGHT_ALREADY_APPLIED",
      sources: ["turn-2:0"],
    });
    tray.remove("project-1", "TWIN_CHAT_INSIGHT", "turn-2:0");
    expect(tray.failureOf("project-1")).toBeNull();
    await expect(tray.applyAll("project-1", api, authorize)).rejects.toThrow("network down");
    expect(tray.failureOf("project-1")).toEqual({ code: "network down", sources: [] });
    expect(tray.isApplying("project-1")).toBe(false);
    tray.add("project-1", item({ sourceId: "turn-4:0" }));
    expect(tray.failureOf("project-1")).toBeNull();
  });
});
