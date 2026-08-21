import { createPinia, setActivePinia } from "pinia";
import { flushPromises, mount } from "@vue/test-utils";
import { beforeEach, describe, expect, it, vi } from "vitest";

import type { ArtifactGraphApi } from "../api/artifacts";
import { ARTIFACT_GRAPH, ARTIFACT_GRAPH_PROJECT_ID } from "../test/artifactGraphFixtures";
import ProjectArtifactGraph from "./ProjectArtifactGraph.vue";

const authorize = <T>(operation: (accessToken: string) => Promise<T>) => operation("access-token");

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
  } = {},
) {
  const props: {
    projectId: string;
    authorize: typeof authorize;
    api: ArtifactGraphApi;
    saveExport?: (blob: Blob, filename: string) => void;
  } = {
    projectId: ARTIFACT_GRAPH_PROJECT_ID,
    authorize,
    api: options.api ?? fakeApi(),
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
  beforeEach(() => {
    setActivePinia(createPinia());
  });

  it("renders exact roots, stage nodes, and the methodological boundary", async () => {
    const wrapper = mountGraph();

    await flushPromises();

    expect(wrapper.text()).toContain("Cross-stage artifact graph");
    expect(wrapper.text()).toContain("REQ-001");
    expect(wrapper.text()).toContain("TST-001");
    expect(wrapper.text()).toContain("not empirical evidence");
    expect(wrapper.text()).toContain(ARTIFACT_GRAPH.requirements_reference.content_hash);
    expect(wrapper.text()).toContain(ARTIFACT_GRAPH.architecture_reference?.content_hash);
  });

  it("filters the accessible relationship table by connected stage", async () => {
    const wrapper = mountGraph();

    await flushPromises();

    const relationshipRowsBefore = wrapper.findAll("tbody tr");
    await wrapper.get("select").setValue("TESTING");
    const relationshipRowsAfter = wrapper.findAll("tbody tr");

    expect(relationshipRowsBefore.length).toBe(ARTIFACT_GRAPH.links.length);
    expect(relationshipRowsAfter).toHaveLength(1);
    expect(relationshipRowsAfter[0]?.text()).toContain("TESTS");
    expect(relationshipRowsAfter[0]?.text()).toContain("TST-001");
  });

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
