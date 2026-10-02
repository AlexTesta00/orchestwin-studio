import { createPinia, setActivePinia } from "pinia";
import { mount } from "@vue/test-utils";
import { h } from "vue";
import { describe, expect, it } from "vitest";

import { AGENT_IDENTIFIERS } from "@/api/team-contracts";
import { useUserModelingStore } from "@/stores/userModeling";
import type { PersonaVersionPayload, UserTwinVersionPayload } from "@/types/userModeling";
import TwinIdentity from "./TwinIdentity.vue";
import UiSurface from "./UiSurface.vue";
import {
  TWIN_AVATARS,
  roleAvatar,
  roleSteps,
  twinAvatar,
  twinIdentity,
  twinPeers,
} from "./twinIdentity";

const TEAM_IMAGES = /^\/team\/(a11y|an|ar|copy|fe|qa|ur|ux)\.webp$/u;

const OLD_STEP_NAMES =
  /passo Squadra|Team step|passo Requisiti|Requirements step|passo Pacchetto|Package step|\bPacchetto\b/;

const TEAM_WORDS =
  /\b(?:squadr[ae]|teams?|agent[ei]|agents?|assistent[ei]|assistants?|specialist[ai]|specialists?|ruol[oi]|roles?|membr[oi]|members?)\b/i;

function persona(personaId: string): PersonaVersionPayload {
  return {
    id: `${personaId}-version`,
    project_id: "project",
    persona_id: personaId,
    version_number: 1,
    based_on_version_number: null,
    content_hash: "a".repeat(64),
    created_by_user_id: "owner",
    created_at: "2026-09-28T10:00:00Z",
    profile: {
      name: personaId,
      source: "SYSTEM_PROPOSED",
      kind: "PROTO_PERSONA",
      confirmation_status: "CONFIRMED",
      rejection_reason: null,
      observations: [],
    },
  };
}

function twin(twinId: string, personaId: string): UserTwinVersionPayload {
  return {
    id: `${twinId}-version`,
    twin_id: twinId,
    profile: { name: twinId, persona_reference: { persona_id: personaId }, observations: [] },
  } as unknown as UserTwinVersionPayload;
}

