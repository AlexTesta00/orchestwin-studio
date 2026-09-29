import { createPinia, setActivePinia } from "pinia";
import { flushPromises, mount } from "@vue/test-utils";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { DesignLoopApiError, type InsightBatchApi } from "@/api/designLoop";
import { type InsightTrayItem, useInsightTrayStore } from "@/stores/insightTray";
import { expectAccessible } from "@/test/axe";
import type {
  InsightApplicationPayload,
  InsightBatchApplicationPayload,
  InsightBatchApplicationRequest,
} from "@/types/designLoop";
import InsightBriefTray from "./InsightBriefTray.vue";

const authorize = <T>(operation: (accessToken: string) => Promise<T>) => operation("token");

function item(index: number, overrides: Partial<InsightTrayItem> = {}): InsightTrayItem {
  return {
    sourceKind: "TWIN_CHAT_INSIGHT",
    sourceId: `turn-${index}:0`,
    sourceTwinId: "twin-1",
    text: `Insight number ${index}.`,
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
    text: "Insight.",
    target: "BRIEF",
    target_field: "functional_requirements",
    target_version_id: "brief-4",
    target_version_number: 4,
    target_code: null,
    created_at: "2026-09-28T10:00:00Z",
    content_hash: "c".repeat(64),
  };
}

function fakeApi(): InsightBatchApi {
  return {
    applyInsightBatch: vi.fn(async (_projectId: string, body: InsightBatchApplicationRequest) => ({
      applications: body.items.map((entry) => application(entry.source_id)),
      brief_version_number: 4,
    })),
  };
}

function mountTray(api: InsightBatchApi = fakeApi(), locale: "en" | "it" = "it") {
  return mount(InsightBriefTray, {
    attachTo: document.body,
    props: { projectId: "project-1", locale, authorize, api },
  });
}

