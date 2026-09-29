import { describe, expect, it, vi } from "vitest";

import { createDesignReviewPinsApi, DesignReviewPinsApiError } from "./designReviewPins";

function response(status: number, body: unknown): Response {
  return new Response(body === undefined ? "" : JSON.stringify(body), {
    status,
    headers: { "Content-Type": "application/json" },
  });
}

const PINS = {
  design_version_id: "version-2",
  pins: [
    {
      number: 1,
      element_code: "ELM-014",
      screen_code: "SCR-001",
      twin_id: "twin-1",
      finding_id: "UTF-001",
      severity: "major",
      label: "Il pulsante di conferma è troppo in basso",
    },
  ],
  unanchored: [{ number: 2, screen_code: "SCR-002", twin_id: "twin-1", finding_id: "UTF-003" }],
};

describe("design review pins api", () => {
  it("reads the pins and the document of a review with the bearer token", async () => {
    const fetchImpl = vi.fn(async (input: RequestInfo | URL) =>
      String(input).includes("/pins")
        ? response(200, PINS)
        : response(200, { html: "<!doctype html>", source: "review", entry_screen: "SCR-002" }),
    );
    const api = createDesignReviewPinsApi({ basePath: "/api/v1/", fetchImpl });

    expect(await api.pins("project 1", "run/1", "token")).toEqual(PINS);
    expect((await api.document("project 1", "run/1", "SCR-002", "token")).source).toBe("review");
    await api.document("project 1", "run/1", null, "token");

    expect(fetchImpl.mock.calls.map((call) => String(call[0]))).toEqual([
      "/api/v1/projects/project%201/design/evaluations/run%2F1/pins",
      "/api/v1/projects/project%201/design/evaluations/run%2F1/document?entry_screen=SCR-002",
      "/api/v1/projects/project%201/design/evaluations/run%2F1/document",
    ]);
    for (const call of fetchImpl.mock.calls as unknown[][]) {
      const init = call[1] as RequestInit;
      expect(init.method).toBe("GET");
      expect(init.credentials).toBe("include");
      expect(init.headers).toEqual({ Accept: "application/json", Authorization: "Bearer token" });
    }
  });

  it.each([
    [409, "GENERATED_MOCKUP_REQUIRED"],
    [404, "DESIGN_EVALUATION_NOT_FOUND"],
    [404, "PROJECT_NOT_FOUND"],
  ])("surfaces the answer %i %s", async (status, code) => {
    const api = createDesignReviewPinsApi({
      fetchImpl: async () => response(status, { detail: { code } }),
    });

    const failure = api.pins("p", "run-1", "token");

    await expect(failure).rejects.toBeInstanceOf(DesignReviewPinsApiError);
    await expect(failure).rejects.toMatchObject({ status, code });
  });

  it("refuses to call the server without a token and reports unreadable answers", async () => {
    const fetchImpl = vi.fn(async () => new Response("<html>", { status: 200 }));
    const api = createDesignReviewPinsApi({ fetchImpl });

    await expect(api.document("p", "run-1", null, " ")).rejects.toMatchObject({
      code: "ACCESS_TOKEN_REQUIRED",
    });
    expect(fetchImpl).not.toHaveBeenCalled();
    await expect(api.pins("p", "run-1", "token")).rejects.toMatchObject({
      code: "INVALID_API_RESPONSE",
    });
  });
});
