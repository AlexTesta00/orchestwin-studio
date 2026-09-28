import { describe, expect, it, vi } from "vitest";

import type {
  RequirementsAlignmentPayload,
  RequirementsRealignmentPayload,
} from "../types/requirementsAlignment";
import {
  createRequirementsAlignmentApi,
  RequirementsAlignmentApiError,
} from "./requirementsAlignment";

const PROJECT_ID = "11111111-1111-4111-8111-111111111111";
const ACCESS_TOKEN = "access-token";

const STATUS: RequirementsAlignmentPayload = {
  aligned: false,
  issue: null,
  requirements_version_number: 2,
  snapshot_version_number: 3,
  twins_approved: true,
};

const REALIGNMENT: RequirementsRealignmentPayload = {
  version_id: "22222222-2222-4222-8222-222222222222",
  version_number: 3,
  based_on_version_number: 2,
  content_hash: "c".repeat(64),
  user_modeling_version_number: 3,
  twin_count: 5,
  gate_approval_required: true,
};

function jsonResponse(payload: unknown, status = 200): Response {
  return new Response(JSON.stringify(payload), {
    status,
    headers: { "Content-Type": "application/json" },
  });
}

describe("Requirements Alignment API client", () => {
  it("reads the alignment of the requirements with an authenticated GET", async () => {
    const fetchImpl = vi.fn<typeof fetch>().mockResolvedValue(jsonResponse(STATUS));
    const api = createRequirementsAlignmentApi({ fetchImpl });

    const status = await api.status(PROJECT_ID, ACCESS_TOKEN);

    const call = fetchImpl.mock.calls[0];
    expect(call?.[0]).toBe(`/api/v1/projects/${PROJECT_ID}/requirements/twin-alignment`);
    expect(call?.[1]?.method).toBe("GET");
    expect(call?.[1]?.credentials).toBe("include");
    expect(call?.[1]?.headers).toEqual({
      Accept: "application/json",
      Authorization: `Bearer ${ACCESS_TOKEN}`,
    });
    expect(status).toEqual(STATUS);
  });

  it("updates the requirements with a POST without a body on a custom base path", async () => {
    const fetchImpl = vi.fn<typeof fetch>().mockResolvedValue(jsonResponse(REALIGNMENT, 201));
    const api = createRequirementsAlignmentApi({ basePath: "/studio/api/v1/", fetchImpl });

    const realignment = await api.realign("project 1", ACCESS_TOKEN);

    const call = fetchImpl.mock.calls[0];
    expect(call?.[0]).toBe("/studio/api/v1/projects/project%201/requirements/twin-alignment");
    expect(call?.[1]?.method).toBe("POST");
    expect(call?.[1]?.credentials).toBe("include");
    expect(call?.[1]?.headers).toEqual({
      Accept: "application/json",
      Authorization: `Bearer ${ACCESS_TOKEN}`,
    });
    expect(call?.[1]).not.toHaveProperty("body");
    expect(realignment).toEqual(REALIGNMENT);
  });

  it("preserves the status and the code of a refused update", async () => {
    const fetchImpl = vi
      .fn<typeof fetch>()
      .mockResolvedValueOnce(
        jsonResponse({ detail: { code: "USER_TWINS_APPROVAL_REQUIRED" } }, 409),
      )
      .mockResolvedValueOnce(jsonResponse({ detail: { code: "REQUIREMENTS_NOT_FOUND" } }, 404))
      .mockResolvedValueOnce(new Response("Bad gateway", { status: 502 }));
    const api = createRequirementsAlignmentApi({ fetchImpl });

    const refused = api.realign(PROJECT_ID, ACCESS_TOKEN);
    await expect(refused).rejects.toBeInstanceOf(RequirementsAlignmentApiError);
    await expect(refused).rejects.toMatchObject({
      name: "RequirementsAlignmentApiError",
      status: 409,
      code: "USER_TWINS_APPROVAL_REQUIRED",
    });
    await expect(api.realign(PROJECT_ID, ACCESS_TOKEN)).rejects.toMatchObject({
      status: 404,
      code: "REQUIREMENTS_NOT_FOUND",
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
    const api = createRequirementsAlignmentApi({ fetchImpl });

    await expect(api.status(PROJECT_ID, ACCESS_TOKEN)).rejects.toMatchObject({
      name: "RequirementsAlignmentApiError",
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
    const api = createRequirementsAlignmentApi({ fetchImpl });

    await expect(api.status(PROJECT_ID, " ")).rejects.toBeInstanceOf(RequirementsAlignmentApiError);
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
    expect(() => createRequirementsAlignmentApi({ basePath: " / " })).toThrow(
      "Requirements Alignment API base path must not be empty",
    );
  });
});
