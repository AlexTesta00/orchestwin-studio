import {
  describe,
  expect,
  it,
  vi,
} from "vitest";

import { ApiClient } from "./client";

describe("ApiClient team workflow responses", () => {
  it("returns typed conflict responses for expected team states", async () => {
    const fetchImplementation =
      vi.fn<typeof fetch>().mockResolvedValue(
        new Response(
          JSON.stringify({
            status:
              "BRIEF_NOT_APPROVED",
            version: null,
            issues: [],
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
      await client.generateProjectTeamProposal(
        "access-token",
        "project-id",
      );

    expect(result).toEqual({
      status:
        "BRIEF_NOT_APPROVED",
      version: null,
      issues: [],
    });

    const [
      requestUrl,
      request,
    ] =
      fetchImplementation.mock.calls[0] ??
      [];

    expect(requestUrl).toBe(
      "/api/v1/projects/project-id/team-proposals",
    );
    expect(request?.method).toBe("POST");

    const headers =
      new Headers(request?.headers);

    expect(
      headers.get("Authorization"),
    ).toBe("Bearer access-token");
  });

  it("returns typed validation responses for rejected team edits", async () => {
    const fetchImplementation =
      vi.fn<typeof fetch>().mockResolvedValue(
        new Response(
          JSON.stringify({
            status: "REJECTED",
            version: null,
            issues: [
              {
                code:
                  "RATIONALE_REQUIRED",
                agent_id:
                  "MOBILE_ENGINEER",
              },
            ],
            events: [],
          }),
          {
            status: 422,
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
      await client.editCurrentProjectTeamProposal(
        "access-token",
        "project-id",
        {
          selected_agent_ids: [
            "MOBILE_ENGINEER",
          ],
          owner_rationales: [],
        },
      );

    expect(result.status).toBe(
      "REJECTED",
    );
    expect(result.issues).toEqual([
      {
        code:
          "RATIONALE_REQUIRED",
        agent_id:
          "MOBILE_ENGINEER",
      },
    ]);
  });
});