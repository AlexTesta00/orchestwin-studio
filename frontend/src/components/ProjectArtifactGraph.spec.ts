import { createPinia, setActivePinia } from "pinia";
import { flushPromises, mount } from "@vue/test-utils";
import { beforeEach, describe, expect, it, vi } from "vitest";

import type { ArtifactGraphApi } from "../api/artifacts";
import type { CrossStageArtifactGraphPayload } from "../types/artifacts";
import { ARTIFACT_GRAPH, ARTIFACT_GRAPH_PROJECT_ID } from "../test/artifactGraphFixtures";
import ProjectArtifactGraph from "./ProjectArtifactGraph.vue";

const authorize = <T>(operation: (accessToken: string) => Promise<T>) => operation("access-token");

const OLD_STEP_NAMES =
  /passo Squadra|Team step|passo Requisiti|Requirements step|passo Pacchetto|Package step|\bPacchetto\b/;

const TEAM_WORDS =
  /\b(?:squadr[ae]|teams?|agent[ei]|agents?|assistent[ei]|assistants?|specialist[ai]|specialists?|ruol[oi]|roles?|membr[oi]|members?)\b/i;

function fakeApi(): ArtifactGraphApi {
  return {
    current: async () => ARTIFACT_GRAPH,
    exportCurrent: async () =>
      new Blob([JSON.stringify(ARTIFACT_GRAPH)], {
        type: "application/json",
      }),
  };
}

function mountGraph(
  options: {
    api?: ArtifactGraphApi;
    saveExport?: (blob: Blob, filename: string) => void;
    locale?: "en" | "it";
  } = {},
) {
  const props: {
    projectId: string;
    authorize: typeof authorize;
    api: ArtifactGraphApi;
    locale: "en" | "it";
    saveExport?: (blob: Blob, filename: string) => void;
  } = {
    projectId: ARTIFACT_GRAPH_PROJECT_ID,
    authorize,
    api: options.api ?? fakeApi(),
    locale: options.locale ?? "en",
  };

  if (options.saveExport !== undefined) {
    props.saveExport = options.saveExport;
  }

  return mount(ProjectArtifactGraph, {
    global: {
      plugins: [createPinia()],
    },
    props,
  });
}

