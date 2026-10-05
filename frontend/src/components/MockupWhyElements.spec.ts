import { flushPromises, mount } from "@vue/test-utils";
import { describe, expect, it, vi } from "vitest";
import { whyDocument, whyNode } from "../test/whyFixtures";
import MockupWhyElements from "./MockupWhyElements.vue";
import { whyContextKey } from "./whyContext";

describe("Studio mockup element controls", () => {
  it("selects only elements of the exact rendered document, alternative and active screen", async () => {
    const element = (key: string, alternative: string, hash: string, screen: string) =>
      whyNode({
        key,
        code: "ELM-001",
        kind: "PROTOTYPE_ELEMENT",
        title: key,
        declared_context: {
          perspectives: [],
          mockup: {
            alternative_id: alternative,
            prototype_id: "prototype",
            source: "LATEST",
            screen_code: screen,
            document_hashes: { [screen]: hash },
          },
        },
      });
    const exact = element("Exact keypad", "alt", "rendered", "SCR-001");
    const anotherScreen = element("Result", "alt", "rendered", "SCR-002");
    const api = {
      explain: vi.fn(),
      document: vi
        .fn()
        .mockResolvedValue(
          whyDocument([
            exact,
            anotherScreen,
            element("Other alternative", "other", "rendered", "SCR-001"),
            element("Old rendering", "alt", "old", "SCR-001"),
          ]),
        ),
    };
    const wrapper = mount(MockupWhyElements, {
      props: {
        alternativeId: "alt",
        documentHash: "rendered",
        screenCode: "SCR-001",
        locale: "en",
      },
      global: {
        provide: {
          [whyContextKey as symbol]: {
            api,
            projectId: () => "project",
            authorize: <T>(request: (token: string) => Promise<T>) => request("token"),
          },
        },
      },
    });
    expect(api.document).not.toHaveBeenCalled();
    (wrapper.element as HTMLDetailsElement).open = true;
    await wrapper.trigger("toggle");
    await flushPromises();
    expect(wrapper.findAll('[data-testid="mockup-why-element"]')).toHaveLength(1);
    expect(wrapper.text()).toContain(exact.title);
    expect(wrapper.text()).not.toContain("Other alternative");
    expect(wrapper.text()).not.toContain("Old rendering");
    expect(api.explain).not.toHaveBeenCalled();
    await wrapper.setProps({ screenCode: "SCR-002" });
    expect(wrapper.text()).toContain("Result");
    expect(wrapper.text()).not.toContain(exact.title);
    expect(api.document).toHaveBeenCalledTimes(1);
    await wrapper.setProps({ documentHash: "unknown" });
    await flushPromises();
    expect(wrapper.get('[data-testid="mockup-why-missing"]').text()).toBe(
      "Data for this link is missing",
    );
  });
});
