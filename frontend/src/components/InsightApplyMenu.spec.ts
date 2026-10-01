import { createPinia, setActivePinia } from "pinia";
import { flushPromises, mount } from "@vue/test-utils";
import { computed } from "vue";
import { beforeEach, describe, expect, it, vi } from "vitest";

import type { DesignLoopApi } from "@/api/designLoop";
import { DesignLoopApiError } from "@/api/designLoop";
import { MAX_TRAY_ITEMS, useInsightTrayStore } from "@/stores/insightTray";
import { expectAccessible } from "@/test/axe";
import type { InsightApplicationPayload, InsightSource } from "@/types/designLoop";
import InsightApplyMenu from "./InsightApplyMenu.vue";
import { surfaceKey } from "./UiSurface.vue";

const authorize = <T>(operation: (accessToken: string) => Promise<T>) => operation("token");

const OLD_STEP_NAMES =
  /passo Squadra|Team step|passo Requisiti|Requirements step|passo Pacchetto|Package step|\bPacchetto\b/;

const TEAM_WORDS =
  /\b(?:squadr[ae]|teams?|agent[ei]|agents?|assistent[ei]|assistants?|specialist[ai]|specialists?|ruol[oi]|roles?|membr[oi]|members?)\b/i;

function application(
  overrides: Partial<InsightApplicationPayload> = {},
): InsightApplicationPayload {
  return {
    id: "application-1",
    project_id: "project-1",
    owner_user_id: "owner-1",
    source_kind: "SYNTHETIC_FINDING",
    source_id: "run:1:UTF-001",
    source_twin_id: "twin-1",
    text: "Show the date format.",
    target: "REQUIREMENTS",
    target_field: null,
    target_version_id: "version-3",
    target_version_number: 3,
    target_code: "REQ-004",
    created_at: "2026-09-25T20:00:00Z",
    content_hash: "c".repeat(64),
    ...overrides,
  };
}

function fakeApi(): DesignLoopApi {
  return {
    evaluate: vi.fn(),
    runs: vi.fn(async () => []),
    comparison: vi.fn(async () => null),
    regenerate: vi.fn(),
    applyInsight: vi.fn(async (_project, body) =>
      application({ target: body.target, target_field: body.brief_field ?? null }),
    ),
    applications: vi.fn(async () => []),
    validations: vi.fn(async () => []),
    validate: vi.fn(),
    discussions: vi.fn(async () => []),
    startDiscussion: vi.fn(),
    nextDiscussionRound: vi.fn(),
    decideDiscussion: vi.fn(),
  };
}

const CHAT_SOURCE: InsightSource = {
  kind: "TWIN_CHAT_INSIGHT",
  id: "turn-1:0",
  twinId: "twin-1",
  text: "Fast check-in.",
};

function mountMenu(
  api: DesignLoopApi,
  source: InsightSource = CHAT_SOURCE,
  locale: "en" | "it" = "it",
) {
  return mount(InsightApplyMenu, {
    props: { projectId: "project-1", source, locale, authorize, api },
  });
}