describe("InsightBriefTray", () => {
  beforeEach(() => {
    setActivePinia(createPinia());
  });

  it("stays hidden while the tray of its project is empty", async () => {
    const tray = useInsightTrayStore();
    const wrapper = mountTray();
    expect(wrapper.find('[data-testid="insight-brief-tray"]').exists()).toBe(false);
    tray.add("project-2", item(1));
    await flushPromises();
    expect(wrapper.find('[data-testid="insight-brief-tray"]').exists()).toBe(false);
    tray.add("project-1", item(1));
    await flushPromises();
    expect(wrapper.get('[role="region"]').attributes("aria-label")).toBe("Spunti per il brief");
    wrapper.unmount();
  });

  it("lists the insights set aside and lets the owner remove or clear them", async () => {
    const tray = useInsightTrayStore();
    tray.add("project-1", item(1));
    tray.add("project-1", item(2));
    tray.add("project-1", item(3));
    const wrapper = mountTray();
    expect(wrapper.get('[data-testid="insight-brief-tray-count"]').text()).toBe(
      "3 spunti messi da parte per il brief",
    );
    expect(
      wrapper
        .findAll('[data-testid="insight-brief-tray-item"]')
        .map((row) => row.find("[id]").text()),
    ).toEqual(["Insight number 1.", "Insight number 2.", "Insight number 3."]);
    const removes = wrapper.findAll('[data-testid="insight-brief-tray-remove"]');
    expect(removes.map((button) => button.attributes("aria-label"))).toEqual([
      "Togli",
      "Togli",
      "Togli",
    ]);
    expect(
      document.getElementById(removes[1]!.attributes("aria-describedby")!)?.textContent?.trim(),
    ).toBe("Insight number 2.");
    await removes[1]!.trigger("click");
    await flushPromises();
    expect(tray.itemsOf("project-1").map((entry) => entry.sourceId)).toEqual([
      "turn-1:0",
      "turn-3:0",
    ]);
    expect(document.activeElement).toBe(
      wrapper.get('[data-testid="insight-brief-tray-count"]').element,
    );
    await wrapper.get('[data-testid="insight-brief-tray-remove"]').trigger("click");
    await flushPromises();
    expect(wrapper.get('[data-testid="insight-brief-tray-count"]').text()).toBe(
      "1 spunto messo da parte per il brief",
    );
    await wrapper.get('[data-testid="insight-brief-tray-clear"]').trigger("click");
    await flushPromises();
    expect(tray.itemsOf("project-1")).toEqual([]);
    expect(wrapper.find('[data-testid="insight-brief-tray"]').exists()).toBe(false);
    wrapper.unmount();
  });

  it("uses the singular and plural forms in English", async () => {
    const tray = useInsightTrayStore();
    tray.add("project-1", item(1));
    const wrapper = mountTray(fakeApi(), "en");
    expect(wrapper.get('[data-testid="insight-brief-tray-count"]').text()).toBe(
      "1 insight set aside for the brief",
    );
    expect(wrapper.get('[data-testid="insight-brief-tray-apply"]').text()).toBe(
      "Add to the brief as one version",
    );
    expect(wrapper.get('[data-testid="insight-brief-tray-clear"]').text()).toBe("Clear");
    tray.add("project-1", item(2));
    await flushPromises();
    expect(wrapper.get('[data-testid="insight-brief-tray-count"]').text()).toBe(
      "2 insights set aside for the brief",
    );
    await wrapper.get('[data-testid="insight-brief-tray-apply"]').trigger("click");
    await flushPromises();
    expect(wrapper.get('[role="status"]').text()).toBe(
      "2 insights added to the brief, version 4. Brief, team, twins, requirements and design need approval again.",
    );
    tray.add("project-1", item(3));
    await flushPromises();
    await wrapper.get('[data-testid="insight-brief-tray-apply"]').trigger("click");
    await flushPromises();
    expect(wrapper.get('[role="status"]').text()).toBe(
      "1 insight added to the brief, version 4. Brief, team, twins, requirements and design need approval again.",
    );
    wrapper.unmount();
  });

  it("brings every insight into the brief in one version and reports it until closed", async () => {
    const tray = useInsightTrayStore();
    tray.add("project-1", item(1));
    tray.add("project-1", item(2, { briefField: "risks", sourceTwinId: null }));
    const api = fakeApi();
    const wrapper = mountTray(api);
    expect(wrapper.get('[role="status"]').text()).toBe("");
    await wrapper.get('[data-testid="insight-brief-tray-apply"]').trigger("click");
    await flushPromises();
    expect(api.applyInsightBatch).toHaveBeenCalledTimes(1);
    expect(vi.mocked(api.applyInsightBatch).mock.calls[0]?.[1].items).toEqual([
      {
        source_kind: "TWIN_CHAT_INSIGHT",
        source_id: "turn-1:0",
        source_twin_id: "twin-1",
        text: "Insight number 1.",
        target: "BRIEF",
        brief_field: "functional_requirements",
      },
      {
        source_kind: "TWIN_CHAT_INSIGHT",
        source_id: "turn-2:0",
        source_twin_id: null,
        text: "Insight number 2.",
        target: "BRIEF",
        brief_field: "risks",
      },
    ]);
    expect(tray.itemsOf("project-1")).toEqual([]);
    expect(wrapper.find('[data-testid="insight-brief-tray-apply"]').exists()).toBe(false);
    expect(wrapper.get('[role="status"]').text()).toBe(
      "Aggiunti al brief 2 spunti, versione 4. Brief, squadra, twin, requisiti e design vanno approvati di nuovo.",
    );
    const close = wrapper.get('[data-testid="insight-brief-tray-close"]');
    expect(close.text()).toBe("Chiudi");
    expect(document.activeElement).toBe(close.element);
    await expectAccessible(wrapper.element);
    await close.trigger("click");
    await flushPromises();
    expect(wrapper.find('[data-testid="insight-brief-tray"]').exists()).toBe(false);
    expect(tray.resultOf("project-1")).toBeNull();
    wrapper.unmount();
  });

  it.each([
    [
      "INSIGHT_ALREADY_APPLIED",
      "Uno spunto era già stato applicato: toglilo e riprova.",
      "Già applicato",
    ],
    [
      "INSIGHT_SOURCE_DISMISSED",
      "Uno spunto viene da un'osservazione messa da parte: toglilo e riprova.",
      "Osservazione messa da parte",
    ],
  ])(
    "explains a batch refused with %s and marks the insight to remove",
    async (code, message, mark) => {
      const tray = useInsightTrayStore();
      tray.add("project-1", item(1));
      tray.add("project-1", item(2));
      const api = fakeApi();
      vi.mocked(api.applyInsightBatch).mockRejectedValueOnce(
        new DesignLoopApiError("failed", {
          status: 409,
          code,
          payload: { detail: { code, sources: ["turn-2:0"] } },
        }),
      );
      const wrapper = mountTray(api);
      await wrapper.get('[data-testid="insight-brief-tray-apply"]').trigger("click");
      await flushPromises();
      expect(wrapper.get('[role="alert"]').text()).toBe(message);
      expect(tray.itemsOf("project-1")).toHaveLength(2);
      expect(
        wrapper.get('[data-testid="insight-brief-tray-details"]').attributes("open"),
      ).toBeDefined();
      const rows = wrapper.findAll('[data-testid="insight-brief-tray-item"]');
      expect(rows.map((row) => row.attributes("data-conflict"))).toEqual(["false", "true"]);
      expect(rows[1]!.get('[data-testid="insight-brief-tray-conflict"]').text()).toBe(mark);
      await expectAccessible(wrapper.element);
      await rows[1]!.get('[data-testid="insight-brief-tray-remove"]').trigger("click");
      await flushPromises();
      expect(wrapper.find('[role="alert"]').exists()).toBe(false);
      wrapper.unmount();
    },
  );

  it("shows the code of any other failure", async () => {
    const tray = useInsightTrayStore();
    tray.add("project-1", item(1));
    const api = fakeApi();
    vi.mocked(api.applyInsightBatch).mockRejectedValueOnce(
      new DesignLoopApiError("failed", {
        status: 409,
        code: "BRIEF_VERSION_NOT_CREATED",
        payload: { detail: { code: "BRIEF_VERSION_NOT_CREATED" } },
      }),
    );
    const wrapper = mountTray(api, "en");
    await wrapper.get('[data-testid="insight-brief-tray-apply"]').trigger("click");
    await flushPromises();
    expect(wrapper.get('[role="alert"]').text()).toBe(
      "The operation failed: BRIEF_VERSION_NOT_CREATED",
    );
    expect(
      wrapper.get('[data-testid="insight-brief-tray-details"]').attributes("open"),
    ).toBeUndefined();
    expect(wrapper.findAll('[data-testid="insight-brief-tray-conflict"]')).toHaveLength(0);
    wrapper.unmount();
  });

  it("disables the actions while the batch is running", async () => {
    const tray = useInsightTrayStore();
    tray.add("project-1", item(1));
    let finish!: () => void;
    const api: InsightBatchApi = {
      applyInsightBatch: vi.fn(
        () =>
          new Promise<InsightBatchApplicationPayload>((resolve) => {
            finish = () =>
              resolve({ applications: [application("turn-1:0")], brief_version_number: 2 });
          }),
      ),
    };
    const wrapper = mountTray(api);
    await wrapper.get('[data-testid="insight-brief-tray-apply"]').trigger("click");
    await flushPromises();
    expect(wrapper.get('[role="status"]').text()).toBe("Porto gli spunti nel brief…");
    for (const testId of ["apply", "clear", "remove"]) {
      expect(
        wrapper.get(`[data-testid="insight-brief-tray-${testId}"]`).attributes("disabled"),
      ).toBeDefined();
    }
    finish();
    await flushPromises();
    expect(wrapper.get('[role="status"]').text()).toBe(
      "Aggiunto al brief 1 spunto, versione 2. Brief, squadra, twin, requisiti e design vanno approvati di nuovo.",
    );
    wrapper.unmount();
  });

  it("sits in the page flow as a dark panel and shows its status line only when there is news", async () => {
    const tray = useInsightTrayStore();
    tray.add("project-1", item(1));
    const wrapper = mountTray();
    const region = wrapper.get('[data-testid="insight-brief-tray"]');
    expect(region.classes()).not.toContain("fixed");
    expect(region.attributes("data-surface")).toBe("night");
    const statusLine = wrapper.get('[data-testid="insight-brief-tray-status"]').element
      .parentElement as HTMLElement;
    expect(statusLine.classList.contains("sr-only")).toBe(true);
    await wrapper.get('[data-testid="insight-brief-tray-apply"]').trigger("click");
    await flushPromises();
    expect(statusLine.classList.contains("sr-only")).toBe(false);
    await wrapper.get('[data-testid="insight-brief-tray-close"]').trigger("click");
    await flushPromises();
    expect(wrapper.find('[data-testid="insight-brief-tray"]').exists()).toBe(false);
    wrapper.unmount();
  });

  it("keeps its actions out of the way on small screens until the list is opened", async () => {
    const tray = useInsightTrayStore();
    tray.add("project-1", item(1));
    const wrapper = mountTray();
    const actions = wrapper.get('[data-testid="insight-brief-tray-actions"]');
    expect(actions.classes()).toContain("max-sm:hidden");
    const details = wrapper.get('[data-testid="insight-brief-tray-details"]');
    (details.element as HTMLDetailsElement).open = true;
    await details.trigger("toggle");
    expect(actions.classes()).not.toContain("max-sm:hidden");
    (details.element as HTMLDetailsElement).open = false;
    await details.trigger("toggle");
    expect(actions.classes()).toContain("max-sm:hidden");
    wrapper.unmount();
  });

  it("forgets the result when the owner leaves the project", async () => {
    const tray = useInsightTrayStore();
    tray.add("project-1", item(1));
    tray.add("project-2", item(1));
    const wrapper = mountTray();
    await wrapper.get('[data-testid="insight-brief-tray-apply"]').trigger("click");
    await flushPromises();
    expect(tray.resultOf("project-1")).not.toBeNull();
    await wrapper.setProps({ projectId: "project-2" });
    expect(tray.resultOf("project-1")).toBeNull();
    expect(wrapper.get('[data-testid="insight-brief-tray-count"]').text()).toBe(
      "1 spunto messo da parte per il brief",
    );
    await wrapper.get('[data-testid="insight-brief-tray-apply"]').trigger("click");
    await flushPromises();
    expect(tray.resultOf("project-2")).not.toBeNull();
    wrapper.unmount();
    expect(tray.resultOf("project-2")).toBeNull();
  });
});
