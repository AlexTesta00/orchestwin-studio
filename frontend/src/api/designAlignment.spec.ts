import { describe, expect, it, vi } from "vitest";

import {
  createDesignAlignmentApi,
  DesignAlignmentApiError,
  type DesignAlignmentPayload,
  type DesignRealignmentPayload,
} from "./designAlignment";

const PROJECT_ID = "11111111-1111-4111-8111-111111111111";
const ACCESS_TOKEN = "access-token";

const STATUS: DesignAlignmentPayload = {
  aligned: false,
  issue: null,
  design_version_number: 4,
  grounded_requirements_version_number: 2,
  requirements_version_number: 3,
  missing_codes: [],
  uncovered_codes: ["REQ-007"],
};

const REALIGNMENT: DesignRealignmentPayload = {
  version_id: "22222222-2222-4222-8222-222222222222",
  version_number: 5,
  based_on_version_number: 4,
  content_hash: "c".repeat(64),
  requirements_version_number: 3,
  gate_approval_required: true,
  uncovered_codes: ["REQ-007"],
};

function jsonResponse(payload: unknown, status = 200): Response {
  return new Response(JSON.stringify(payload), {
    status,
    headers: { "Content-Type": "application/json" },
  });
}

describe("Design Alignment API client", () => {
  it("reads the alignment of the design with an authenticated GET", async () => {
    const fetchImpl = vi.fn<typeof fetch>().mockResolvedValue(jsonResponse(STATUS));
    const api = createDesignAlignmentApi({ fetchImpl });

    const status = await api.status(PROJECT_ID, ACCESS_TOKEN);

    const call = fetchImpl.mock.calls[0];
    expect(call?.[0]).toBe(`/api/v1/projects/${PROJECT_ID}/design/requirements-alignment`);
    expect(call?.[1]?.method).toBe("GET");
    expect(call?.[1]?.credentials).toBe("include");
    expect(call?.[1]?.headers).toEqual({
      Accept: "application/json",
      Authorization: `Bearer ${ACCESS_TOKEN}`,
    });
    expect(call?.[1]).not.toHaveProperty("body");
    expect(status).toEqual(STATUS);
  });

  it("re-anchors the design with a POST without a body on a custom base path", async () => {
    const fetchImpl = vi.fn<typeof fetch>().mockResolvedValue(jsonResponse(REALIGNMENT, 201));
    const api = createDesignAlignmentApi({ basePath: "/studio/api/v1/", fetchImpl });

    const realignment = await api.realign("project 1", ACCESS_TOKEN);

    const call = fetchImpl.mock.calls[0];
    expect(call?.[0]).toBe("/studio/api/v1/projects/project%201/design/requirements-alignment");
    expect(call?.[1]?.method).toBe("POST");
    expect(call?.[1]?.credentials).toBe("include");
    expect(call?.[1]?.headers).toEqual({
      Accept: "application/json",
      Authorization: `Bearer ${ACCESS_TOKEN}`,
    });
    expect(call?.[1]).not.toHaveProperty("body");
    expect(realignment).toEqual(REALIGNMENT);
  });

  it("keeps the status, the code and the payload of a refusal", async () => {
    const missing = {
      detail: { code: "REQUIREMENT_NO_LONGER_AVAILABLE", missing_codes: ["REQ-003"] },
    };
    const fetchImpl = vi
      .fn<typeof fetch>()
      .mockResolvedValueOnce(jsonResponse(missing, 409))
      .mockResolvedValueOnce(jsonResponse({ detail: { code: "DESIGN_NOT_FOUND" } }, 404))
      .mockResolvedValueOnce(jsonResponse({ detail: "Not Found" }, 404))
      .mockResolvedValueOnce(new Response("Bad gateway", { status: 502 }));
    const api = createDesignAlignmentApi({ fetchImpl });

    const refused = api.realign(PROJECT_ID, ACCESS_TOKEN);
    await expect(refused).rejects.toBeInstanceOf(DesignAlignmentApiError);
    await expect(refused).rejects.toMatchObject({
      name: "DesignAlignmentApiError",
      status: 409,
      code: "REQUIREMENT_NO_LONGER_AVAILABLE",
      payload: missing,
    });
    await expect(api.status(PROJECT_ID, ACCESS_TOKEN)).rejects.toMatchObject({
      status: 404,
      code: "DESIGN_NOT_FOUND",
    });
    await expect(api.status(PROJECT_ID, ACCESS_TOKEN)).rejects.toMatchObject({
      status: 404,
      code: null,
    });
    await expect(api.status(PROJECT_ID, ACCESS_TOKEN)).rejects.toMatchObject({
      status: 502,
      code: null,
      payload: "Bad gateway",
    });
  });

  it("rejects a successful response whose body is not a JSON object", async () => {
    const fetchImpl = vi
      .fn<typeof fetch>()
      .mockResolvedValueOnce(new Response("<html>proxy error</html>", { status: 200 }))
      .mockResolvedValueOnce(jsonResponse([], 201));
    const api = createDesignAlignmentApi({ fetchImpl });

    await expect(api.status(PROJECT_ID, ACCESS_TOKEN)).rejects.toMatchObject({
      name: "DesignAlignmentApiError",
      status: 200,
      code: "INVALID_API_RESPONSE",
      payload: "<html>proxy error</html>",
    });
    await expect(api.realign(PROJECT_ID, ACCESS_TOKEN)).rejects.toMatchObject({
      status: 201,
      code: "INVALID_API_RESPONSE",
      payload: [],
    });
  });

  it("refuses to call the API without an access token", async () => {
    const fetchImpl = vi.fn<typeof fetch>();
    const api = createDesignAlignmentApi({ fetchImpl });

    await expect(api.status(PROJECT_ID, " ")).rejects.toBeInstanceOf(DesignAlignmentApiError);
    await expect(api.status(PROJECT_ID, "")).rejects.toMatchObject({
      status: 0,
      code: "ACCESS_TOKEN_REQUIRED",
    });
    await expect(api.realign(PROJECT_ID, "   ")).rejects.toMatchObject({
      code: "ACCESS_TOKEN_REQUIRED",
    });
    expect(fetchImpl).not.toHaveBeenCalled();
  });

  it("refuses an empty base path", () => {
    expect(() => createDesignAlignmentApi({ basePath: " / " })).toThrow(
      "Design Alignment API base path must not be empty",
    );
  });
});
