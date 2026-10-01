import { flushPromises, mount } from "@vue/test-utils";
import { afterEach, describe, expect, it } from "vitest";

import type { ProjectStage } from "@/api/contracts";
import { expectAccessible } from "@/test/axe";
import type {
  ProjectSectionPayload,
  ProjectSectionsPayload,
  SectionAlignmentResultPayload,
  SectionBlock,
  SectionsAlignmentPayload,
  SectionsAlignmentSummaryPayload,
} from "@/types/sections";
import ProjectSectionsNotice from "./ProjectSectionsNotice.vue";

type Locale = "en" | "it";

const LABELS: Record<Locale, string[]> = {
  it: ["Brief", "Prospettive", "User Twin", "Definizione", "Design e valutazione", "Dossier"],
  en: ["Brief", "Perspectives", "User Twin", "Definition", "Design & Evaluation", "Dossier"],
};

const KEYS: ProjectStage[] = ["BRIEF", "TEAM", "USER_TWINS", "REQUIREMENTS", "DESIGN", "PACKAGE"];

function sectionsOf(
  overrides: Partial<Record<ProjectStage, Partial<ProjectSectionPayload>>> = {},
  alignment: Partial<SectionsAlignmentSummaryPayload> = {},
): ProjectSectionsPayload {
  return {
    first_pass_complete: true,
    sections: KEYS.map((key) => ({
      key,
      state: "FINE",
      version_number: 2,
      reasons: [],
      blocked: null,
      codes: [],
      ...overrides[key],
    })),
    alignment: { available: false, sections: [], uncovered_codes: [], ...alignment },
  };
}

const BEHIND = sectionsOf(
  {
    USER_TWINS: { state: "TO_UPDATE", reasons: ["PERSPECTIVES_CHANGED"] },
    REQUIREMENTS: { state: "TO_UPDATE", reasons: ["PERSPECTIVES_CHANGED", "USER_TWINS_CHANGED"] },
    DESIGN: { state: "TO_UPDATE", reasons: ["REQUIREMENTS_CHANGED"] },
    PACKAGE: { state: "TO_UPDATE", reasons: ["FOLDER_BEHIND"] },
  },
  { available: true, sections: ["USER_TWINS", "REQUIREMENTS", "DESIGN"] },
);

function result(
  outcomes: Partial<SectionAlignmentResultPayload>[],
  sections: ProjectSectionsPayload,
  status: SectionsAlignmentPayload["status"] = "ALIGNED",
): SectionsAlignmentPayload {
  return {
    status,
    results: outcomes.map((outcome) => ({
      key: "USER_TWINS",
      outcome: "ALIGNED",
      issue: null,
      version_number: 3,
      codes: [],
      ...outcome,
    })),
    sections,
  };
}

interface NoticeProps {
  sections: ProjectSectionsPayload;
  openKey?: ProjectStage;
  busy?: boolean;
  result?: SectionsAlignmentPayload | null;
  failed?: boolean;
}

const mounted: { unmount: () => void }[] = [];

function mountNotice(props: NoticeProps, locale: Locale = "it") {
  const wrapper = mount(ProjectSectionsNotice, {
    attachTo: document.body,
    props: { labels: LABELS[locale], openKey: "PACKAGE", locale, ...props },
  });
  mounted.push(wrapper);
  return wrapper;
}

function lines(wrapper: ReturnType<typeof mountNotice>): string[] {
  return wrapper
    .findAll('[data-testid="sections-notice-line"]')
    .map((line) => line.text().replace(/\s+/g, " "));
}

const notice = '[data-testid="sections-notice"]';
const gesture = '[data-testid="sections-align"]';

afterEach(() => {
  for (const wrapper of mounted.splice(0)) {
    wrapper.unmount();
  }
});

