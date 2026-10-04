import { describe, expect, it, vi } from "vitest";

import { createDesignApi, DesignApiError } from "./design";
import { DIRECTED_DESIGN_VERSION, designDistanceReport } from "../test/designFixtures";

const PROJECT_ID = "00000000-0000-4000-8000-000000000010";
const ACCESS_TOKEN = "access-token";
const REPORT = designDistanceReport(DIRECTED_DESIGN_VERSION);

function jsonResponse(payload: unknown, status = 200): Response {
  return new Response(JSON.stringify(payload), {
    status,
    headers: { "Content-Type": "application/json" },
  });
}

describe("distance of the design alternatives", () => {
  it("reads the report of the current design with an authenticated GET", async () => {
    const fetchImpl = vi.fn<typeof fetch>().mockResolvedValue(jsonResponse(REPORT));
    const api = createDesignApi({ fetchImpl });

    const report = await api.distance(PROJECT_ID, ACCESS_TOKEN);

    const call = fetchImpl.mock.calls[0];
    expect(call?.[0]).toBe(`/api/v1/projects/${PROJECT_ID}/design/distance`);
    expect(call?.[1]?.method).toBe("GET");
    expect(call?.[1]?.credentials).toBe("include");
    expect(call?.[1]?.headers).toEqual({
      Accept: "application/json",
      Authorization: `Bearer ${ACCESS_TOKEN}`,
    });
    expect(call?.[1]).not.toHaveProperty("body");
    expect(report).toEqual(REPORT);
  });

  it("reads it on a custom base path with the project encoded", async () => {
    const fetchImpl = vi.fn<typeof fetch>().mockResolvedValue(jsonResponse(REPORT));
    const api = createDesignApi({ basePath: "/studio/api/v1/", fetchImpl });

    await api.distance("project 1", ACCESS_TOKEN);

    expect(fetchImpl.mock.calls[0]?.[0]).toBe(
      "/studio/api/v1/projects/project%201/design/distance",
    );
  });

  it("keeps the refusal of a project without a design so that the page can show nothing", async () => {
    const missing = { detail: { code: "DESIGN_PACKAGE_NOT_FOUND" } };
    const fetchImpl = vi
      .fn<typeof fetch>()
      .mockResolvedValueOnce(jsonResponse(missing, 404))
      .mockResolvedValueOnce(jsonResponse({ detail: "Not Found" }, 404))
      .mockResolvedValueOnce(new Response("Bad gateway", { status: 502 }));
    const api = createDesignApi({ fetchImpl });

    const refused = api.distance(PROJECT_ID, ACCESS_TOKEN);
    await expect(refused).rejects.toBeInstanceOf(DesignApiError);
    await expect(refused).rejects.toMatchObject({
      status: 404,
      code: "DESIGN_PACKAGE_NOT_FOUND",
      payload: missing,
    });
    await expect(api.distance(PROJECT_ID, ACCESS_TOKEN)).rejects.toMatchObject({
      status: 404,
      code: null,
    });
    await expect(api.distance(PROJECT_ID, ACCESS_TOKEN)).rejects.toMatchObject({
      status: 502,
      code: "INVALID_API_RESPONSE",
    });
  });

  it.each([
    ["an empty answer", ""],
    ["a list", "[]"],
    ["a report without pairs", JSON.stringify({ ...REPORT, pairs: null })],
    [
      "a pair without the drawn style",
      JSON.stringify({ ...REPORT, pairs: [{ ...REPORT.pairs[0], styles: null }] }),
    ],
    [
      "a pair whose differences are not a list",
      JSON.stringify({
        ...REPORT,
        pairs: [{ ...REPORT.pairs[0], structure: { available: true, score: 4, differences: "" } }],
      }),
    ],
    [
      "an alternative without adherence",
      JSON.stringify({ ...REPORT, alternatives: [{ code: "DES-001", direction: null }] }),
    ],
  ])("refuses %s as a report", async (_case, body) => {
    const api = createDesignApi({
      fetchImpl: async () =>
        new Response(body, { status: 200, headers: { "Content-Type": "application/json" } }),
    });

    await expect(api.distance(PROJECT_ID, ACCESS_TOKEN)).rejects.toMatchObject({
      name: "DesignApiError",
      status: 200,
      code: "INVALID_API_RESPONSE",
    });
  });

  it("accepts a report of a design whose alternatives have no direction nor mockups", async () => {
    const report = designDistanceReport(DIRECTED_DESIGN_VERSION, {
      declared: {
        score: null,
        axes_different: null,
        axes: [],
        choices_different: null,
        choices_total: 22,
        primary_colour_distance: null,
      },
      styles: { available: false, score: null, differences: [] },
      structure: { available: false, score: null, differences: [] },
      verdict: "UNKNOWN",
    });
    const withoutDirections = {
      ...report,
      alternatives: report.alternatives.map((item) => ({
        ...item,
        direction: null,
        adherence: { available: false, axes: {} },
      })),
    };
    const api = createDesignApi({ fetchImpl: async () => jsonResponse(withoutDirections) });

    await expect(api.distance(PROJECT_ID, ACCESS_TOKEN)).resolves.toEqual(withoutDirections);
  });

  it("refuses to call the Studio without an access token", async () => {
    const fetchImpl = vi.fn<typeof fetch>();
    const api = createDesignApi({ fetchImpl });

    await expect(api.distance(PROJECT_ID, " ")).rejects.toMatchObject({
      status: 0,
      code: "ACCESS_TOKEN_REQUIRED",
    });
    expect(fetchImpl).not.toHaveBeenCalled();
  });
});
