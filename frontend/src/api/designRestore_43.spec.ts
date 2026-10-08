import { describe, expect, it, vi } from "vitest";

import {
  createDesignRestoreApi,
  DesignRestoreApiError,
  type DesignRestorePayload,
} from "./designRestore";
import { SELECTED_DESIGN_VERSION } from "../test/designFixtures";

const PROJECT_ID = "11111111-1111-4111-8111-111111111111";
const ACCESS_TOKEN = "access-token";

const RESTORED: DesignRestorePayload = {
  reason: "RESTORED",
  restored_version_number: 2,
  note: "Ripristino della versione 2",
  revision: {
    status: "APPLIED",
    diff: null,
    version: { ...SELECTED_DESIGN_VERSION, version_number: 4, based_on_version_number: 3 },
    issue: null,
    domain_issue: null,
    diff_persistence_status: null,
    version_persistence_status: null,
  },
};

function jsonResponse(payload: unknown, status = 201): Response {
  return new Response(JSON.stringify(payload), {
    status,
    headers: { "Content-Type": "application/json" },
  });
}

describe("Design Restore API client", () => {
  it("asks for a past version with an authenticated POST that carries the number and the locale", async () => {
    const fetchImpl = vi.fn<typeof fetch>().mockResolvedValue(jsonResponse(RESTORED));
    const api = createDesignRestoreApi({ fetchImpl });

    const answer = await api.restore(
      PROJECT_ID,
      { version_number: 2, locale: "it-IT" },
      ACCESS_TOKEN,
    );

    const call = fetchImpl.mock.calls[0];
    expect(fetchImpl).toHaveBeenCalledTimes(1);
    expect(call?.[0]).toBe(`/api/v1/projects/${PROJECT_ID}/design/revisions/restore`);
    expect(call?.[1]?.method).toBe("POST");
    expect(call?.[1]?.credentials).toBe("include");
    expect(call?.[1]?.headers).toEqual({
      Accept: "application/json",
      Authorization: `Bearer ${ACCESS_TOKEN}`,
      "Content-Type": "application/json",
    });
    expect(JSON.parse(String(call?.[1]?.body))).toEqual({ version_number: 2, locale: "it-IT" });
    expect(answer).toEqual(RESTORED);
  });

  it("encodes the project and keeps a custom base path", async () => {
    const fetchImpl = vi.fn<typeof fetch>().mockResolvedValue(jsonResponse(RESTORED));
    const api = createDesignRestoreApi({ basePath: "/studio/api/v1/", fetchImpl });

    await api.restore("project 1", { version_number: 1, locale: "en-US" }, ACCESS_TOKEN);

    expect(fetchImpl.mock.calls[0]?.[0]).toBe(
      "/studio/api/v1/projects/project%201/design/revisions/restore",
    );
  });

  it("keeps the status, the code and the payload of a refusal", async () => {
    const current = { detail: { code: "DESIGN_RESTORE_CURRENT" } };
    const fetchImpl = vi
      .fn<typeof fetch>()
      .mockResolvedValueOnce(jsonResponse(current, 409))
      .mockResolvedValueOnce(jsonResponse({ detail: { code: "DESIGN_VERSION_NOT_FOUND" } }, 404))
      .mockResolvedValueOnce(jsonResponse({ detail: [{ type: "greater_than_equal" }] }, 422))
      .mockResolvedValueOnce(new Response("Bad gateway", { status: 502 }));
    const api = createDesignRestoreApi({ fetchImpl });
    const body = { version_number: 2, locale: "en-US" };

    const refused = api.restore(PROJECT_ID, body, ACCESS_TOKEN);
    await expect(refused).rejects.toBeInstanceOf(DesignRestoreApiError);
    await expect(refused).rejects.toMatchObject({
      name: "DesignRestoreApiError",
      status: 409,
      code: "DESIGN_RESTORE_CURRENT",
      payload: current,
    });
    await expect(api.restore(PROJECT_ID, body, ACCESS_TOKEN)).rejects.toMatchObject({
      status: 404,
      code: "DESIGN_VERSION_NOT_FOUND",
    });
    await expect(api.restore(PROJECT_ID, body, ACCESS_TOKEN)).rejects.toMatchObject({
      status: 422,
      code: null,
    });
    await expect(api.restore(PROJECT_ID, body, ACCESS_TOKEN)).rejects.toMatchObject({
      status: 502,
      code: null,
      payload: "Bad gateway",
    });
  });

  it("refuses an answer that does not carry the new version", async () => {
    const fetchImpl = vi
      .fn<typeof fetch>()
      .mockResolvedValueOnce(new Response("<html>proxy</html>", { status: 201 }))
      .mockResolvedValueOnce(
        jsonResponse({ ...RESTORED, revision: { ...RESTORED.revision, version: null } }),
      );
    const api = createDesignRestoreApi({ fetchImpl });
    const body = { version_number: 2, locale: "en-US" };

    await expect(api.restore(PROJECT_ID, body, ACCESS_TOKEN)).rejects.toMatchObject({
      name: "DesignRestoreApiError",
      status: 201,
      code: "INVALID_API_RESPONSE",
    });
    await expect(api.restore(PROJECT_ID, body, ACCESS_TOKEN)).rejects.toMatchObject({
      code: "INVALID_API_RESPONSE",
    });
  });

  it("refuses to call the Studio without an access token", async () => {
    const fetchImpl = vi.fn<typeof fetch>();
    const api = createDesignRestoreApi({ fetchImpl });

    await expect(
      api.restore(PROJECT_ID, { version_number: 2, locale: "en-US" }, "  "),
    ).rejects.toMatchObject({ status: 0, code: "ACCESS_TOKEN_REQUIRED" });
    expect(fetchImpl).not.toHaveBeenCalled();
  });
});
