import { mount } from "@vue/test-utils";
import { describe, expect, it } from "vitest";
import { expectAccessible } from "@/test/axe";
import type { ReadableClaim, UserTwinVersionPayload } from "../types/userModeling";
import TwinPersonaView from "./TwinPersonaView.vue";

const unknown: ReadableClaim = {
  observation_key: "user_twin.represents",
  value: { kind: "UNKNOWN", text: null, items: [], reason: null },
  display_status: "UNKNOWN",
  rationale: null,
  provenance: [],
};
const description: ReadableClaim = {
  ...unknown,
  observation_key: "user_twin.description",
  value: { kind: "TEXT", text: "Checks in hotel guests", items: [], reason: null },
  display_status: "CONTESTED",
  rationale: "The role needs confirmation",
  provenance: [
    {
      source_kind: "OWNER_INPUT",
      source_id: "owner",
      source_version: null,
      content_hash: null,
      locator: null,
      summary: "Owner description",
    },
  ],
};
const reference = { artifact_id: "artifact", version_number: 1, content_hash: "hash" };
const twin: UserTwinVersionPayload = {
  id: "version",
  project_id: "project",
  twin_id: "twin",
  version_number: 2,
  based_on_version_number: 1,
  content_hash: "hash",
  created_by_user_id: "owner",
  created_at: "2026-10-01",
  profile: {
    name: "Receptionist",
    persona_reference: {
      persona_id: "persona",
      version_number: 1,
      content_hash: "hash",
      source: "OWNER_PROVIDED",
      kind: "PERSONA",
      confirmation_status: "CONFIRMED",
    },
    project_brief_reference: reference,
    agent_team_reference: reference,
    catalog_version: 1,
    catalog_content_hash: "hash",
    validation_status: "OWNER_APPROVED_UT",
    observations: [],
  },
  view: {
    basis: "PROVISIONAL",
    represents: unknown,
    does_not_represent: unknown,
    contexts: unknown,
    evidence_gaps: unknown,
    empirically_supported_fields: [],
    unsupported_fields: ["user_twin.description"],
    persona: {
      description,
      goals: unknown,
      needs: unknown,
      behaviours: unknown,
      pain_points: unknown,
      constraints: unknown,
      contexts: unknown,
    },
  },
};
describe("TwinPersonaView", () => {
  it("shows the basis and summary while the Persona and Why details stay closed", async () => {
    const wrapper = mount(TwinPersonaView, { props: { twin } });
    expect(wrapper.get('[data-testid="twin-representation-twin"]').text()).toContain("Provisional");
    expect(wrapper.text()).toContain("Checks in hotel guests");
    expect(wrapper.text()).toContain(
      "The brief and the owner's choices are not evidence about real users.",
    );
    const persona = wrapper.get('[data-testid="twin-persona-twin"]');
    expect(persona.attributes("open")).toBeUndefined();
    const why = wrapper.get('[data-testid="persona-why-twin-description"]');
    expect(why.attributes("open")).toBeUndefined();
    expect(why.get("summary").text()).toContain("Why? Description");
    await why.get("summary").trigger("click");
    expect((why.element as HTMLDetailsElement).open).toBe(true);
    expect(why.text()).toContain("Contested");
    expect(why.text()).toContain("The role needs confirmation");
    expect(why.text()).toContain("Owner description");
    expect(wrapper.find('[role="progressbar"]').exists()).toBe(false);
    await expectAccessible(wrapper.element);
  });
  it("uses the server basis and preserves unknown gaps in Italian", () => {
    const wrapper = mount(TwinPersonaView, {
      props: { twin: { ...twin, view: { ...twin.view!, basis: "EVIDENCE_BASED" } }, locale: "it" },
    });
    expect(wrapper.text()).toContain("Fondato su evidenze");
    expect(wrapper.text()).toContain("Non rappresenta");
    expect(wrapper.text()).toContain("Sconosciuto");
    expect(wrapper.get('[data-testid="persona-why-twin-description"] summary').text()).toContain(
      "Perché? Descrizione",
    );
  });
});
