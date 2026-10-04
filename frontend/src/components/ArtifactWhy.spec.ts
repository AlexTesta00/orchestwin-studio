import { flushPromises, mount } from "@vue/test-utils";
import { describe, expect, it, vi } from "vitest";
import { WhyApiError } from "../api/why";
import { expectAccessible } from "../test/axe";
import { whyAnswer, whyDocument, whyNode } from "../test/whyFixtures";
import type { DirectionShape } from "../types/design";
import type { WhyAnswer, WhyNode } from "../types/why";
import ArtifactWhy from "./ArtifactWhy.vue";
import ArtifactWhyNode from "./ArtifactWhyNode.vue";
import { whyContextKey, twinClaimCode } from "./whyContext";
import { whyNodeTitle } from "./whyCopy";

function setup(
  values: Partial<InstanceType<typeof ArtifactWhy>["$props"]> = {},
  result = whyAnswer(),
) {
  const api = {
    explain: vi.fn().mockResolvedValue(result),
    document: vi.fn().mockResolvedValue(whyDocument([result.target])),
  };
  const wrapper = mount(ArtifactWhy, {
    props: { code: "REQ-001", ...values },
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
  return { wrapper, api };
}

async function open(wrapper: ReturnType<typeof setup>["wrapper"]): Promise<void> {
  (wrapper.element as HTMLDetailsElement).open = true;
  await wrapper.trigger("toggle");
  await flushPromises();
}

const direction: NonNullable<WhyNode["declared_context"]["direction"]> = {
  name: "Quaderno di bordo",
  concept: "Una pagina editoriale con titoli molto grandi e filetti sottili.",
  axes: {
    layout: "EDITORIAL",
    shape: "SQUARE_RULES",
    type: "DISPLAY",
    colour: "INK",
    density: "SPACIOUS",
  },
  candidates: 5,
  origin: "MODEL",
  selected_by: "STUDIO",
};

const directionWords = {
  it: {
    title: "Direzione visiva: Quaderno di bordo",
    axes: [
      "Impianto: Pagina editoriale",
      "Forme: Angoli vivi e filetti",
      "Tipografia: Titoli molto grandi",
      "Colore: Quasi monocromo",
      "Densità: Ariosa",
    ],
    origin: "Proposta dal modello fra 5 candidate; scelta dallo Studio perché lontana dall'altra.",
  },
  en: {
    title: "Visual direction: Quaderno di bordo",
    axes: [
      "Layout: Editorial page",
      "Shapes: Square corners and rules",
      "Type: Very large titles",
      "Colour: Almost monochrome",
      "Density: Spacious",
    ],
    origin:
      "Proposed by the model among 5 candidates; chosen by the Studio because it is far from the other.",
  },
} as const;

const internalIds = ["EDITORIAL", "SQUARE_RULES", "DISPLAY", "INK", "SPACIOUS", "MODEL", "STUDIO"];

function designAlternative(context: Partial<WhyNode["declared_context"]> = {}): WhyNode {
  return whyNode({
    key: "DESIGN_ALTERNATIVE:alternative:2:alternative-hash",
    code: "ALT-002",
    kind: "DESIGN_ALTERNATIVE",
    title: "Quaderno di bordo per il turno",
    reference: { artifact_id: "alternative", version_number: 2, content_hash: "alternative-hash" },
    rationale: {
      text: "Separa la lettura del turno dalla scrittura delle note.",
      origin: "MODEL",
      version_number: 2,
      content_hash: "rationale-hash",
    },
    declared_context: { perspectives: [], ...context },
  });
}

function withoutComments(element: Element): string {
  return element.outerHTML.replace(/<!--[\s\S]*?-->/g, "");
}

describe("Artifact Why", () => {
  it.each(["en", "it"] as const)(
    "localizes container placeholders in the %s chain while preserving authentic titles and references",
    async (locale) => {
      const labels = {
        AGENT_TEAM: ["Prospettive", "Perspectives"],
        PROJECT_BRIEF: ["Brief del progetto", "Project brief"],
        USER_MODELING: ["User twin", "User twins"],
        REQUIREMENTS_SPECIFICATION: ["Definizione", "Definition"],
        DESIGN_PACKAGE: ["Design e valutazione", "Design and evaluation"],
      } as const;
      const containers = Object.keys(labels).map((kind) =>
        whyNode({ key: kind, kind, title: kind }),
      );
      const authenticTitle = "AGENT_TEAM · Progetto reale — titolo originale";
      const target = whyNode({ kind: "AGENT_TEAM", title: authenticTitle });
      const result = whyAnswer(target, {
        upstream: containers,
        summary: {
          upstream_count: containers.length,
          downstream_count: 0,
          complete_to_twin: false,
          complete_to_evidence: false,
          all_paths_complete: false,
          stop_reasons: [],
        },
      });
      const original = structuredClone(result);
      const expected = Object.values(labels).map((label) => label[locale === "it" ? 0 : 1]);
      for (const node of containers) {
        const title = `  Titolo originale ${node.kind}\nSeconda riga  `;
        expect(whyNodeTitle({ ...node, title }, locale)).toBe(title);
      }
      expect(
        whyNodeTitle(whyNode({ kind: "UNKNOWN_CONTAINER", title: "UNKNOWN_CONTAINER" }), locale),
      ).toBe("UNKNOWN_CONTAINER");
      const { wrapper } = setup({ locale }, result);
      await open(wrapper);
      expect(wrapper.get('[data-testid="why-target-title"]').text()).toBe(authenticTitle);
      expect(
        wrapper
          .get('[data-testid="why-summary-upstream"]')
          .findAll("li")
          .map((item) => item.text()),
      ).toEqual(expected.slice(0, 3));
      const details = wrapper.get('[data-testid="why-details"]');
      (details.element as HTMLDetailsElement).open = true;
      await details.trigger("toggle");
      const nodes = details
        .get('[data-testid="why-details-upstream"]')
        .findAll('[data-testid="why-node"]');
      expect(nodes.map((node) => node.get("strong").text())).toEqual(expected);
      expect(result).toEqual(original);
      wrapper.unmount();
    },
  );

  it.each(["en", "it"] as const)(
    "bounds the %s summary and preserves every validation, perspective and gap in accessible details",
    async (locale) => {
      const statuses = ["HYPOTHESIZED", "CONTESTED", "UNKNOWN"] as const;
      const validations = Array.from({ length: 18 }, (_, index) =>
        whyNode({
          key: `validation-${index}`,
          title: `Hypothesis ${index + 1}`,
          display_status: statuses[index % statuses.length]!,
        }),
      );
      const perspectives = [
        "UX",
        "ACCESSIBILITY",
        "SOFTWARE_ENGINEERING",
        "PRODUCT",
        "SECURITY",
      ].map((key) => ({
        key,
        applied: true,
        team_reference: {
          artifact_id: "team",
          version_number: 2,
          content_hash: `historical-team-${key}`,
        },
      }));
      const gapCodes = [
        "MISSING_RATIONALE",
        "SOURCE_TEXT_UNAVAILABLE",
        "CONTEXT_OUTDATED",
        "SOURCE_RETIRED",
        "MISSING_RATIONALE",
      ];
      const target = whyNode({
        gaps: gapCodes.map((code, index) => ({
          code,
          node_key: "REQUIREMENT:req:3:hash",
          related_code: `reference-${index}`,
          stage: "requirements",
        })),
        declared_context: { perspectives },
      });
      const reasons = [
        "MISSING_NEED",
        "MISSING_SCENARIO",
        "MISSING_TWIN",
        "MISSING_CLAIM",
        "MISSING_SOURCE",
        "OMITTED_SECTION",
        "MISSING_NEED",
      ];
      const gaps = [
        ...target.gaps,
        ...reasons.map((code, index) => ({
          code,
          node_key: validations[index]!.key,
          related_code: `upstream-${index}`,
          stage: "twins",
        })),
      ];
      const result = whyAnswer(target, {
        human_validation: validations,
        upstream: validations,
        gaps,
        summary: {
          upstream_count: validations.length,
          downstream_count: 0,
          complete_to_twin: false,
          complete_to_evidence: false,
          all_paths_complete: false,
          stop_reasons: reasons,
        },
      });
      const original = structuredClone(result);
      const { wrapper, api } = setup({ locale }, result);
      await open(wrapper);
      const summaryValidation = wrapper.get('[data-testid="why-human-validation"]');
      expect(summaryValidation.findAll("li")).toHaveLength(3);
      expect(summaryValidation.get("strong").text()).toContain("· 18");
      expect(summaryValidation.text()).toContain(locale === "it" ? "Ipotizzato" : "Hypothesized");
      expect(summaryValidation.text()).toContain(locale === "it" ? "Contestato" : "Contested");
      expect(summaryValidation.text()).toContain(locale === "it" ? "Sconosciuto" : "Unknown");
      const summaryContext = wrapper.get('[data-testid="why-declared-context"]');
      expect(summaryContext.findAll("li")).toHaveLength(3);
      expect(summaryContext.get("strong").text()).toContain("· 5");
      expect(summaryContext.text()).not.toContain("historical-team");
      expect(wrapper.get('[data-testid="why-interrupted"]').findAll("p")).toHaveLength(3);
      expect(wrapper.get('[data-testid="why-interrupted"] strong').text()).toContain("· 6");
      expect(wrapper.findAll('[data-testid="why-target-gap"]')).toHaveLength(3);
      expect(wrapper.get('[data-testid="why-target-gaps"] strong').text()).toContain("· 4");
      const details = wrapper.get('[data-testid="why-details"]');
      expect(details.attributes("open")).toBeUndefined();
      (details.element as HTMLDetailsElement).open = true;
      await details.trigger("toggle");
      await flushPromises();
      const fullValidation = details.get('[data-testid="why-details-human-validation"]');
      expect(fullValidation.isVisible()).toBe(true);
      expect(fullValidation.findAll("li").map((item) => item.attributes("data-why-key"))).toEqual(
        validations.map((node) => node.key),
      );
      const fullContext = details.get('[data-testid="why-details-declared-context"]');
      expect(fullContext.findAll("li")).toHaveLength(perspectives.length);
      for (const perspective of perspectives)
        expect(fullContext.text()).toContain(perspective.team_reference.content_hash);
      expect(details.get('[data-testid="why-details-interrupted"]').findAll("li")).toHaveLength(
        reasons.length,
      );
      const fullGaps = details.get('[data-testid="why-details-gaps"]').findAll("li");
      expect(fullGaps.map((item) => item.attributes("data-gap-code"))).toEqual(
        gaps.map((gap) => gap.code),
      );
      for (const gap of gaps)
        expect(details.get('[data-testid="why-details-gaps"]').text()).toContain(gap.related_code);
      expect(api.explain).toHaveBeenCalledTimes(1);
      expect(result).toEqual(original);
      await expectAccessible(wrapper.element);
      wrapper.unmount();
    },
  );

  it("reads only after opening and shows a summary, missing need and declared context in both languages", async () => {
    for (const locale of ["en", "it"] as const) {
      const target = whyNode({
        declared_context: {
          perspectives: [
            {
              key: "ACCESSIBILITY",
              applied: true,
              team_reference: {
                artifact_id: "team",
                version_number: 2,
                content_hash: "historical-team",
              },
            },
          ],
        },
      });
      const { wrapper, api } = setup({ locale }, whyAnswer(target));
      expect(api.explain).not.toHaveBeenCalled();
      expect(wrapper.get('[data-testid="why-open"]').text()).toBe(
        locale === "it" ? "Perché?" : "Why?",
      );
      await open(wrapper);
      expect(api.explain).toHaveBeenCalledWith("project", "REQ-001", "token");
      expect(wrapper.get('[data-testid="why-summary"]').attributes("data-why-key")).toBe(
        target.key,
      );
      expect(wrapper.get('[data-testid="why-declared-context"]').text()).toContain(
        locale === "it" ? "Contesto dichiarato" : "Declared context",
      );
      expect(wrapper.text()).toContain("historical-team");
      expect(wrapper.get('[data-testid="why-interrupted"]').text()).toContain(
        locale === "it" ? "Manca il bisogno collegato" : "The linked need is missing",
      );
      expect(wrapper.get('[data-testid="why-details"]').attributes("open")).toBeUndefined();
      await wrapper.get('[data-testid="why-details"]').trigger("toggle");
      expect(api.explain).toHaveBeenCalledTimes(1);
      await expectAccessible(wrapper.element);
      wrapper.unmount();
    }
  });

  it("resolves the displayed version and hash without selecting another revision of the same code", async () => {
    const old = whyNode({
      key: "old",
      reference: { artifact_id: "req", version_number: 2, content_hash: "old-hash" },
      current: false,
    });
    const current = whyNode();
    const { wrapper, api } = setup({
      kind: "REQUIREMENT",
      versionNumber: 3,
      contentHash: "hash",
      artifactId: "req",
    });
    api.document.mockResolvedValue(whyDocument([old, current]));
    await open(wrapper);
    expect(api.explain).toHaveBeenCalledExactlyOnceWith("project", current.key, "token");
    expect(wrapper.find('[data-testid="why-candidates"]').exists()).toBe(false);
  });

  it("requires an explicit choice for ambiguous codes and keeps the chosen exact key", async () => {
    const first = whyNode({ key: "first", code: "ELM-001", title: "First button" });
    const second = whyNode({ key: "second", code: "ELM-001", title: "Second button" });
    const { wrapper, api } = setup({ code: "ELM-001" }, whyAnswer(second));
    api.explain.mockRejectedValueOnce(
      new WhyApiError("Ambiguous", {
        status: 409,
        code: "WHY_CODE_AMBIGUOUS",
        payload: { detail: { candidates: [first.key, second.key] } },
      }),
    );
    api.document.mockResolvedValue(whyDocument([first, second]));
    await open(wrapper);
    expect(api.explain).toHaveBeenCalledTimes(1);
    expect(wrapper.findAll('[data-testid="why-candidate"]')).toHaveLength(2);
    await wrapper.findAll('[data-testid="why-candidate"]')[1]!.trigger("click");
    await flushPromises();
    expect(api.explain).toHaveBeenLastCalledWith("project", second.key, "token");
    expect(wrapper.get('[data-testid="why-target-title"]').text()).toBe(second.title);
  });

  it("preserves historical model rationale and retired Unicode quotes as escaped text", async () => {
    const quote = "È già così.\n<img src=x onerror=alert(1)>";
    const target = whyNode({
      key: "claim",
      code: "UT-ABCD1234-v2:user_twin.goals",
      kind: "USER_TWIN_CLAIM",
      title: "goals",
      display_status: "CONTESTED",
      current: false,
      declared_context: {
        perspectives: [],
        observation_value: { kind: "TEXT", text: quote, items: [], reason: null },
      },
      rationale: {
        text: "Historic explanation",
        origin: "MODEL",
        version_number: 2,
        content_hash: "old-rationale",
      },
      citations: [
        {
          citation: {
            source_id: "source",
            source_version: 1,
            content_hash: "source-hash",
            quote,
            start: 10,
            end: 10 + [...quote].length,
            start_line: 2,
            end_line: 3,
          },
          status: "RETIRED",
          effect: "SUPPORTS",
          source: { title: "Interview", status: "RETIRED", text_available: false },
        },
      ],
    });
    const { wrapper } = setup({ code: target.key, locale: "it" }, whyAnswer(target));
    await open(wrapper);
    expect(wrapper.get('[data-testid="why-target-title"]').text()).toBe("Obiettivi");
    expect(wrapper.get('[data-testid="why-rationale"]').text()).toContain(
      "Motivazione generata dal modello",
    );
    expect(wrapper.get('[data-testid="why-quote"]').text()).toBe(quote);
    expect(wrapper.get('[data-testid="why-claim-value"]').text()).toContain(quote);
    expect(wrapper.find("img").exists()).toBe(false);
    expect(wrapper.get('[data-testid="why-retired-source"]').text()).toBe("Fonte ritirata");
    expect(wrapper.text()).toContain("old-rationale");
    expect(wrapper.text()).toContain("Contestato");
    expect(twinClaimCode("abcd1234-0000-4000-8000-000000000000", 2, "user_twin.goals")).toBe(
      target.code,
    );
  });

  it("drops a late response after the displayed artifact changes", async () => {
    const { wrapper, api } = setup();
    let resolve: ((value: WhyAnswer) => void) | undefined;
    api.explain.mockImplementationOnce(
      () =>
        new Promise<WhyAnswer>((done) => {
          resolve = done;
        }),
    );
    api.explain.mockImplementationOnce(() => new Promise<WhyAnswer>(() => {}));
    (wrapper.element as HTMLDetailsElement).open = true;
    await wrapper.trigger("toggle");
    await wrapper.setProps({ code: "REQ-002" });
    resolve!(whyAnswer());
    await flushPromises();
    expect(wrapper.find('[data-testid="why-summary"]').exists()).toBe(false);
  });

  it.each(["it", "en"] as const)(
    "shows the %s visual direction of a design alternative in plain words without internal ids",
    async (locale) => {
      const words = directionWords[locale];
      const target = designAlternative({ direction });
      const original = structuredClone(target);
      const { wrapper } = setup({ code: target.code, locale }, whyAnswer(target));
      await open(wrapper);
      const details = wrapper.get('[data-testid="why-details"]');
      (details.element as HTMLDetailsElement).open = true;
      await details.trigger("toggle");
      const blocks = details.findAll('[data-testid="why-direction"]');
      expect(blocks).toHaveLength(1);
      const block = blocks[0]!;
      expect(block.get("strong").text()).toBe(words.title);
      expect(block.get("p").text()).toBe(direction.concept);
      expect(block.findAll("li").map((item) => item.text())).toEqual(words.axes);
      expect(block.get('[data-testid="why-direction-origin"]').text()).toBe(words.origin);
      for (const id of internalIds) {
        expect(wrapper.text()).not.toContain(id);
        expect(block.html()).not.toContain(id);
      }
      expect(target).toEqual(original);
      await expectAccessible(wrapper.element);
      wrapper.unmount();
    },
  );

  it.each(["it", "en"] as const)(
    "skips an unknown %s direction value instead of showing its id",
    (locale) => {
      const node = designAlternative({
        direction: {
          ...direction,
          axes: { ...direction.axes, shape: "NOT_IN_VOCABULARY" as unknown as DirectionShape },
        },
      });
      const wrapper = mount(ArtifactWhyNode, { props: { node, locale } });
      const [layout, , type, colour, density] = directionWords[locale].axes;
      expect(
        wrapper
          .get('[data-testid="why-direction"]')
          .findAll("li")
          .map((item) => item.text()),
      ).toEqual([layout, type, colour, density]);
      expect(wrapper.text()).not.toContain("NOT_IN_VOCABULARY");
      wrapper.unmount();
    },
  );

  it.each(["it", "en"] as const)(
    "renders a %s node without a direction exactly as before",
    (locale) => {
      const plain = mount(ArtifactWhyNode, { props: { node: designAlternative(), locale } });
      const directed = mount(ArtifactWhyNode, {
        props: { node: designAlternative({ direction }), locale },
      });
      expect(plain.find('[data-testid="why-direction"]').exists()).toBe(false);
      expect(plain.text()).not.toContain(locale === "it" ? "Direzione visiva" : "Visual direction");
      expect(plain.text()).not.toContain(directionWords[locale].origin);
      const block = directed.get('[data-testid="why-direction"]').element;
      expect(withoutComments(directed.element).replace(withoutComments(block), "")).toBe(
        withoutComments(plain.element),
      );
      plain.unmount();
      directed.unmount();
    },
  );
});
