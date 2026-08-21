import { describe, expect, it, vi } from "vitest";

import { createArchitectureApi, ArchitectureApiError } from "./architecture";

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

describe("Architecture API client", () => {
  it("sends an authenticated request to the readiness endpoint", async () => {
    const fetchMock = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      void input;
      void init;

      return response({
        status: "ARCHITECTURE_REQUIRED",
        version: null,
        gate: null,
        has_package: false,
        approved_current_package: false,
      });
    });
    const api = createArchitectureApi({ fetchImpl: fetchMock });

    await api.readiness(PROJECT_ID, ACCESS_TOKEN);

    const [input, init] = firstCall(
      fetchMock.mock.calls as [RequestInfo | URL, RequestInit?][],
      "readiness fetch call",
    );

    expect(input).toBe(`/api/v1/projects/${PROJECT_ID}/architecture/readiness`);
    expect(init?.method).toBe("GET");
    expect(init?.credentials).toBe("include");
    expect(init?.headers).toMatchObject({
      Accept: "application/json",
      Authorization: `Bearer ${ACCESS_TOKEN}`,
    });
    expect(init).not.toHaveProperty("body");
  });

  it("serializes an owner decision for an Architecture Package diff", async () => {
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
    const api = createArchitectureApi({ fetchImpl: fetchMock });

    await api.decideRevision(
      PROJECT_ID,
      DIFF_ID,
      {
        decision: "REJECT",
        reason: "The test plan still misses a required integration check.",
      },
      ACCESS_TOKEN,
    );

    const [input, init] = firstCall(
      fetchMock.mock.calls as [RequestInfo | URL, RequestInit?][],
      "revision decision fetch call",
    );

    expect(input).toBe(`/api/v1/projects/${PROJECT_ID}/architecture/revisions/${DIFF_ID}/decision`);
    expect(init?.method).toBe("POST");
    expect(init?.body).toBe(
      JSON.stringify({
        decision: "REJECT",
        reason: "The test plan still misses a required integration check.",
      }),
    );
  });

  it("preserves backend governance conflict codes", async () => {
    const api = createArchitectureApi({
      fetchImpl: async () =>
        response(
          {
            detail: {
              code: "DESIGN_APPROVAL_REQUIRED",
            },
          },
          409,
        ),
    });

    await expect(api.generate(PROJECT_ID, ACCESS_TOKEN)).rejects.toEqual(
      expect.objectContaining({
        name: "ArchitectureApiError",
        status: 409,
        code: "DESIGN_APPROVAL_REQUIRED",
      }),
    );
  });

  it("rejects requests without an in-memory access token", async () => {
    const api = createArchitectureApi({ fetchImpl: vi.fn() });

    await expect(api.history(PROJECT_ID, " ")).rejects.toBeInstanceOf(ArchitectureApiError);
  });
});
