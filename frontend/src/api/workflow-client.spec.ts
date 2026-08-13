import {
  describe,
  expect,
  it,
  vi,
} from "vitest";

import { ApiClient } from "./client";

describe("ApiClient workflow responses", () => {
  it("returns typed conflict responses for expected workflow states", async () => {
    const fetchImplementation =
      vi.fn<typeof fetch>().mockResolvedValue(
        new Response(
          JSON.stringify({
            status: "BRIEF_COMPLETE",
            round: null,
          }),
          {
            status: 409,
            headers: {
              "Content-Type":
                "application/json",
            },
          },
        ),
      );

    const client = new ApiClient(
      "/api/v1",
      fetchImplementation,
    );

    const result =
      await client.startProjectClarificationRound(
        "access-token",
        "project-id",
      );

    expect(result).toEqual({
      status: "BRIEF_COMPLETE",
      round: null,
    });

    expect(
      fetchImplementation,
    ).toHaveBeenCalledOnce();

    const [
      requestUrl,
      request,
    ] =
      fetchImplementation.mock.calls[0] ??
      [];

    expect(requestUrl).toBe(
      "/api/v1/projects/project-id/clarification-rounds",
    );
    expect(request?.method).toBe("POST");

    const headers =
      new Headers(request?.headers);

    expect(
      headers.get("Authorization"),
    ).toBe("Bearer access-token");
  });
});