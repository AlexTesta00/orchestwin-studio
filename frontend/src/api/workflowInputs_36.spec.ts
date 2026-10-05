import { describe, expect, it, vi } from "vitest";

import { createWorkflowInputsApi, WorkflowInputsApiError } from "./workflowInputs";

describe("workflow inputs HTTP contract", () => {
  it("preserves the prototype history envelope and its declared limits", async () => {
    const payload = { prototypes: [], limits: ["PROVIDED_PROTOTYPE_EVALUATION_UNAVAILABLE"] };
    const fetchImpl = vi
      .fn<typeof fetch>()
      .mockResolvedValue(new Response(JSON.stringify(payload)));
    const api = createWorkflowInputsApi({ fetchImpl });
    expect(await api.prototypes("project", "token")).toEqual(payload);
    expect(fetchImpl.mock.calls[0]?.[0]).toBe("/api/v1/projects/project/provided-prototypes");
    expect(fetchImpl.mock.calls[0]?.[1]?.method).toBe("GET");
  });
  it("reads without any mutation and preserves the portable envelope", async () => {
    const payload = {
      kind: "orchestwin.workflow-inputs",
      schema_version: 1,
      project_id: "owner project",
      decisions: [],
      prototypes: [],
      limits: [],
    };
    const fetchImpl = vi
      .fn<typeof fetch>()
      .mockResolvedValue(new Response(JSON.stringify(payload)));
    const api = createWorkflowInputsApi({ fetchImpl });
    expect(await api.read("owner project", "token")).toEqual(payload);
    expect(fetchImpl).toHaveBeenCalledWith(
      "/api/v1/projects/owner%20project/workflow-inputs",
      expect.objectContaining({
        method: "GET",
        credentials: "include",
        headers: { Accept: "application/json", Authorization: "Bearer token" },
      }),
    );
  });

  it("records a declared gap with the exact base context and reason", async () => {
    const fetchImpl = vi.fn<typeof fetch>().mockResolvedValue(new Response("{}"));
    const api = createWorkflowInputsApi({ fetchImpl });
    const body = {
      target: "JOURNEYS" as const,
      action: "DECLARE_MISSING" as const,
      reason: "Not researched\nOwner decision",
      base_context: {
        REQUIREMENTS: { artifact_id: "id", version_number: 4, content_hash: "a".repeat(64) },
      },
    };
    await api.decide("project", body, "token");
    expect(fetchImpl.mock.calls[0]?.[1]?.body).toBe(JSON.stringify(body));
    expect(fetchImpl.mock.calls[0]?.[1]?.method).toBe("POST");
  });

  it("uses the shared safe document route and exact revision decision", async () => {
    const fetchImpl = vi.fn<typeof fetch>().mockImplementation(async () => new Response("{}"));
    const api = createWorkflowInputsApi({ fetchImpl });
    await api.prototypeDocument("project", "prototype", "token", "SCR-002");
    await api.decidePrototype(
      "project",
      { action: "REQUEST_REVISION", reason: "Change labels" },
      "token",
    );
    expect(fetchImpl.mock.calls[0]?.[0]).toBe(
      "/api/v1/projects/project/provided-prototypes/prototype/document?entry_screen=SCR-002",
    );
    expect(fetchImpl.mock.calls[1]?.[1]?.body).toBe(
      JSON.stringify({ action: "REQUEST_REVISION", reason: "Change labels" }),
    );
  });

  it("exposes refusal codes and refuses an anonymous request before HTTP", async () => {
    const fetchImpl = vi.fn<typeof fetch>().mockResolvedValue(
      new Response(JSON.stringify({ detail: { code: "PROVIDED_PROTOTYPE_VERSION_CONFLICT" } }), {
        status: 409,
      }),
    );
    const api = createWorkflowInputsApi({ fetchImpl });
    await expect(api.read("project", "token")).rejects.toMatchObject({
      status: 409,
      code: "PROVIDED_PROTOTYPE_VERSION_CONFLICT",
    });
    await expect(api.read("project", " ")).rejects.toBeInstanceOf(WorkflowInputsApiError);
    expect(fetchImpl).toHaveBeenCalledTimes(1);
  });
});
