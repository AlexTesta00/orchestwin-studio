import { flushPromises, mount } from "@vue/test-utils";
import { describe, expect, it, vi } from "vitest";

import { whyAnswer, whyDocument, whyNode } from "@/test/whyFixtures";
import { suppliedPrototype } from "@/test/workflowInputsFixtures";
import type { WorkflowDecision } from "@/types/workflowInputs";
import ArtifactWhy from "./ArtifactWhy.vue";
import ArtifactWhyNode from "./ArtifactWhyNode.vue";
import { whyContextKey } from "./whyContext";
import { whyGapLabel, whyNodeTitle } from "./whyCopy";

describe("owner records in Why in sprint 36", () => {
  it.each(["it", "en"] as const)(
    "shows the %s evaluation limit and declared origin without empirical support",
    async (locale) => {
      const prototype = suppliedPrototype();
      const target = whyNode({
        key: "PROVIDED_PROTOTYPE:provided:1:hash",
        code: prototype.code,
        title: prototype.title,
        kind: "PROVIDED_PROTOTYPE",
        declared_context: {
          perspectives: [],
          provided_prototype: prototype,
          origin: "OWNER_INPUT",
          limits: [
            "PROVIDED_PROTOTYPE_REVIEW_UNAVAILABLE",
            "PROVIDED_PROTOTYPE_CODE_UNAVAILABLE",
            "PROVIDED_PROTOTYPE_WALKTHROUGH_UNAVAILABLE",
            "PROVIDED_PROTOTYPE_OPERATION_UNAVAILABLE",
            "PROVIDED_PROTOTYPE_EVALUATION_UNAVAILABLE",
          ],
        },
        gaps: [
          "PROVIDED_PROTOTYPE_REVIEW_UNAVAILABLE",
          "PROVIDED_PROTOTYPE_CODE_UNAVAILABLE",
          "PROVIDED_PROTOTYPE_WALKTHROUGH_UNAVAILABLE",
          "PROVIDED_PROTOTYPE_OPERATION_UNAVAILABLE",
          "PROVIDED_PROTOTYPE_EVALUATION_UNAVAILABLE",
        ].map((code) => ({
          code,
          node_key: "provided",
          related_code: prototype.code,
          stage: "design",
        })),
      });
      const original = structuredClone(target);
      const api = {
        explain: vi.fn().mockResolvedValue(whyAnswer(target)),
        document: vi.fn().mockResolvedValue(whyDocument([target])),
      };
      const wrapper = mount(ArtifactWhy, {
        props: { code: prototype.code, locale },
        global: {
          provide: {
            [whyContextKey as symbol]: {
              projectId: () => "project",
              api,
              authorize: <T>(request: (token: string) => Promise<T>) => request("token"),
            },
          },
        },
      });
      (wrapper.element as HTMLDetailsElement).open = true;
      await wrapper.trigger("toggle");
      await flushPromises();
      const limit =
        locale === "it"
          ? "La valutazione dei twin sul prototipo fornito non è disponibile nello sprint 36."
          : "Twin evaluation of the supplied prototype is unavailable in sprint 36.";
      expect(wrapper.get('[data-testid="why-provided-evaluation-limit"]').text()).toBe(limit);
      expect(wrapper.get('[data-testid="why-provided-prototype-summary"]').text()).toContain(
        "Penpot",
      );
      const detail = mount(ArtifactWhyNode, { props: { node: target, locale } });
      expect(detail.get('[data-testid="why-provided-evaluation-limit"]').text()).toBe(limit);
      for (const code of target.declared_context.limits ?? [])
        expect(detail.text()).toContain(whyGapLabel(code, locale));
      expect(api.explain).toHaveBeenCalledTimes(1);
      expect(target).toEqual(original);
      detail.unmount();
      wrapper.unmount();
    },
  );

  it.each(["DECLARE_MISSING", "RESOLVE_MISSING"] as const)(
    "preserves the owner reason for %s without changing the record",
    (action) => {
      const decision: WorkflowDecision = {
        id: "decision",
        project_id: "project",
        sequence: 1,
        target: "EVIDENCE",
        action,
        reason: "Real research has not been carried out.",
        base_context: {},
        recorded_at: "2026-10-03T00:00:00Z",
        content_hash: "b".repeat(64),
      };
      const target = whyNode({
        kind: "WORKFLOW_DECISION",
        code: "GAP-001",
        title: decision.reason,
        declared_context: { perspectives: [], workflow_decision: decision, origin: "OWNER_INPUT" },
        rationale: {
          origin: "OWNER",
          text: decision.reason,
          version_number: 1,
          content_hash: decision.content_hash,
        },
      });
      const wrapper = mount(ArtifactWhyNode, { props: { node: target, locale: "en" } });
      expect(wrapper.get('[data-testid="why-declared-decision"]').text()).toContain(
        action === "DECLARE_MISSING" ? "Declared gap" : "Resolved gap",
      );
      expect(wrapper.text()).toContain(decision.reason);
      expect(wrapper.get('[data-testid="why-rationale"]').text()).toContain("Owner rationale");
      expect(whyNodeTitle(target, "it")).toContain(
        action === "DECLARE_MISSING" ? "Lacuna dichiarata" : "Lacuna risolta",
      );
      expect(decision.action).toBe(action);
    },
  );
});
