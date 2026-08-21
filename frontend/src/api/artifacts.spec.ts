import { describe, expect, it, vi } from "vitest";

import { ARTIFACT_GRAPH, ARTIFACT_GRAPH_PROJECT_ID } from "../test/artifactGraphFixtures";
import { ArtifactGraphApiError, createArtifactGraphApi } from "./artifacts";

function jsonResponse(payload: unknown, status = 200): Response {
  return {
    ok: status >= 200 && status < 300,
    status,
    text: async () => JSON.stringify(payload),
    blob: async () => new Blob([JSON.stringify(payload)], { type: "application/json" }),
  } as Response;
}

function firstCall<T>(values: readonly T[], label: string): T {
  const value = values[0];

  if (value === undefined) {
    throw new Error(`${label} was expected`);
  }

  return value;
}

describe("Artifact Graph API client", () => {
  it("loads the authenticated current cross-stage graph", async () => {
    const fetchMock = vi.fn(async () => jsonResponse(ARTIFACT_GRAPH));
    const api = createArtifactGraphApi({ fetchImpl: fetchMock });

    const result = await api.current(ARTIFACT_GRAPH_PROJECT_ID, "access-token");

    const [input, init] = firstCall(
      fetchMock.mock.calls as unknown as [RequestInfo | URL, RequestInit?][],
      "artifact graph fetch call",
    );
    expect(input).toBe(`/api/v1/projects/${ARTIFACT_GRAPH_PROJECT_ID}/artifacts/graph`);
    expect(init?.method).toBe("GET");
    expect(init?.credentials).toBe("include");
    expect(init?.headers).toMatchObject({
      Accept: "application/json",
      Authorization: "Bearer access-token",
    });
    expect(result).toEqual(ARTIFACT_GRAPH);
  });

  it("downloads the server-generated graph export", async () => {
    const fetchMock = vi.fn(async () => jsonResponse(ARTIFACT_GRAPH));
    const api = createArtifactGraphApi({ fetchImpl: fetchMock });

    const result = await api.exportCurrent(ARTIFACT_GRAPH_PROJECT_ID, "access-token");

    const [input] = firstCall(
      fetchMock.mock.calls as unknown as [RequestInfo | URL, RequestInit?][],
      "artifact graph export call",
    );
    expect(input).toBe(`/api/v1/projects/${ARTIFACT_GRAPH_PROJECT_ID}/artifacts/graph/export`);
    expect(result).toBeInstanceOf(Blob);
  });

  it("preserves typed owner-scoped lookup failures", async () => {
    const api = createArtifactGraphApi({
      fetchImpl: async () =>
        jsonResponse(
          {
            detail: {
              code: "ARTIFACT_GRAPH_NOT_FOUND",
            },
          },
          404,
        ),
    });

    await expect(api.current(ARTIFACT_GRAPH_PROJECT_ID, "access-token")).rejects.toEqual(
      expect.objectContaining({
        name: "ArtifactGraphApiError",
        status: 404,
        code: "ARTIFACT_GRAPH_NOT_FOUND",
      }),
    );
  });

  it("rejects requests without an in-memory access token", async () => {
    const api = createArtifactGraphApi({ fetchImpl: vi.fn() });

    await expect(api.current(ARTIFACT_GRAPH_PROJECT_ID, " ")).rejects.toBeInstanceOf(
      ArtifactGraphApiError,
    );
  });
});
