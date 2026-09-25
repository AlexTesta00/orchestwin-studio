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
});
