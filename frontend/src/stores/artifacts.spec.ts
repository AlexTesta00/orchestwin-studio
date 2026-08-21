import { createPinia, setActivePinia } from "pinia";
import { beforeEach, describe, expect, it } from "vitest";

import type { ArtifactGraphApi } from "../api/artifacts";
import { ARTIFACT_GRAPH, ARTIFACT_GRAPH_PROJECT_ID } from "../test/artifactGraphFixtures";
import type { CrossStageArtifactGraphPayload } from "../types/artifacts";
import { type AuthorizedRequest, useArtifactGraphStore } from "./artifacts";

const SECOND_PROJECT_ID = "00000000-0000-4000-8000-000000000299";

function fakeApi(): ArtifactGraphApi {
  return {
    current: async () => ARTIFACT_GRAPH,
    exportCurrent: async () =>
      new Blob([JSON.stringify(ARTIFACT_GRAPH)], { type: "application/json" }),
  };
}

const authorize: AuthorizedRequest = async <T>(
  operation: (accessToken: string) => Promise<T>,
): Promise<T> => operation("access-token");

describe("Artifact Graph store", () => {
  beforeEach(() => {
    setActivePinia(createPinia());
  });

  it("loads current graph counts and exact stage completion", async () => {
    const store = useArtifactGraphStore();

    await store.load(ARTIFACT_GRAPH_PROJECT_ID, authorize, fakeApi());

    expect(store.graph).toEqual(ARTIFACT_GRAPH);
    expect(store.nodeCount).toBe(ARTIFACT_GRAPH.nodes.length);
    expect(store.linkCount).toBe(ARTIFACT_GRAPH.links.length);
    expect(store.isCompleteThroughArchitecture).toBe(true);
    expect(store.error).toBeNull();
  });

  it("returns the server-generated export without storing binary data", async () => {
    const store = useArtifactGraphStore();

    const exported = await store.exportGraph(ARTIFACT_GRAPH_PROJECT_ID, authorize, fakeApi());

    expect(exported).toBeInstanceOf(Blob);
    expect(store.graph).toBeNull();
    expect(store.pending.export).toBe(false);
  });

  it("discards a stale graph response after the active project changes", async () => {
    let resolveGraph!: (value: CrossStageArtifactGraphPayload) => void;
    const delayedGraph = new Promise<CrossStageArtifactGraphPayload>((resolve) => {
      resolveGraph = resolve;
    });
    const api = fakeApi();
    api.current = async () => delayedGraph;
    const store = useArtifactGraphStore();
    const load = store.load(ARTIFACT_GRAPH_PROJECT_ID, authorize, api);

    store.activateProject(SECOND_PROJECT_ID);
    resolveGraph(ARTIFACT_GRAPH);
    await load;

    expect(store.projectId).toBe(SECOND_PROJECT_ID);
    expect(store.graph).toBeNull();
  });
});
