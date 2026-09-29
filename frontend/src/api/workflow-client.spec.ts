import { describe, expect, it, vi } from "vitest";

import { ApiClient } from "./client";

describe("ApiClient workflow responses", () => {
  it("returns typed conflict responses for expected workflow states", async () => {
    const fetchImplementation = vi.fn<typeof fetch>().mockResolvedValue(
      new Response(
        JSON.stringify({
          status: "FIELD_ALREADY_PROVIDED",
          assumption: null,
        }),
        {
          status: 409,
          headers: {
            "Content-Type": "application/json",
          },
        },
      ),
    );

    const client = new ApiClient("/api/v1", fetchImplementation);

    const result = await client.createProjectBriefAssumption("access-token", "project-id", {
      field: "budget",
      statement: "Approximately EUR 5,000.",
    });

    expect(result).toEqual({
      status: "FIELD_ALREADY_PROVIDED",
      assumption: null,
    });

    expect(fetchImplementation).toHaveBeenCalledOnce();

    const [requestUrl, request] = fetchImplementation.mock.calls[0] ?? [];

    expect(requestUrl).toBe("/api/v1/projects/project-id/brief-assumptions");
    expect(request?.method).toBe("POST");
    expect(JSON.parse(String(request?.body))).toEqual({
      field: "budget",
      statement: "Approximately EUR 5,000.",
    });

    const headers = new Headers(request?.headers);

    expect(headers.get("Authorization")).toBe("Bearer access-token");
  });

  it("accepts every proposal through its own route and keeps the typed conflict", async () => {
    const fetchImplementation = vi.fn<typeof fetch>().mockResolvedValue(
      new Response(
        JSON.stringify({
          status: "NOTHING_TO_ACCEPT",
          accepted: [],
          skipped: [],
          brief_version: null,
        }),
        {
          status: 409,
          headers: {
            "Content-Type": "application/json",
          },
        },
      ),
    );

    const client = new ApiClient("/api/v1", fetchImplementation);

    const result = await client.acceptAllProjectBriefAssumptions("access-token", "project-id");

    expect(result).toEqual({
      status: "NOTHING_TO_ACCEPT",
      accepted: [],
      skipped: [],
      brief_version: null,
    });

    const [requestUrl, request] = fetchImplementation.mock.calls[0] ?? [];

    expect(requestUrl).toBe("/api/v1/projects/project-id/brief-assumptions/accept-all");
    expect(request?.method).toBe("POST");
    expect(JSON.parse(String(request?.body))).toEqual({ reason: null });
    expect(new Headers(request?.headers).get("Authorization")).toBe("Bearer access-token");
  });

  it("encodes every identifier placed in a path", async () => {
    const fetchImplementation = vi
      .fn<typeof fetch>()
      .mockImplementation(async () => new Response(JSON.stringify({}), { status: 200 }));
    const client = new ApiClient("/api/v1", fetchImplementation);

    await client.getProject("access-token", "../auth/logout");
    await client.acceptProjectBriefAssumption("access-token", "../auth/logout", "a/b?c#d");
    await client.acceptAllProjectBriefAssumptions("access-token", "../auth/logout", "Confirmed.");
    await client.rejectProjectBriefAssumption("access-token", "project-id", "a/b", "No.");
    await client.listProjectBriefGateEvents("access-token", "project-id", "../gate");
    await client.listAgentTeamGateEvents("access-token", "project-id", "../gate");

    expect(fetchImplementation.mock.calls.map(([requestUrl]) => requestUrl)).toEqual([
      "/api/v1/projects/..%2Fauth%2Flogout",
      "/api/v1/projects/..%2Fauth%2Flogout/brief-assumptions/a%2Fb%3Fc%23d/accept",
      "/api/v1/projects/..%2Fauth%2Flogout/brief-assumptions/accept-all",
      "/api/v1/projects/project-id/brief-assumptions/a%2Fb/reject",
      "/api/v1/projects/project-id/gates/project-brief/..%2Fgate/events",
      "/api/v1/projects/project-id/gates/agent-team/..%2Fgate/events",
    ]);
  });
});
