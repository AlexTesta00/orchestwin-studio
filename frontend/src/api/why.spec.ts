import { describe, expect, it, vi } from "vitest";
import { whyAnswer, whyDocument } from "../test/whyFixtures";
import { createWhyApi, WhyApiError } from "./why";

function response(payload: unknown, status = 200): Response {
  return { ok: status < 400, status, json: async () => payload } as Response;
}

describe("Why API", () => {
  it("reads an encoded exact selector and the document with the current access token", async () => {
    const fetchImpl = vi
      .fn()
      .mockResolvedValueOnce(response(whyAnswer()))
      .mockResolvedValueOnce(response(whyDocument([])));
    const api = createWhyApi({ fetchImpl });
    await api.explain("project/a", "USER_TWIN_CLAIM:id:2:hash:user_twin.goals", " token ");
    await api.document("project/a", "token");
    expect(fetchImpl.mock.calls[0]?.[0]).toBe(
      "/api/v1/projects/project%2Fa/artifacts/why?code=USER_TWIN_CLAIM%3Aid%3A2%3Ahash%3Auser_twin.goals",
    );
    expect(fetchImpl.mock.calls[1]?.[0]).toBe(
      "/api/v1/projects/project%2Fa/artifacts/why/document",
    );
    expect(fetchImpl.mock.calls[0]?.[1]).toEqual({
      method: "GET",
      credentials: "include",
      headers: { Accept: "application/json", Authorization: "Bearer token" },
    });
  });

  it.each([404, 409, 422])("preserves the %s status and ambiguity candidates", async (status) => {
    const payload = { detail: { code: "WHY_CODE_AMBIGUOUS", candidates: ["a", "b"] } };
    const api = createWhyApi({ fetchImpl: vi.fn().mockResolvedValue(response(payload, status)) });
    await expect(api.explain("project", "ELM-001", "token")).rejects.toMatchObject({
      status,
      code: "WHY_CODE_AMBIGUOUS",
      payload,
    });
  });

  it("rejects missing authentication before any request and malformed successful documents", async () => {
    const fetchImpl = vi
      .fn()
      .mockResolvedValue(response({ kind: "orchestwin.why", schema_version: 2 }));
    const api = createWhyApi({ fetchImpl });
    await expect(api.document("project", " ")).rejects.toBeInstanceOf(WhyApiError);
    expect(fetchImpl).not.toHaveBeenCalled();
    await expect(api.document("project", "token")).rejects.toMatchObject({
      code: "INVALID_API_RESPONSE",
    });
  });
});