describe("ProjectSectionsNotice", () => {
  it.each<[Locale, string[], string]>([
    [
      "it",
      [
        "User Twin, Definizione e Design e valutazione da aggiornare: a monte qualcosa è cambiato. I contenuti che hai approvato restano gli stessi, vengono solo riagganciati alle versioni nuove.",
        "Requisiti nuovi che il design non copre ancora: REQ-008 e REQ-009. Dopo l'aggiornamento puoi chiedere una modifica al design.",
      ],
      "Aggiorna e conferma",
    ],
    [
      "en",
      [
        "User Twin, Definition and Design & Evaluation to update: something upstream changed. The content you approved stays the same, it is only re-anchored to the new versions.",
        "New requirements that the design does not cover yet: REQ-008 and REQ-009. After the update you can ask for a change to the design.",
      ],
      "Update and confirm",
    ],
  ])(
    "names the sections behind, what the design will not cover and the one gesture in %s",
    (locale, expected, label) => {
      const wrapper = mountNotice(
        {
          sections: {
            ...BEHIND,
            alignment: { ...BEHIND.alignment, uncovered_codes: ["REQ-008", "REQ-009"] },
          },
        },
        locale,
      );

      expect(wrapper.get(notice).attributes("role")).toBe("status");
      expect(lines(wrapper)).toEqual(expected);
      expect(wrapper.get(gesture).text()).toBe(label);
      expect(wrapper.get(gesture).attributes("disabled")).toBeUndefined();
    },
  );

  it("leaves out the sentence on what the design does not cover when it covers everything", () => {
    const wrapper = mountNotice({ sections: BEHIND });

    expect(wrapper.findAll('[data-testid="sections-notice-line"]')).toHaveLength(1);
    expect(wrapper.get('[data-kind="behind"]').text()).toContain("da aggiornare");
  });

  it("asks for the gesture once and cannot be pressed again while it runs", async () => {
    const wrapper = mountNotice({ sections: BEHIND });

    await wrapper.get(gesture).trigger("click");
    expect(wrapper.emitted("align")).toEqual([[]]);

    await wrapper.setProps({ busy: true });
    expect(wrapper.get(gesture).attributes("disabled")).toBeDefined();
    expect(wrapper.get(notice).attributes("aria-busy")).toBe("true");
    expect(wrapper.get('[data-testid="sections-notice-running"]').text()).toBe(
      "Aggiorno le sezioni…",
    );
    await wrapper.get(gesture).trigger("click");
    (wrapper.get(gesture).element as HTMLButtonElement).click();
    expect(wrapper.emitted("align")).toHaveLength(1);
  });

  it.each<[Locale, string, string]>([
    [
      "it",
      "✓ Sezioni aggiornate: User Twin, Definizione e Design e valutazione.",
      "Il design è stato riagganciato alla Definizione nuova: puoi chiedere ai twin una nuova valutazione.",
    ],
    [
      "en",
      "✓ Sections updated: User Twin, Definition and Design & Evaluation.",
      "The design was re-anchored to the new Definition: you can ask the twins for a new evaluation.",
    ],
  ])(
    "announces in %s what the gesture updated and invites a new evaluation of the design",
    async (locale, done, evaluation) => {
      const wrapper = mountNotice({ sections: BEHIND }, locale);
      const after = sectionsOf({
        DESIGN: { state: "UPDATE_AVAILABLE", reasons: ["EVALUATION_MISSING"] },
        PACKAGE: { state: "TO_UPDATE", reasons: ["FOLDER_BEHIND"] },
      });

      await wrapper.setProps({
        sections: after,
        result: result([{ key: "USER_TWINS" }, { key: "REQUIREMENTS" }, { key: "DESIGN" }], after),
      });

      expect(lines(wrapper)).toEqual([done, evaluation]);
      expect(wrapper.get('[data-kind="done"]').classes()).toContain("text-petrol-on-night-2");
      expect(wrapper.find(gesture).exists()).toBe(false);
    },
  );

  it.each<[Locale, string[]]>([
    [
      "it",
      [
        "✓ Sezioni aggiornate: User Twin e Definizione.",
        "Design e valutazione non si aggiorna da sola: il design cita REQ-004 e REQ-007, che la Definizione non contiene più: rigenera le alternative nel passo Design e valutazione.",
      ],
    ],
    [
      "en",
      [
        "✓ Sections updated: User Twin and Definition.",
        "Design & Evaluation cannot be updated by itself: the design cites REQ-004 and REQ-007, which the Definition no longer contains: regenerate the alternatives in the Design & Evaluation step.",
      ],
    ],
  ])("tells in %s what a partial gesture updated and why it stopped", (locale, expected) => {
    const after = sectionsOf({
      DESIGN: {
        state: "TO_UPDATE",
        reasons: ["REQUIREMENTS_CHANGED"],
        blocked: "REQUIREMENT_NO_LONGER_AVAILABLE",
        codes: ["REQ-004", "REQ-007"],
      },
    });
    const wrapper = mountNotice(
      {
        sections: after,
        result: result(
          [
            { key: "USER_TWINS" },
            { key: "REQUIREMENTS" },
            {
              key: "DESIGN",
              outcome: "BLOCKED",
              issue: "REQUIREMENT_NO_LONGER_AVAILABLE",
              version_number: null,
              codes: ["REQ-004", "REQ-007"],
            },
          ],
          after,
          "PARTIAL",
        ),
      },
      locale,
    );

    expect(lines(wrapper)).toEqual(expected);
    expect(wrapper.find(gesture).exists()).toBe(false);
  });

  it.each<[Locale, ProjectStage, SectionBlock, string]>([
    [
      "it",
      "DESIGN",
      "TWIN_SET_CHANGED",
      "Design e valutazione non si aggiorna da sola: i twin non sono più gli stessi.",
    ],
    [
      "en",
      "DESIGN",
      "TWIN_SET_CHANGED",
      "Design & Evaluation cannot be updated by itself: the twins are no longer the same.",
    ],
    [
      "it",
      "REQUIREMENTS",
      "TWIN_NO_LONGER_AVAILABLE",
      "Definizione non si aggiorna da sola: i twin non sono più gli stessi.",
    ],
    [
      "en",
      "REQUIREMENTS",
      "TWIN_NO_LONGER_AVAILABLE",
      "Definition cannot be updated by itself: the twins are no longer the same.",
    ],
    [
      "it",
      "REQUIREMENTS",
      "REVISION_PENDING",
      "Definizione non si aggiorna da sola: c'è una modifica proposta da decidere.",
    ],
    [
      "en",
      "REQUIREMENTS",
      "REVISION_PENDING",
      "Definition cannot be updated by itself: a proposed change is waiting for your decision.",
    ],
    [
      "it",
      "USER_TWINS",
      "UPSTREAM_NOT_READY",
      "User Twin non si aggiorna da sola: prima va sistemata la sezione a monte.",
    ],
    [
      "en",
      "USER_TWINS",
      "UPSTREAM_NOT_READY",
      "User Twin cannot be updated by itself: the section upstream has to be settled first.",
    ],
    [
      "it",
      "TEAM",
      "PREPARE_AGAIN",
      "Prospettive non si aggiorna da sola: il brief è cambiato: prepara di nuovo le prospettive.",
    ],
    [
      "en",
      "TEAM",
      "PREPARE_AGAIN",
      "Perspectives cannot be updated by itself: the brief changed: prepare the perspectives again.",
    ],
  ])("says in %s why %s, blocked by %s, cannot be updated", (locale, key, blocked, expected) => {
    const behind: Partial<ProjectSectionPayload> = {
      state: "TO_UPDATE",
      reasons: ["BRIEF_CHANGED"],
      blocked,
    };
    const wrapper = mountNotice({ sections: sectionsOf({ [key]: behind }) }, locale);

    expect(lines(wrapper)).toEqual([expected]);
    expect(wrapper.find(gesture).exists()).toBe(false);
  });

  it("speaks only of the first section that cannot be updated, before and after the gesture", () => {
    const chain = sectionsOf({
      TEAM: { state: "IN_PROGRESS" },
      USER_TWINS: { state: "TO_UPDATE", blocked: "UPSTREAM_NOT_READY" },
      REQUIREMENTS: { state: "TO_UPDATE", blocked: "UPSTREAM_NOT_READY" },
      DESIGN: { state: "TO_UPDATE", blocked: "UPSTREAM_NOT_READY" },
    });

    expect(lines(mountNotice({ sections: chain }))).toEqual([
      "User Twin non si aggiorna da sola: prima va sistemata la sezione a monte.",
    ]);
  });

  it("warns before the gesture about a section that it will not be able to update", () => {
    const sections = sectionsOf(
      {
        USER_TWINS: { state: "TO_UPDATE" },
        DESIGN: { state: "TO_UPDATE", blocked: "REVISION_PENDING" },
      },
      { available: true, sections: ["USER_TWINS", "DESIGN"] },
    );

    expect(lines(mountNotice({ sections }, "en"))).toEqual([
      "User Twin and Design & Evaluation to update: something upstream changed. The content you approved stays the same, it is only re-anchored to the new versions.",
      "Design & Evaluation cannot be updated by itself: a proposed change is waiting for your decision.",
    ]);
  });

  it("gives a plain reason for a refusal that it does not know", () => {
    const wrapper = mountNotice({
      sections: sectionsOf({ DESIGN: { state: "TO_UPDATE", blocked: null } }),
      result: result(
        [{ key: "DESIGN", outcome: "BLOCKED", issue: "GATE_CONFLICT", version_number: null }],
        sectionsOf({ DESIGN: { state: "TO_UPDATE" } }),
        "PARTIAL",
      ),
    });

    expect(lines(wrapper)).toEqual([
      "Design e valutazione non si aggiorna da sola: non è stato possibile farlo adesso, riprova tra poco.",
    ]);
  });

  it("opens the Perspectives section from the reason that asks to prepare them again", async () => {
    const sections = sectionsOf({
      TEAM: { state: "TO_UPDATE", blocked: "PREPARE_AGAIN" },
      USER_TWINS: { state: "TO_UPDATE", blocked: "UPSTREAM_NOT_READY" },
    });
    const wrapper = mountNotice({ sections });
    const link = wrapper.get('[data-testid="sections-notice-open"]');

    expect(link.text()).toBe("Apri Prospettive");
    expect(link.attributes("data-target")).toBe("TEAM");
    await link.trigger("click");
    expect(wrapper.emitted("open")).toEqual([["TEAM"]]);

    await wrapper.setProps({ openKey: "TEAM" });
    expect(wrapper.find('[data-testid="sections-notice-open"]').exists()).toBe(false);
    expect(document.activeElement).toBe(wrapper.get(notice).element);
  });

  it.each<[Locale, string[], string]>([
    [
      "it",
      [
        "I twin hanno imparato qualcosa durante lo sviluppo: guarda la proposta con ut twins update.",
        "Requisiti nuovi che il design non copre ancora: REQ-008. Chiedi una modifica al design per coprirli.",
        "Il design è stato riagganciato alla Definizione nuova: puoi chiedere ai twin una nuova valutazione.",
      ],
      "Apri Design e valutazione",
    ],
    [
      "en",
      [
        "The twins learned something during development: see the proposal with ut twins update.",
        "New requirements that the design does not cover yet: REQ-008. Ask for a change to the design to cover them.",
        "The design was re-anchored to the new Definition: you can ask the twins for a new evaluation.",
      ],
      "Open Design & Evaluation",
    ],
  ])("tells in %s what new material a section could take in", async (locale, expected, open) => {
    const wrapper = mountNotice(
      {
        sections: sectionsOf({
          USER_TWINS: { state: "UPDATE_AVAILABLE", reasons: ["TWINS_LEARNED"] },
          DESIGN: {
            state: "UPDATE_AVAILABLE",
            reasons: ["REQUIREMENTS_NOT_COVERED", "EVALUATION_MISSING"],
            codes: ["REQ-008"],
          },
        }),
      },
      locale,
    );

    expect(lines(wrapper)).toEqual(expected);
    expect(wrapper.get('[data-kind="learned"] code').text()).toBe("ut twins update");
    const link = wrapper.get('[data-testid="sections-notice-open"]');
    expect(link.text()).toBe(open);
    await link.trigger("click");
    expect(wrapper.emitted("open")).toEqual([["DESIGN"]]);
    expect(wrapper.find(gesture).exists()).toBe(false);
  });

  it.each([
    ["every section is fine", sectionsOf()],
    [
      "only a section waits for a decision or the folder is behind",
      sectionsOf({
        REQUIREMENTS: { state: "IN_PROGRESS" },
        DESIGN: { state: "NOT_STARTED", version_number: null },
        PACKAGE: { state: "TO_UPDATE", reasons: ["FOLDER_BEHIND"] },
      }),
    ],
  ])("renders nothing when %s", (_label, sections) => {
    const wrapper = mountNotice({ sections });

    expect(wrapper.find(notice).exists()).toBe(false);
    expect(wrapper.findAll("p")).toHaveLength(0);
    expect(wrapper.find("button").exists()).toBe(false);
  });

  it.each<[Locale, string]>([
    ["it", "Non c'era niente da aggiornare: le sezioni erano già a posto."],
    ["en", "There was nothing to update: the sections were already up to date."],
  ])("says in %s when the gesture found nothing to update", (locale, expected) => {
    const wrapper = mountNotice(
      { sections: sectionsOf(), result: result([], sectionsOf(), "NOTHING_TO_ALIGN") },
      locale,
    );

    expect(lines(wrapper)).toEqual([expected]);
  });

  it.each<[Locale, string]>([
    ["it", "Non è stato possibile aggiornare le sezioni: riprova."],
    ["en", "The sections could not be updated: try again."],
  ])("says in %s that the gesture failed and keeps it available", (locale, expected) => {
    const wrapper = mountNotice({ sections: BEHIND, failed: true }, locale);

    expect(lines(wrapper)[0]).toBe(expected);
    expect(wrapper.get('[data-kind="failed"]').classes()).toContain("text-fail-on-night");
    expect(wrapper.get(gesture).attributes("disabled")).toBeUndefined();
  });

  it("keeps the keyboard focus in the notice when the gesture button goes away", async () => {
    const wrapper = mountNotice({ sections: BEHIND });
    const button = wrapper.get(gesture);
    (button.element as HTMLButtonElement).focus();
    await button.trigger("click");
    await wrapper.setProps({ busy: true });
    const after = sectionsOf();

    await wrapper.setProps({
      busy: false,
      sections: after,
      result: result([{ key: "USER_TWINS" }], after),
    });
    await flushPromises();

    expect(wrapper.find(gesture).exists()).toBe(false);
    expect(document.activeElement).toBe(wrapper.get(notice).element);
    expect(wrapper.get(notice).attributes("tabindex")).toBe("-1");
  });

  it("gives the focus back to the gesture when it failed", async () => {
    const wrapper = mountNotice({ sections: BEHIND });
    await wrapper.get(gesture).trigger("click");
    await wrapper.setProps({ busy: true });
    (document.activeElement as HTMLElement | null)?.blur();

    await wrapper.setProps({ busy: false, failed: true });
    await flushPromises();

    expect(document.activeElement).toBe(wrapper.get(gesture).element);
  });

  it("has no axe violations with the gesture, a result, a reason and a link", async () => {
    const wrapper = mountNotice({
      sections: {
        ...sectionsOf(
          {
            TEAM: { state: "TO_UPDATE", blocked: "PREPARE_AGAIN" },
            USER_TWINS: { state: "UPDATE_AVAILABLE", reasons: ["TWINS_LEARNED"] },
          },
          { available: true, sections: ["REQUIREMENTS"], uncovered_codes: ["REQ-002"] },
        ),
      },
      result: result([{ key: "DESIGN" }], sectionsOf()),
    });

    await expectAccessible(wrapper.element);
    await wrapper.setProps({ busy: true });
    await expectAccessible(wrapper.element);
  });
});
