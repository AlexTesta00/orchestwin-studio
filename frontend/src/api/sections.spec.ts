import { describe, expect, it, vi } from "vitest";

import type { ProjectSectionsPayload, SectionsAlignmentPayload } from "../types/sections";
import { createSectionsApi, SectionsApiError } from "./sections";

const PROJECT_ID = "11111111-1111-4111-8111-111111111111";
const ACCESS_TOKEN = "test-token-not-real";

const SECTIONS: ProjectSectionsPayload = {
  first_pass_complete: true,
  sections: [
    { key: "BRIEF", state: "FINE", version_number: 2, reasons: [], blocked: null, codes: [] },
    { key: "TEAM", state: "FINE", version_number: 2, reasons: [], blocked: null, codes: [] },
    {
      key: "USER_TWINS",
      state: "TO_UPDATE",
      version_number: 1,
      reasons: ["PERSPECTIVES_CHANGED"],
      blocked: null,
      codes: [],
    },
    {
      key: "REQUIREMENTS",
      state: "TO_UPDATE",
      version_number: 3,
      reasons: ["PERSPECTIVES_CHANGED", "USER_TWINS_CHANGED"],
      blocked: null,
      codes: [],
    },
    {
      key: "DESIGN",
      state: "TO_UPDATE",
      version_number: 4,
      reasons: ["REQUIREMENTS_CHANGED"],
      blocked: null,
      codes: [],
    },
    {
      key: "PACKAGE",
      state: "TO_UPDATE",
      version_number: 6,
      reasons: ["FOLDER_BEHIND"],
      blocked: null,
      codes: [],
    },
  ],
  alignment: {
    available: true,
    sections: ["USER_TWINS", "REQUIREMENTS", "DESIGN"],
    uncovered_codes: [],
  },
};

const ALIGNMENT: SectionsAlignmentPayload = {
  status: "PARTIAL",
  results: [
    { key: "USER_TWINS", outcome: "ALIGNED", issue: null, version_number: 2, codes: [] },
    { key: "REQUIREMENTS", outcome: "ALIGNED", issue: null, version_number: 4, codes: [] },
    {
      key: "DESIGN",
      outcome: "BLOCKED",
      issue: "REQUIREMENT_NO_LONGER_AVAILABLE",
      version_number: null,
      codes: ["REQ-004"],
    },
  ],
  sections: SECTIONS,
};

function jsonResponse(payload: unknown, status = 200): Response {
  return new Response(JSON.stringify(payload), {
    status,
    headers: { "Content-Type": "application/json" },
  });
}