describe("TwinIdentity", () => {
  it("gives every catalog role a localized explanation and a robot of the team", () => {
    for (const role of AGENT_IDENTIFIERS) {
      const italian = twinIdentity(role, "", "it");
      const english = twinIdentity(role, "", "en");
      expect(italian.name).not.toBe(role);
      expect(italian.description.length).toBeGreaterThan(20);
      expect(english.description).not.toBe(italian.description);
      expect(italian.avatar).toBe(english.avatar);
      expect(italian.avatar).toMatch(TEAM_IMAGES);
      expect(italian.isUser).toBe(false);
    }
  });

  it("maps every role of the catalog to one of the eight robots and to the steps it works in", () => {
    expect(Object.fromEntries(AGENT_IDENTIFIERS.map((role) => [role, roleAvatar(role)]))).toEqual({
      WORKFLOW_ORCHESTRATOR: "/team/an.webp",
      INTAKE_CLARIFICATION_AGENT: "/team/copy.webp",
      TEAM_SELECTOR: "/team/ur.webp",
      HUMAN_GATE_CONTROLLER: "/team/an.webp",
      ARTIFACT_MANAGER: "/team/copy.webp",
      SANDBOX_CONTROLLER: "/team/qa.webp",
      REQUIREMENTS_ANALYST: "/team/an.webp",
      UX_RESEARCHER_USER_MODELER: "/team/ur.webp",
      UX_UI_DESIGNER: "/team/ux.webp",
      SOFTWARE_ARCHITECT: "/team/ar.webp",
      FRONTEND_ENGINEER: "/team/fe.webp",
      BACKEND_ENGINEER: "/team/fe.webp",
      MOBILE_ENGINEER: "/team/fe.webp",
      QA_TEST_ENGINEER: "/team/qa.webp",
      SECURITY_REVIEWER: "/team/qa.webp",
      ACCESSIBILITY_REVIEWER: "/team/a11y.webp",
      INTEGRATION_ENGINEER: "/team/ar.webp",
    });
    expect(roleSteps("REQUIREMENTS_ANALYST")).toEqual([4]);
    expect(roleSteps("UX_RESEARCHER_USER_MODELER")).toEqual([3, 5]);
    expect(roleSteps("UX_UI_DESIGNER")).toEqual([5]);
    expect(roleSteps("__proto__")).toEqual([]);
  });

  it("names no step by its old name and speaks of no team for step 2, in both languages", () => {
    const stepTwo = AGENT_IDENTIFIERS.filter((role) => roleSteps(role).includes(2));
    expect(stepTwo).toContain("TEAM_SELECTOR");
    for (const locale of ["it", "en"] as const) {
      const texts = [
        ...stepTwo.flatMap((role) => {
          const identity = twinIdentity(role, "", locale);
          return [identity.name, identity.description];
        }),
        twinIdentity(undefined, "persona", locale).description,
        twinIdentity("UNKNOWN_ROLE", "", locale).description,
      ];
      expect(texts.filter((text) => OLD_STEP_NAMES.test(text))).toEqual([]);
      expect(texts.filter((text) => TEAM_WORDS.test(text))).toEqual([]);
    }
    expect(twinIdentity("TEAM_SELECTOR", "", "it").name).toBe("Organizzatore delle prospettive");
    expect(twinIdentity("TEAM_SELECTOR", "", "en").name).toBe("Perspectives planner");
    expect(twinIdentity(undefined, "persona", "en").description).toBe(
      "Represents a point of view of your product's users.",
    );
  });

  it("keeps a visible name beside a decorative robot", () => {
    const wrapper = mount(TwinIdentity, { props: { role: "UX_UI_DESIGNER", locale: "it" } });
    expect(wrapper.text()).toContain("Designer UX/UI");
    expect(wrapper.text()).toContain("Propone le alternative di design");
    const image = wrapper.get("img");
    expect(image.attributes("alt")).toBe("");
    expect(image.attributes("src")).toBe("/team/ux.webp");
  });

  it("keeps the user's identity stable across profile revisions and locales", () => {
    const italian = twinIdentity(undefined, "same-persona-id", "it");
    const english = twinIdentity(undefined, "same-persona-id", "en");
    expect(italian.avatar).toBe(english.avatar);
    const wrapper = mount(TwinIdentity, {
      props: { identityKey: "same-persona-id", name: "Alex Testa", locale: "it" },
    });
    expect(wrapper.text()).toContain("Alex Testa");
    expect(wrapper.text()).toContain("punto di vista");
    expect(wrapper.get("img").attributes("src")).toBe(italian.avatar);
  });

  it("never guesses a demographic picture for a user", () => {
    for (const key of ["a", "persona-1", "Éva Rossi", "李", ""]) {
      expect(TWIN_AVATARS).toContain(twinIdentity(undefined, key, "it").avatar);
    }
  });

  it("gives the twins distinct robots in a stable order and reuses them beyond three", () => {
    const peers = twinPeers(["persona-d", "persona-b", "persona-a", "persona-c", "persona-b"]);
    expect(peers).toEqual(["persona-a", "persona-b", "persona-c", "persona-d"]);
    expect(peers.map((key) => twinAvatar(key, peers))).toEqual([
      "/twins/vb.webp",
      "/twins/lb.webp",
      "/twins/cp.webp",
      "/twins/vb.webp",
    ]);
    expect(twinAvatar("outside", peers)).toBe(twinAvatar("outside"));
  });

  it("shows the same robot for a twin in the twins step and in the design step", () => {
    const pinia = createPinia();
    setActivePinia(pinia);
    const store = useUserModelingStore();
    store.personaVersions = [persona("persona-c"), persona("persona-a"), persona("persona-b")];
    store.twinVersions = [
      twin("twin-x", "persona-b"),
      twin("twin-y", "persona-c"),
      twin("twin-z", "persona-a"),
      twin("twin-imported", "persona-of-another-project"),
    ];
    const peers = twinPeers(store.currentPersonas.map((item) => item.persona_id));

    for (const [twinId, personaId] of [
      ["twin-x", "persona-b"],
      ["twin-y", "persona-c"],
      ["twin-z", "persona-a"],
      ["twin-imported", "persona-of-another-project"],
    ] as const) {
      const twinsStep = mount(TwinIdentity, {
        props: { identityKey: personaId, name: twinId, peers },
        global: { plugins: [pinia] },
      });
      const designStep = mount(TwinIdentity, {
        props: { identityKey: twinId, name: twinId },
        global: { plugins: [pinia] },
      });
      expect(designStep.get('[data-testid="twin-identity"]').attributes("data-avatar")).toBe(
        twinsStep.get('[data-testid="twin-identity"]').attributes("data-avatar"),
      );
    }
    const avatars = ["twin-x", "twin-y", "twin-z"].map(
      (twinId) =>
        mount(TwinIdentity, {
          props: { identityKey: twinId, name: twinId },
          global: { plugins: [pinia] },
        })
          .get("img")
          .attributes("src") ?? "",
    );
    expect(new Set(avatars).size).toBe(3);
  });

  it("frames a hypothesis with a dashed ring and a confirmed profile with a solid one", () => {
    const hypothesis = mount(TwinIdentity, { props: { identityKey: "a", name: "Sara" } });
    const confirmed = mount(TwinIdentity, {
      props: { identityKey: "a", name: "Sara", status: "confirmed" },
    });
    const ring = (wrapper: typeof hypothesis) => wrapper.get("[data-identity-status]");
    expect(ring(hypothesis).attributes("data-identity-status")).toBe("hypothesis");
    expect(ring(hypothesis).classes()).toContain("border-dashed");
    expect(ring(confirmed).attributes("data-identity-status")).toBe("confirmed");
    expect(ring(confirmed).classes()).toContain("border-solid");
  });

  it("uses the colours of a dark surface and the heading level it is given", () => {
    const wrapper = mount(UiSurface, {
      slots: {
        default: () =>
          h(TwinIdentity, { identityKey: "a", name: "Sara", nameAs: "h3", size: "lg" }),
      },
    });
    const heading = wrapper.get("h3");
    expect(heading.text()).toBe("Sara");
    expect(heading.classes()).toContain("text-on-night");
    expect(wrapper.get("img").attributes("width")).toBe("52");
  });

  it("uses a safe generic identity for an unknown role", () => {
    const wrapper = mount(TwinIdentity, { props: { role: "__proto__", locale: "it" } });
    expect(wrapper.text()).toContain("Specialista");
    expect(wrapper.text()).not.toContain("__proto__");
    expect(wrapper.get("img").attributes("src")).toBe("/team/copy.webp");
  });

  it("does not repeat a profile's name as its description", () => {
    const wrapper = mount(TwinIdentity, {
      props: { name: "Utenti principianti", description: " utenti principianti " },
    });
    expect(wrapper.text().match(/utenti principianti/gi)).toHaveLength(1);
  });

  it("supports compact labels without relying on color alone", () => {
    const wrapper = mount(TwinIdentity, { props: { role: "QA_TEST_ENGINEER", compact: true } });
    expect(wrapper.text()).toBe("Specialista della qualità");
    expect(wrapper.find("img").exists()).toBe(true);
  });
});
