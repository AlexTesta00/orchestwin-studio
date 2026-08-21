import { describe, expect, it, vi } from "vitest";

import { createDesignApi, DesignApiError } from "./design";

const PROJECT_ID = "00000000-0000-4000-8000-000000000010";
const DIFF_ID = "00000000-0000-4000-8000-000000000020";
const ACCESS_TOKEN = "access-token";

function response(payload: unknown, status = 200): Response {
  return {
    ok: status >= 200 && status < 300,
    status,
    text: async () => JSON.stringify(payload),
  } as Response;
}

function firstCall<T>(values: readonly T[], label: string): T {
  const value = values[0];

  if (value === undefined) {
    throw new Error(`${label} was expected`);
  }

  return value;
}

describe("Design API client", () => {
  it("sends an authenticated request to the readiness endpoint", async () => {
    const fetchMock = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      void input;
      void init;

      return response({
        status: "DESIGN_REQUIRED",
        version: null,
        gate: null,
        has_package: false,
        package_ready_for_gate: false,
        approved_current_package: false,
      });
    });
    const api = createDesignApi({
      fetchImpl: fetchMock,
    });

    await api.readiness(PROJECT_ID, ACCESS_TOKEN);

    const [input, init] = firstCall(
      fetchMock.mock.calls as [RequestInfo | URL, RequestInit?][],
      "readiness fetch call",
    );

    expect(input).toBe(`/api/v1/projects/${PROJECT_ID}/design/readiness`);
    expect(init?.method).toBe("GET");
    expect(init?.credentials).toBe("include");
    expect(init?.headers).toMatchObject({
      Accept: "application/json",
      Authorization: `Bearer ${ACCESS_TOKEN}`,
    });
    expect(init).not.toHaveProperty("body");
  });

  it("serializes an owner decision for a Design Package diff", async () => {
    const fetchMock = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      void input;
      void init;

      return response({
        status: "APPLIED",
        diff: null,
        version: null,
        issue: null,
        domain_issue: null,
        diff_persistence_status: null,
        version_persistence_status: null,
      });
    });
    const api = createDesignApi({
      fetchImpl: fetchMock,
    });

    await api.decideRevision(
      PROJECT_ID,
      DIFF_ID,
      {
        decision: "REJECT",
        reason: "The selected workflow still needs revision.",
      },
      ACCESS_TOKEN,
    );

    const [input, init] = firstCall(
      fetchMock.mock.calls as [RequestInfo | URL, RequestInit?][],
      "revision decision fetch call",
    );

    expect(input).toBe(`/api/v1/projects/${PROJECT_ID}/design/revisions/${DIFF_ID}/decision`);
    expect(init?.method).toBe("POST");
    expect(init?.body).toBe(
      JSON.stringify({
        decision: "REJECT",
        reason: "The selected workflow still needs revision.",
      }),
    );
  });

  it("preserves backend governance conflict codes", async () => {
    const api = createDesignApi({
      fetchImpl: async () =>
        response(
          {
            detail: {
              code: "REQUIREMENTS_APPROVAL_REQUIRED",
            },
          },
          409,
        ),
    });

    await expect(api.generate(PROJECT_ID, ACCESS_TOKEN)).rejects.toEqual(
      expect.objectContaining({
        name: "DesignApiError",
        status: 409,
        code: "REQUIREMENTS_APPROVAL_REQUIRED",
      }),
    );
  });

  it("rejects requests without an in-memory access token", async () => {
    const api = createDesignApi({
      fetchImpl: vi.fn(),
    });

    await expect(api.history(PROJECT_ID, " ")).rejects.toBeInstanceOf(DesignApiError);
  });
});
