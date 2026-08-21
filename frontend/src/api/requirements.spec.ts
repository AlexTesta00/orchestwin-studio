import { describe, expect, it, vi } from "vitest";

import { createRequirementsApi, RequirementsApiError } from "./requirements";

const PROJECT_ID = "00000000-0000-4000-8000-000000000010";
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

describe("Requirements API client", () => {
  it("sends an authenticated request to the readiness endpoint", async () => {
    const fetchMock = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      void input;
      void init;

      return response({
        status: "REQUIREMENTS_REQUIRED",
        version: null,
        gate: null,
        approved_current_specification: false,
      });
    });
    const api = createRequirementsApi({
      fetchImpl: fetchMock,
    });

    await api.readiness(PROJECT_ID, ACCESS_TOKEN);

    const [input, init] = firstCall(
      fetchMock.mock.calls as [RequestInfo | URL, RequestInit?][],
      "readiness fetch call",
    );

    expect(input).toBe(`/api/v1/projects/${PROJECT_ID}/requirements/readiness`);
    expect(init?.method).toBe("GET");
    expect(init?.credentials).toBe("include");
    expect(init?.headers).toMatchObject({
      Accept: "application/json",
      Authorization: `Bearer ${ACCESS_TOKEN}`,
    });
    expect(init).not.toHaveProperty("body");
  });

  it("serializes a Gate 4 decision request", async () => {
    const fetchMock = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      void input;
      void init;

      return response({
        status: "APPLIED",
        gate: null,
        event: null,
        issue: null,
      });
    });
    const api = createRequirementsApi({
      fetchImpl: fetchMock,
    });

    await api.decideGate(
      PROJECT_ID,
      {
        action: "REQUEST_REVISION",
        reason: "Add measurable acceptance criteria.",
      },
      ACCESS_TOKEN,
    );

    const [input, init] = firstCall(
      fetchMock.mock.calls as [RequestInfo | URL, RequestInit?][],
      "decision fetch call",
    );

    expect(input).toBe(`/api/v1/projects/${PROJECT_ID}/requirements/gate/decision`);
    expect(init?.method).toBe("POST");
    expect(init?.body).toBe(
      JSON.stringify({
        action: "REQUEST_REVISION",
        reason: "Add measurable acceptance criteria.",
      }),
    );
  });

  it("preserves backend conflict codes", async () => {
    const api = createRequirementsApi({
      fetchImpl: async () =>
        response(
          {
            detail: {
              code: "USER_MODELING_APPROVAL_REQUIRED",
            },
          },
          409,
        ),
    });

    await expect(api.generate(PROJECT_ID, ACCESS_TOKEN)).rejects.toEqual(
      expect.objectContaining({
        name: "RequirementsApiError",
        status: 409,
        code: "USER_MODELING_APPROVAL_REQUIRED",
      }),
    );
  });

  it("rejects requests without an in-memory access token", async () => {
    const api = createRequirementsApi({
      fetchImpl: vi.fn(),
    });

    await expect(api.history(PROJECT_ID, " ")).rejects.toBeInstanceOf(RequirementsApiError);
  });
});
