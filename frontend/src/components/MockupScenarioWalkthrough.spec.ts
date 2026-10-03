import { flushPromises, mount } from "@vue/test-utils";
import { describe, expect, it, vi } from "vitest";
import MockupScenarioWalkthrough from "./MockupScenarioWalkthrough.vue";
import { whyContextKey } from "./whyContext";
import { validationDocument, validationWalkthrough } from "../test/humanValidationFixtures";

function panel() {
  const api = {
    overview: vi.fn(),
    walkthrough: vi.fn(async () => validationWalkthrough()),
    createHypothesis: vi.fn(),
    reviseHypothesis: vi.fn(),
    recordOutcome: vi.fn(),
  };
  const why = { explain: vi.fn(), document: vi.fn(async () => validationDocument()) };
  const wrapper = mount(MockupScenarioWalkthrough, {
    props: {
      alternativeId: "alternative-id",
      documentHash: "rendered-hash",
      screenCodes: ["SCR-001"],
      locale: "it",
      api,
    },
    global: {
      provide: {
        [whyContextKey as symbol]: {
          api: why,
          projectId: () => "project",
          authorize: <T>(operation: (token: string) => Promise<T>) => operation("token"),
        },
      },
    },
  });
  return { wrapper, api, why };
}

describe("Mockup scenario walkthrough", () => {
  it("loads only on request, preserves original task and steps, and exposes missing step anchors", async () => {
    const { wrapper, api, why } = panel();
    expect(why.document).not.toHaveBeenCalled();
    (wrapper.element as HTMLDetailsElement).open = true;
    await wrapper.trigger("toggle");
    await flushPromises();
    expect(api.walkthrough).not.toHaveBeenCalled();
    expect(
      (wrapper.get('[data-testid="walkthrough-scenario"]').element as HTMLSelectElement).value,
    ).toBe("");
    await wrapper.get('[data-testid="walkthrough-scenario"]').setValue("scenario");
    await wrapper.get('[data-testid="walkthrough-open"]').trigger("click");
    await flushPromises();
    expect(api.walkthrough).toHaveBeenCalledWith(
      "project",
      "scenario",
      { alternativeId: "alternative-id", documentHash: "rendered-hash" },
      "token",
    );
    expect(wrapper.get('[data-testid="walkthrough-task"]').text()).toBe("Calcolare 2 + 2");
    expect(wrapper.get('[data-testid="walkthrough-step"]').text()).toContain("1. Inserire 2 + 2");
    expect(wrapper.get('[data-testid="walkthrough-step"]').text()).toContain(
      "Manca il collegamento attestato fra questo passo e un elemento",
    );
    expect(wrapper.get('[data-testid="walkthrough-step"]').text()).not.toContain("Equals button");
    expect(wrapper.get('[data-testid="walkthrough-anchor-candidates"]').text()).toContain(
      "candidati per lo scenario",
    );
    expect(wrapper.get('[data-testid="walkthrough-expected"]').text()).toBe("Il risultato è 4");
    await wrapper.findAll('[data-testid="walkthrough-step-button"]')[1]?.trigger("click");
    expect(wrapper.get('[data-testid="walkthrough-step"]').text()).toContain(
      "2. Leggere il risultato",
    );
    expect(api.createHypothesis).not.toHaveBeenCalled();
    expect(api.recordOutcome).not.toHaveBeenCalled();
  });

  it("uses existing screen navigation and refreshes anchors for the new document while retaining the selected step", async () => {
    const { wrapper, api } = panel();
    (wrapper.element as HTMLDetailsElement).open = true;
    await wrapper.trigger("toggle");
    await flushPromises();
    await wrapper.get('[data-testid="walkthrough-scenario"]').setValue("scenario");
    await wrapper.get('[data-testid="walkthrough-open"]').trigger("click");
    await flushPromises();
    await wrapper.get('[data-testid="walkthrough-show-screen"]').trigger("click");
    expect(wrapper.emitted("screen")).toEqual([["SCR-001"]]);
    expect(wrapper.find("iframe").exists()).toBe(false);
    await wrapper.findAll('[data-testid="walkthrough-step-button"]')[1]?.trigger("click");
    api.walkthrough.mockResolvedValueOnce(
      validationWalkthrough({ anchor_candidates: [], gaps: [{ code: "MISSING_MOCKUP_ANCHOR" }] }),
    );
    await wrapper.setProps({ documentHash: "new-rendering" });
    await flushPromises();
    expect(wrapper.get('[data-testid="walkthrough-step"]').text()).toContain(
      "2. Leggere il risultato",
    );
    expect(wrapper.find('[data-testid="walkthrough-anchor"]').exists()).toBe(false);
    expect(api.walkthrough).toHaveBeenLastCalledWith(
      "project",
      "scenario",
      { alternativeId: "alternative-id", documentHash: "new-rendering" },
      "token",
    );
    expect(api.walkthrough).toHaveBeenCalledTimes(2);
    await wrapper.setProps({ locale: "en" });
    expect(wrapper.text()).toContain("Scenario walkthrough");
  });
});