describe("InsightApplyMenu", () => {
  beforeEach(() => {
    setActivePinia(createPinia());
  });

  it("offers the design first, then the requirements and the brief last", () => {
    const wrapper = mountMenu(fakeApi());
    const actions = wrapper
      .findAll("button")
      .map((button) => [button.attributes("data-testid"), button.text()]);
    expect(actions).toEqual([
      ["insight-apply-design", "Nel design"],
      ["insight-apply-requirements", "Nei requisiti"],
      ["insight-apply-brief", "Metti da parte per il brief"],
    ]);
    expect(wrapper.get('[data-testid="insight-apply-design"]').classes()).toContain("bg-action");
    expect(wrapper.get('[data-testid="insight-apply-requirements"]').classes()).not.toContain(
      "bg-action",
    );
    const note = wrapper.get('[data-testid="insight-brief-note"]');
    expect(note.text()).toBe(
      "Nel brief cambia il punto di partenza: brief, prospettive, twin, requisiti e design andranno approvati di nuovo.",
    );
    expect(wrapper.get('[data-testid="insight-apply-brief"]').attributes("aria-describedby")).toBe(
      note.attributes("id"),
    );
  });

  it.each([
    [
      "it",
      "Nel brief cambia il punto di partenza: brief, prospettive, twin, requisiti e design andranno approvati di nuovo.",
    ],
    [
      "en",
      "In the brief it changes the starting point: brief, perspectives, twins, requirements and design will need approval again.",
    ],
  ] as const)("names no step by its old name and speaks of no team in %s", async (locale, note) => {
    const wrapper = mountMenu(fakeApi(), CHAT_SOURCE, locale);
    await wrapper.get('[data-testid="insight-apply-requirements"]').trigger("click");
    await flushPromises();
    expect(wrapper.get('[data-testid="insight-brief-note"]').text()).toBe(note);
    expect(wrapper.text()).not.toMatch(OLD_STEP_NAMES);
    expect(wrapper.text()).not.toMatch(TEAM_WORDS);
  });

  it("applies the insight to the requirements and reports the created code", async () => {
    const api = fakeApi();
    const wrapper = mountMenu(api, {
      kind: "SYNTHETIC_FINDING",
      id: "run:1:UTF-001",
      twinId: "twin-1",
      text: "Show the date format.",
      mitigation: "Add a hint.",
    });
    await wrapper.get('[data-testid="insight-apply-requirements"]').trigger("click");
    await flushPromises();
    expect(vi.mocked(api.applyInsight).mock.calls[0]?.[1]).toEqual({
      source_kind: "SYNTHETIC_FINDING",
      source_id: "run:1:UTF-001",
      source_twin_id: "twin-1",
      text: "Show the date format.",
      target: "REQUIREMENTS",
      brief_field: null,
      mitigation: "Add a hint.",
    });
    expect(wrapper.get('[data-testid="insight-applied"]').text()).toBe(
      "Aggiunto ai requisiti come REQ-004 (versione 3).",
    );
    expect(wrapper.emitted("applied")).toHaveLength(1);
  });

  it("sets the insight aside for the brief with the chosen field and applies nothing", async () => {
    const api = fakeApi();
    const wrapper = mountMenu(api, CHAT_SOURCE, "en");
    await wrapper.get('[data-testid="insight-brief-field"]').setValue("goals");
    await wrapper.get('[data-testid="insight-apply-brief"]').trigger("click");
    await flushPromises();
    expect(api.applyInsight).not.toHaveBeenCalled();
    expect(wrapper.emitted("applied")).toBeUndefined();
    expect(wrapper.find('[data-testid="insight-applied"]').exists()).toBe(false);
    expect(useInsightTrayStore().itemsOf("project-1")).toEqual([
      {
        sourceKind: "TWIN_CHAT_INSIGHT",
        sourceId: "turn-1:0",
        sourceTwinId: "twin-1",
        text: "Fast check-in.",
        briefField: "goals",
      },
    ]);
    const brief = wrapper.get('[data-testid="insight-apply-brief"]');
    expect(brief.attributes("disabled")).toBeDefined();
    expect(brief.text()).toBe("Set aside for the brief");
    expect(wrapper.get('[data-testid="insight-brief-field"]').attributes("disabled")).toBeDefined();
    await brief.trigger("click");
    expect(useInsightTrayStore().itemsOf("project-1")).toHaveLength(1);
    expect(
      wrapper.get('[data-testid="insight-apply-design"]').attributes("disabled"),
    ).toBeUndefined();
  });

  it("shows an insight already set aside as disabled with its field until the tray is emptied", async () => {
    const tray = useInsightTrayStore();
    tray.add("project-1", {
      sourceKind: "TWIN_CHAT_INSIGHT",
      sourceId: "turn-1:0",
      sourceTwinId: "twin-1",
      text: "Fast check-in.",
      briefField: "risks",
    });
    const wrapper = mountMenu(fakeApi());
    const brief = wrapper.get('[data-testid="insight-apply-brief"]');
    expect(brief.attributes("disabled")).toBeDefined();
    expect(brief.text()).toBe("Messo da parte per il brief");
    expect(
      (wrapper.get('[data-testid="insight-brief-field"]').element as HTMLSelectElement).value,
    ).toBe("risks");
    tray.clear("project-1");
    await flushPromises();
    expect(brief.attributes("disabled")).toBeUndefined();
    expect(brief.text()).toBe("Metti da parte per il brief");
  });

  it("stops setting insights aside when the tray is full", async () => {
    const tray = useInsightTrayStore();
    for (let index = 0; index < MAX_TRAY_ITEMS; index += 1) {
      tray.add("project-1", {
        sourceKind: "TWIN_CHAT_INSIGHT",
        sourceId: `turn-${index + 10}:0`,
        sourceTwinId: null,
        text: `Insight ${index}.`,
        briefField: "goals",
      });
    }
    const wrapper = mountMenu(fakeApi());
    expect(wrapper.get('[data-testid="insight-apply-brief"]').attributes("disabled")).toBeDefined();
    expect(wrapper.get('[data-testid="insight-brief-full"]').text()).toBe(
      "Hai già messo da parte 20 spunti, il massimo per una versione del brief.",
    );
    tray.remove("project-1", "TWIN_CHAT_INSIGHT", "turn-10:0");
    await flushPromises();
    expect(wrapper.find('[data-testid="insight-brief-full"]').exists()).toBe(false);
    expect(
      wrapper.get('[data-testid="insight-apply-brief"]').attributes("disabled"),
    ).toBeUndefined();
  });

  it("explains a duplicate brought into the requirements", async () => {
    const api = fakeApi();
    vi.mocked(api.applyInsight).mockRejectedValueOnce(
      new DesignLoopApiError("failed", {
        status: 409,
        code: "INSIGHT_ALREADY_APPLIED",
        payload: null,
      }),
    );
    const wrapper = mountMenu(api, CHAT_SOURCE, "en");
    await wrapper.get('[data-testid="insight-apply-requirements"]').trigger("click");
    await flushPromises();
    expect(wrapper.get('[role="alert"]').text()).toBe("This insight is already in the project.");
    expect(wrapper.emitted("applied")).toBeUndefined();
  });

  it("applies a discussion proposal and explains a finding set aside by the owner", async () => {
    const api = fakeApi();
    const wrapper = mountMenu(api, {
      kind: "TWIN_DISCUSSION",
      id: "discussion:discussion-1:1:PRP-001",
      twinId: null,
      text: "Show the booking total before confirming.",
    });
    await wrapper.get('[data-testid="insight-apply-design"]').trigger("click");
    await flushPromises();
    expect(vi.mocked(api.applyInsight).mock.calls[0]?.[1]).toEqual({
      source_kind: "TWIN_DISCUSSION",
      source_id: "discussion:discussion-1:1:PRP-001",
      source_twin_id: null,
      text: "Show the booking total before confirming.",
      target: "DESIGN",
      brief_field: null,
      mitigation: null,
    });
    expect(wrapper.emitted("applied")).toHaveLength(1);
    vi.mocked(api.applyInsight).mockRejectedValueOnce(
      new DesignLoopApiError("failed", {
        status: 409,
        code: "INSIGHT_SOURCE_DISMISSED",
        payload: null,
      }),
    );
    await wrapper.get('[data-testid="insight-apply-requirements"]').trigger("click");
    await flushPromises();
    expect(wrapper.get('[role="alert"]').text()).toBe(
      "Hai segnato questa osservazione come non pertinente, quindi non viene portata nel progetto.",
    );
  });

  it("follows the dark surface it sits on, with the same actions and identifiers", async () => {
    const api = fakeApi();
    const wrapper = mount(InsightApplyMenu, {
      props: { projectId: "project-1", source: CHAT_SOURCE, locale: "it", authorize, api },
      global: { provide: { [surfaceKey as symbol]: computed(() => "night") } },
    });
    const menu = wrapper.get('[data-testid="insight-apply-menu"]');
    expect(menu.attributes("data-surface-context")).toBe("night");
    const design = wrapper.get('[data-testid="insight-apply-design"]');
    expect(design.classes()).toEqual(expect.arrayContaining(["bg-on-night", "text-ink"]));
    expect(design.classes()).not.toContain("bg-action");
    expect(wrapper.get('[data-testid="insight-apply-requirements"]').classes()).toContain(
      "border-night-line-strong",
    );
    expect(wrapper.get('[data-testid="insight-brief-field"]').classes()).toContain(
      "bg-night-panel",
    );
    expect(wrapper.html()).not.toMatch(/bg-white|text-ink-2/);
    await design.trigger("click");
    await flushPromises();
    expect(vi.mocked(api.applyInsight).mock.calls[0]?.[1]).toMatchObject({ target: "DESIGN" });
    expect(wrapper.get('[data-testid="insight-applied"]').classes()).toContain(
      "text-petrol-on-night-2",
    );
    await expectAccessible(wrapper.element);
  });
});
