import { describe, expect, it, vi } from "vitest";

import type { ProjectDiagramsPayload } from "../types/diagrams";
import { createDiagramsApi, DiagramsApiError } from "./diagrams";

const PROJECT_ID = "11111111-1111-4111-8111-111111111111";

const DIAGRAMS: ProjectDiagramsPayload = {
  project_id: PROJECT_ID,
  locale: "it",
  mermaid_version: "12.0.0",
  system_name: "Reception desk",
  requirements: {
    version_id: "22222222-2222-4222-8222-222222222222",
    version_number: 2,
    content_hash: "a".repeat(64),
  },
  design: null,
  diagrams: [
    {
      key: "requirements/use-cases",
      stage: "requirements",
      kind: "USE_CASES",
      subject: null,
      title: "Casi d'uso",
      description: "Chi usa il sistema e per fare cosa.",
      path: "diagrams/requirements/use-cases.mmd",
      source: "flowchart LR\n  receptionist --> checkin",
    },
  ],
};

function jsonResponse(payload: unknown, status = 200): Response {
  return new Response(JSON.stringify(payload), {
    status,
    headers: { "Content-Type": "application/json" },
  });
}

describe("Diagrams API client", () => {
  it("loads the diagrams of the project in the requested locale", async () => {
    const fetchImpl = vi.fn<typeof fetch>().mockImplementation(async () => jsonResponse(DIAGRAMS));
    const api = createDiagramsApi({ fetchImpl });

    const result = await api.current(PROJECT_ID, "it", "access-token");

    expect(fetchImpl).toHaveBeenCalledTimes(1);
    const call = fetchImpl.mock.calls[0];
    expect(call?.[0]).toBe(`/api/v1/projects/${PROJECT_ID}/diagrams?locale=it`);
    expect(call?.[1]?.method).toBe("GET");
    expect(call?.[1]?.credentials).toBe("include");
    expect(call?.[1]?.headers).toEqual({
      Accept: "application/json",
      Authorization: "Bearer access-token",
    });
    expect(call?.[1]).not.toHaveProperty("body");
    expect(result).toEqual(DIAGRAMS);
  });

  it("sends the English locale and encodes the project id under a custom base path", async () => {
    const fetchImpl = vi.fn<typeof fetch>().mockImplementation(async () => jsonResponse(DIAGRAMS));
    const api = createDiagramsApi({ basePath: "/studio/api/v1/", fetchImpl });

    await api.current("project 1", "en", "access-token");

    expect(fetchImpl.mock.calls[0]?.[0]).toBe(
      "/studio/api/v1/projects/project%201/diagrams?locale=en",
    );
  });

  it("preserves the typed code when the project has no requirements yet", async () => {
    const fetchImpl = vi
      .fn<typeof fetch>()
      .mockImplementation(async () =>
        jsonResponse({ detail: { code: "DIAGRAMS_NOT_FOUND" } }, 404),
      );
    const api = createDiagramsApi({ fetchImpl });

    const failure = api.current(PROJECT_ID, "en", "access-token");

    await expect(failure).rejects.toBeInstanceOf(DiagramsApiError);
    await expect(failure).rejects.toMatchObject({
      name: "DiagramsApiError",
      status: 404,
      code: "DIAGRAMS_NOT_FOUND",
    });
  });

  it("rejects a successful response whose body is not a JSON object", async () => {
    const fetchImpl = vi
      .fn<typeof fetch>()
      .mockResolvedValueOnce(new Response("<html>proxy error</html>", { status: 200 }))
      .mockResolvedValueOnce(jsonResponse([]));
    const api = createDiagramsApi({ fetchImpl });

    await expect(api.current(PROJECT_ID, "en", "access-token")).rejects.toMatchObject({
      name: "DiagramsApiError",
      status: 200,
      code: "INVALID_API_RESPONSE",
      payload: "<html>proxy error</html>",
    });
    await expect(api.current(PROJECT_ID, "en", "access-token")).rejects.toMatchObject({
      code: "INVALID_API_RESPONSE",
      payload: [],
    });
  });

  it("refuses to call the API without an access token", async () => {
    const fetchImpl = vi.fn<typeof fetch>();
    const api = createDiagramsApi({ fetchImpl });

    const failure = api.current(PROJECT_ID, "it", "   ");

    await expect(failure).rejects.toBeInstanceOf(DiagramsApiError);
    await expect(failure).rejects.toMatchObject({ status: 0, code: "ACCESS_TOKEN_REQUIRED" });
    expect(fetchImpl).not.toHaveBeenCalled();
  });
});
