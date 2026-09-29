import { mount } from "@vue/test-utils";
import { h } from "vue";
import { describe, expect, it } from "vitest";

import { expectAccessible } from "@/test/axe";
import type { ProfileObservationPayload } from "@/types/userModeling";
import UiSurface from "./UiSurface.vue";
import UserModelingProvenanceInspector from "./UserModelingProvenanceInspector.vue";

const observation: ProfileObservationPayload = {
  observation_key: "user_twin.goals",
  value: { kind: "ITEMS", text: null, items: ["Reduce booking errors"], reason: null },
  epistemic_status: "MODEL_INFERRED",
  confidence: 0.42,
  provenance: [
    {
      source_kind: "PROJECT_BRIEF",
      source_id: "brief-version",
      source_version: 1,
      content_hash: "b".repeat(64),
      locator: "target_users[0]",
      summary: "Project target user",
    },
  ],
  human_validation: "REQUIRED",
  rationale: "The brief does not directly state this goal.",
};

describe("UserModelingProvenanceInspector", () => {
  it("stays closed and lists every source with its version, place, hash and the rationale", async () => {
    const wrapper = mount(UserModelingProvenanceInspector, { props: { observation } });

    const details = wrapper.get('[data-testid="provenance-inspector"]');
    expect(details.attributes("open")).toBeUndefined();
    expect(details.get("summary").text()).toBe("Provenance (1)");
    expect(wrapper.text()).toContain("PROJECT_BRIEF");
    expect(wrapper.text()).toContain("Project target user");
    expect(wrapper.text()).toContain("target_users[0]");
    expect(wrapper.text()).toContain("b".repeat(64));
    expect(wrapper.text()).toContain("The brief does not directly state this goal.");
    await expectAccessible(wrapper.element);
  });

  it("says in Italian when an observation has no source", () => {
    const wrapper = mount(UserModelingProvenanceInspector, {
      props: { observation: { ...observation, provenance: [], rationale: null }, locale: "it" },
    });

    expect(wrapper.get("summary").text()).toBe("Provenienza (0)");
    expect(wrapper.text()).toContain("Nessun riferimento di evidenza.");
  });

  it("uses the colours of a dark surface inside a dark surface", () => {
    const wrapper = mount(UiSurface, {
      slots: { default: () => h(UserModelingProvenanceInspector, { observation }) },
    });

    const details = wrapper.get('[data-testid="provenance-inspector"]');
    expect(details.attributes("data-surface-context")).toBe("night");
    expect(details.classes()).toEqual(
      expect.arrayContaining(["border-night-line", "bg-night-raised"]),
    );
  });
});