describe("Sections API client", () => {
  it("reads the sections of a project with an authenticated GET", async () => {
    const fetchImpl = vi.fn<typeof fetch>().mockResolvedValue(jsonResponse(SECTIONS));
    const api = createSectionsApi({ fetchImpl });

    const sections = await api.read(PROJECT_ID, ACCESS_TOKEN);

    const call = fetchImpl.mock.calls[0];
    expect(call?.[0]).toBe(`/api/v1/projects/${PROJECT_ID}/sections`);
    expect(call?.[1]?.method).toBe("GET");
    expect(call?.[1]?.credentials).toBe("include");
    expect(call?.[1]?.headers).toEqual({
      Accept: "application/json",
      Authorization: `Bearer ${ACCESS_TOKEN}`,
    });
    expect(sections).toEqual(SECTIONS);
  });

  it("runs the one gesture with a POST without a body on a custom base path", async () => {
    const fetchImpl = vi.fn<typeof fetch>().mockResolvedValue(jsonResponse(ALIGNMENT));
    const api = createSectionsApi({ basePath: "/studio/api/v1/", fetchImpl });

    const alignment = await api.align("project 1", ACCESS_TOKEN);

    const call = fetchImpl.mock.calls[0];
    expect(call?.[0]).toBe("/studio/api/v1/projects/project%201/sections/alignment");
    expect(call?.[1]?.method).toBe("POST");
    expect(call?.[1]?.credentials).toBe("include");
    expect(call?.[1]?.headers).toEqual({
      Accept: "application/json",
      Authorization: `Bearer ${ACCESS_TOKEN}`,
    });
    expect(call?.[1]).not.toHaveProperty("body");
    expect(alignment).toEqual(ALIGNMENT);
  });

  it.each([404, 405])(
    "answers no sections when a Studio without the route answers %i",
    async (status) => {
      const fetchImpl = vi
        .fn<typeof fetch>()
        .mockResolvedValue(jsonResponse({ detail: "Not Found" }, status));
      const api = createSectionsApi({ fetchImpl });

      await expect(api.read(PROJECT_ID, ACCESS_TOKEN)).resolves.toBeNull();
    },
  );

  it("preserves the status and the code of a failed read and of a refused gesture", async () => {
    const fetchImpl = vi
      .fn<typeof fetch>()
      .mockResolvedValueOnce(
        jsonResponse({ detail: { code: "SECTIONS_SERVICE_UNAVAILABLE" } }, 503),
      )
      .mockResolvedValueOnce(jsonResponse({ detail: { code: "PROJECT_NOT_FOUND" } }, 404))
      .mockResolvedValueOnce(new Response("Bad gateway", { status: 502 }));
    const api = createSectionsApi({ fetchImpl });

    const unavailable = api.read(PROJECT_ID, ACCESS_TOKEN);
    await expect(unavailable).rejects.toBeInstanceOf(SectionsApiError);
    await expect(unavailable).rejects.toMatchObject({
      name: "SectionsApiError",
      status: 503,
      code: "SECTIONS_SERVICE_UNAVAILABLE",
    });
    await expect(api.align(PROJECT_ID, ACCESS_TOKEN)).rejects.toMatchObject({
      status: 404,
      code: "PROJECT_NOT_FOUND",
    });
    await expect(api.align(PROJECT_ID, ACCESS_TOKEN)).rejects.toMatchObject({
      status: 502,
      code: null,
      payload: "Bad gateway",
    });
  });

  it.each([
    ["a text page", "<html>proxy error</html>"],
    ["an unknown state", { ...SECTIONS, sections: [{ ...SECTIONS.sections[0], state: "DONE" }] }],
    ["an unknown section", { ...SECTIONS, sections: [{ ...SECTIONS.sections[0], key: "TEAMS" }] }],
    [
      "a version that is not a number",
      { ...SECTIONS, sections: [{ ...SECTIONS.sections[0], version_number: "2" }] },
    ],
    ["no alignment", { first_pass_complete: true, sections: [] }],
    [
      "an unknown alignable section",
      { ...SECTIONS, alignment: { ...SECTIONS.alignment, sections: ["BRIEF"] } },
    ],
  ])("refuses sections with %s", async (_label, payload) => {
    const body = typeof payload === "string" ? payload : JSON.stringify(payload);
    const fetchImpl = vi.fn<typeof fetch>().mockResolvedValue(new Response(body, { status: 200 }));
    const api = createSectionsApi({ fetchImpl });

    await expect(api.read(PROJECT_ID, ACCESS_TOKEN)).rejects.toMatchObject({
      name: "SectionsApiError",
      status: 200,
      code: "INVALID_API_RESPONSE",
    });
  });

  it.each([
    ["an unknown status", { ...ALIGNMENT, status: "DONE" }],
    ["an unknown outcome", { ...ALIGNMENT, results: [{ ...ALIGNMENT.results[0], outcome: "OK" }] }],
    [
      "a result for the brief",
      { ...ALIGNMENT, results: [{ ...ALIGNMENT.results[0], key: "BRIEF" }] },
    ],
    ["sections that are not valid", { ...ALIGNMENT, sections: { first_pass_complete: true } }],
  ])("refuses a gesture answer with %s", async (_label, payload) => {
    const fetchImpl = vi.fn<typeof fetch>().mockResolvedValue(jsonResponse(payload));
    const api = createSectionsApi({ fetchImpl });

    await expect(api.align(PROJECT_ID, ACCESS_TOKEN)).rejects.toMatchObject({
      status: 200,
      code: "INVALID_API_RESPONSE",
      payload,
    });
  });

  it("refuses to call the API without an access token", async () => {
    const fetchImpl = vi.fn<typeof fetch>();
    const api = createSectionsApi({ fetchImpl });

    await expect(api.read(PROJECT_ID, " ")).rejects.toBeInstanceOf(SectionsApiError);
    await expect(api.read(PROJECT_ID, "")).rejects.toMatchObject({
      status: 0,
      code: "ACCESS_TOKEN_REQUIRED",
    });
    await expect(api.align(PROJECT_ID, "   ")).rejects.toMatchObject({
      code: "ACCESS_TOKEN_REQUIRED",
    });
    expect(fetchImpl).not.toHaveBeenCalled();
  });

  it("refuses an empty base path", () => {
    expect(() => createSectionsApi({ basePath: " / " })).toThrow(
      "Sections API base path must not be empty",
    );
  });
});
