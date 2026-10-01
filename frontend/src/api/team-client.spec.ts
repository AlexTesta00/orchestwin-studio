import { describe, expect, it, vi } from "vitest";

import { ApiClient } from "./client";
import type { PerspectiveView, TeamSelectionIssueResponse } from "./team-contracts";

const CONTRADICTION: TeamSelectionIssueResponse = {
  code: "CONTRADICTORY_ROLE_SIGNALS",
  agent_id: "BACKEND_ENGINEER",
  mandatory_reasons: [
    {
      code: "BACKEND_DELIVERY_SIGNAL",
      evidence: { fields: ["technical_constraints"], terms: ["api"] },
    },
  ],
  impossible_reasons: [
    {
      code: "EXPLICIT_SCOPE_EXCLUSION",
      evidence: { fields: ["description"], terms: ["senza server"] },
    },
  ],
};

const SECURITY: PerspectiveView = {
  key: "SECURITY",
  standing: "OPTIONAL",
  applied: false,
  editable: true,
  agent_id: "SECURITY_REVIEWER",
  requested: { fields: [], terms: [] },
  excluded: { fields: [], terms: [] },
  aspects: [],
};

function jsonResponse(payload: unknown, status: number): Response {
  return new Response(JSON.stringify(payload), {
    status,
    headers: {
      "Content-Type": "application/json",
    },
  });
}

describe("ApiClient team workflow responses", () => {
  it("returns typed conflict responses for expected team states", async () => {
    const fetchImplementation = vi.fn<typeof fetch>().mockResolvedValue(
      jsonResponse(
        {
          status: "BRIEF_NOT_APPROVED",
          version: null,
          issues: [],
        },
        409,
      ),
    );

    const client = new ApiClient("/api/v1", fetchImplementation);

    const result = await client.generateProjectTeamProposal("access-token", "project-id");

    expect(result).toEqual({
      status: "BRIEF_NOT_APPROVED",
      version: null,
      issues: [],
    });

    const [requestUrl, request] = fetchImplementation.mock.calls[0] ?? [];

    expect(requestUrl).toBe("/api/v1/projects/project-id/team-proposals");
    expect(request?.method).toBe("POST");

    const headers = new Headers(request?.headers);

    expect(headers.get("Authorization")).toBe("Bearer access-token");
  });

  it("returns a created version with its perspectives when the brief contradicts itself", async () => {
    const payload = {
      status: "CREATED",
      version: {
        id: "proposal-id",
        version_number: 1,
        selected_agent_ids: ["REQUIREMENTS_ANALYST"],
        constraint_issues: [CONTRADICTION],
        perspectives: [SECURITY],
      },
      issues: [CONTRADICTION],
    };
    const fetchImplementation = vi.fn<typeof fetch>().mockResolvedValue(jsonResponse(payload, 201));

    const client = new ApiClient("/api/v1", fetchImplementation);

    const result = await client.generateProjectTeamProposal("access-token", "project-id");

    expect(result).toEqual(payload);
    expect(result.status).toBe("CREATED");
    expect(result.issues).toEqual([CONTRADICTION]);
    expect(result.version?.perspectives).toEqual([SECURITY]);
  });

  it("sends the complete selection without any rationale when the owner switches a perspective", async () => {
    const fetchImplementation = vi.fn<typeof fetch>().mockResolvedValue(
      jsonResponse(
        {
          status: "UPDATED",
          version: null,
          issues: [],
          events: [],
        },
        201,
      ),
    );

    const client = new ApiClient("/api/v1", fetchImplementation);

    const result = await client.editCurrentProjectTeamProposal("access-token", "project-id", {
      selected_agent_ids: ["REQUIREMENTS_ANALYST", "SECURITY_REVIEWER"],
    });

    expect(result.status).toBe("UPDATED");

    const [requestUrl, request] = fetchImplementation.mock.calls[0] ?? [];

    expect(requestUrl).toBe("/api/v1/projects/project-id/team-proposals/current");
    expect(request?.method).toBe("PATCH");
    expect(request?.body).toBe(
      '{"selected_agent_ids":["REQUIREMENTS_ANALYST","SECURITY_REVIEWER"]}',
    );
  });

  it("returns typed validation responses for rejected team edits", async () => {
    const fetchImplementation = vi.fn<typeof fetch>().mockResolvedValue(
      jsonResponse(
        {
          status: "REJECTED",
          version: null,
          issues: [
            {
              code: "AGENT_NOT_SELECTABLE",
              agent_id: "INTEGRATION_ENGINEER",
            },
          ],
          events: [],
        },
        422,
      ),
    );

    const client = new ApiClient("/api/v1", fetchImplementation);

    const result = await client.editCurrentProjectTeamProposal("access-token", "project-id", {
      selected_agent_ids: ["REQUIREMENTS_ANALYST", "INTEGRATION_ENGINEER"],
    });

    expect(result.status).toBe("REJECTED");
    expect(result.issues).toEqual([
      {
        code: "AGENT_NOT_SELECTABLE",
        agent_id: "INTEGRATION_ENGINEER",
      },
    ]);
  });
});