describe("ProjectArtifactGraph", () => {
  it.each(["it", "en"] as const)(
    "renders versioned evidence links to the exact current twin in %s",
    async (locale) => {
      const graph: CrossStageArtifactGraphPayload = structuredClone(ARTIFACT_GRAPH);
      const evidence = {
        kind: "RESEARCH_EVIDENCE" as const,
        artifact_id: "33333333-3333-4333-8333-333333333333",
        version_number: 2,
        content_hash: "e".repeat(64),
      };
      const twin = {
        kind: "USER_TWIN" as const,
        artifact_id: "22222222-2222-4222-8222-222222222222",
        version_number: 3,
        content_hash: "f".repeat(64),
      };
      graph.nodes.push(
        {
          reference: evidence,
          stage: "CONTEXT",
          display_code: "EVD-001",
          title: "Synthetic source",
        },
        { reference: twin, stage: "CONTEXT", display_code: "TWIN-001", title: "Calculator user" },
      );
      graph.stage_counts.CONTEXT += 2;
      graph.links.push(
        ...(["SUPPORTS", "CONTRADICTS", "ADDS"] as const).map((kind) => ({
          kind,
          source: evidence,
          target: twin,
        })),
      );
      const wrapper = mountGraph({ locale, api: { ...fakeApi(), current: async () => graph } });
      await flushPromises();
      await wrapper.get('[data-testid="artifact-kind-filter"]').setValue("RESEARCH_EVIDENCE");
      expect(wrapper.findAll("tbody tr")).toHaveLength(3);
      expect(wrapper.text()).toContain(locale === "it" ? "Fonte di evidenza" : "Evidence source");
      expect(wrapper.text()).toContain(locale === "it" ? "contraddice" : "contradicts");
      expect(wrapper.text()).toContain("e".repeat(64));
      expect(
        wrapper
          .findAll("tbody tr")
          .every(
            (row) =>
              row.text().includes("Synthetic source · v2") &&
              row.text().includes("Calculator user · v3"),
          ),
      ).toBe(true);
      expect(wrapper.findAll("h5").map((heading) => heading.text())).toEqual(["Synthetic source"]);
      wrapper.unmount();
    },
  );

  it.each(["en", "it"] as const)(
    "shows and filters the scenario to need chain in %s",
    async (locale) => {
      const graph: CrossStageArtifactGraphPayload = structuredClone(ARTIFACT_GRAPH);
      const twin = {
        reference: {
          kind: "USER_TWIN" as const,
          artifact_id: "twin-32",
          version_number: 1,
          content_hash: "e".repeat(64),
        },
        stage: "CONTEXT" as const,
        display_code: "TWIN-001",
        title: "Receptionist",
      };
      graph.nodes.push(twin);
      graph.stage_counts.CONTEXT += 1;
      const requirement = graph.nodes.find((node) => node.reference.kind === "REQUIREMENT")!;
      const scenario = {
        kind: "SCENARIO" as const,
        artifact_id: "scenario-32",
        version_number: null,
        content_hash: null,
      };
      const need = {
        kind: "NEED" as const,
        artifact_id: "need-32",
        version_number: null,
        content_hash: null,
      };
      const journey = { ...need, kind: "JOURNEY" as const, artifact_id: "journey-32" };
      graph.nodes.push(
        {
          reference: scenario,
          stage: "REQUIREMENTS",
          display_code: "SCN-001",
          title: "Guest arrives",
        },
        {
          reference: need,
          stage: "REQUIREMENTS",
          display_code: "NED-001",
          title: "Recognize guests",
        },
        {
          reference: journey,
          stage: "REQUIREMENTS",
          display_code: "JRN-001",
          title: "Welcome the guest",
        },
      );
      graph.links.push(
        { kind: "PARTICIPATES_IN", source: twin.reference, target: scenario },
        { kind: "REVEALS", source: scenario, target: need },
        { kind: "MOTIVATES", source: need, target: requirement.reference },
        { kind: "EXPANDS", source: scenario, target: journey },
        { kind: "REVEALS", source: journey, target: need },
      );
      graph.stage_counts.REQUIREMENTS += 3;
      const wrapper = mountGraph({ locale, api: { ...fakeApi(), current: async () => graph } });
      await flushPromises();
      expect(wrapper.text()).toContain(locale === "it" ? "partecipa a" : "participates in");
      expect(wrapper.text()).toContain(locale === "it" ? "rivela" : "reveals");
      expect(wrapper.text()).toContain(locale === "it" ? "espande" : "expands");
      await wrapper.get('[data-testid="artifact-kind-filter"]').setValue("NEED");
      expect(wrapper.findAll("tbody tr")).toHaveLength(3);
      expect(
        wrapper.findAll("tbody tr").every((row) => row.text().includes("Recognize guests")),
      ).toBe(true);
      expect(wrapper.findAll("h5").map((heading) => heading.text())).toEqual(["Recognize guests"]);
      expect(wrapper.get('[data-testid="artifact-kind-filter"]').text()).toContain(
        locale === "it" ? "Bisogno" : "Need",
      );
      await wrapper.get('[data-testid="artifact-kind-filter"]').setValue("JOURNEY");
      expect(wrapper.findAll("tbody tr")).toHaveLength(2);
      expect(wrapper.findAll("h5").map((heading) => heading.text())).toEqual(["Welcome the guest"]);
    },
  );
  beforeEach(() => {
    setActivePinia(createPinia());
  });

  it("renders exact roots, stage nodes, and the methodological boundary", async () => {
    const wrapper = mountGraph();

    await flushPromises();

    expect(wrapper.text()).toContain("Cross-stage artifact graph");
    expect(wrapper.text()).toContain("REQ-001");
    expect(wrapper.text()).toContain("DES-001");
    expect(wrapper.text()).toContain("not empirical evidence");
    expect(wrapper.text()).toContain(ARTIFACT_GRAPH.requirements_reference.content_hash);
    expect(wrapper.text()).toContain(ARTIFACT_GRAPH.design_reference?.content_hash);
  });

  it("filters the accessible relationship table by connected stage", async () => {
    const wrapper = mountGraph();

    await flushPromises();

    const relationshipRowsBefore = wrapper.findAll("tbody tr");
    await wrapper.get("select").setValue("DESIGN");
    const relationshipRowsAfter = wrapper.findAll("tbody tr");

    expect(relationshipRowsBefore.length).toBe(ARTIFACT_GRAPH.links.length);
    expect(relationshipRowsAfter).toHaveLength(3);
    expect(relationshipRowsAfter[0]?.text()).toContain("GROUNDED_IN");
    expect(relationshipRowsAfter[0]?.text()).toContain("DESIGN-v2");
  });

  it.each([
    [
      "it",
      "Tutte le fasi",
      ["Brief, Prospettive e User Twin", "Definizione", "Design e valutazione"],
    ],
    [
      "en",
      "All stages",
      ["Brief, Perspectives and User Twin", "Definition", "Design & Evaluation"],
    ],
  ] as const)(
    "names the stages after the steps and speaks of no team in %s",
    async (locale, allStages, stages) => {
      const wrapper = mountGraph({ locale });

      await flushPromises();

      expect(
        wrapper.findAll("section[aria-label] article h4").map((title) => title.text()),
      ).toEqual(stages);
      expect(
        wrapper
          .get("select")
          .findAll("option")
          .map((option) => option.text()),
      ).toEqual([allStages, ...stages]);
      expect(wrapper.text()).not.toMatch(OLD_STEP_NAMES);
      expect(wrapper.text()).not.toMatch(TEAM_WORDS);
    },
  );

  it("downloads the server-generated JSON export through an injected saver", async () => {
    const saveExport = vi.fn<(blob: Blob, filename: string) => void>();
    const wrapper = mountGraph({ saveExport });

    await flushPromises();

    const exportButton = wrapper
      .findAll("button")
      .find((button) => button.text().includes("Export JSON graph"));

    if (exportButton === undefined) {
      throw new Error("The Artifact Graph export action was not rendered");
    }

    await exportButton.trigger("click");
    await flushPromises();

    expect(saveExport).toHaveBeenCalledTimes(1);
    expect(saveExport.mock.calls[0]?.[0]).toBeInstanceOf(Blob);
    expect(saveExport.mock.calls[0]?.[1]).toBe(
      `orchestwin-${ARTIFACT_GRAPH_PROJECT_ID}-artifact-graph.json`,
    );
  });
});
