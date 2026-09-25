import { createPinia, setActivePinia } from "pinia";
import { flushPromises, mount } from "@vue/test-utils";
import { beforeEach, describe, expect, it, vi } from "vitest";

import type { DesignLoopApi } from "@/api/designLoop";
import { DesignLoopApiError } from "@/api/designLoop";
import type { InsightApplicationPayload } from "@/types/designLoop";
import InsightApplyMenu from "./InsightApplyMenu.vue";

const authorize = <T>(operation: (accessToken: string) => Promise<T>) => operation("token");

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
  };
}

describe("InsightApplyMenu", () => {
  beforeEach(() => {
    setActivePinia(createPinia());
  });

  it("applies the insight to the requirements and reports the created code", async () => {
    const api = fakeApi();
    const wrapper = mount(InsightApplyMenu, {
      props: {
        projectId: "project-1",
        source: {
          kind: "SYNTHETIC_FINDING",
          id: "run:1:UTF-001",
          twinId: "twin-1",
          text: "Show the date format.",
          mitigation: "Add a hint.",
        },
        locale: "it",
        authorize,
        api,
      },
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

  it("sends the chosen brief field and explains duplicates", async () => {
    const api = fakeApi();
    vi.mocked(api.applyInsight).mockRejectedValueOnce(
      new DesignLoopApiError("failed", {
        status: 409,
        code: "INSIGHT_ALREADY_APPLIED",
        payload: null,
      }),
    );
    const wrapper = mount(InsightApplyMenu, {
      props: {
        projectId: "project-1",
        source: { kind: "TWIN_CHAT_INSIGHT", id: "turn-1:0", text: "Fast check-in." },
        authorize,
        api,
      },
    });
    await wrapper.get('[data-testid="insight-brief-field"]').setValue("goals");
    await wrapper.get('[data-testid="insight-apply-brief"]').trigger("click");
    await flushPromises();
    expect(wrapper.get('[role="alert"]').text()).toBe("This insight is already in the project.");
    await wrapper.get('[data-testid="insight-apply-brief"]').trigger("click");
    await flushPromises();
    expect(vi.mocked(api.applyInsight).mock.calls[1]?.[1]).toMatchObject({
      target: "BRIEF",
      brief_field: "goals",
      source_twin_id: null,
    });
    expect(wrapper.get('[data-testid="insight-applied"]').text()).toBe(
      "Added to the brief (Goals, version 3).",
    );
  });
});
