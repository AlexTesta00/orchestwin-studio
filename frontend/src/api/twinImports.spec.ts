import { describe, expect, it, vi } from "vitest";

import type {
  TwinImportPayload,
  TwinImportSourcePayload,
  TwinImportSourcesPayload,
} from "../types/twinImports";
import { createTwinImportsApi, TwinImportsApiError } from "./twinImports";

const PROJECT_ID = "11111111-1111-4111-8111-111111111111";
const SOURCE_PROJECT_ID = "22222222-2222-4222-8222-222222222222";
const TWIN_ID = "33333333-3333-4333-8333-333333333333";
const ACCESS_TOKEN = "access-token";

const SOURCES: TwinImportSourcesPayload = {
  sources: [
    {
      project_id: SOURCE_PROJECT_ID,
      project_name: "Reception desk",
      snapshot_version_number: 2,
      approved_at: "2026-09-20T12:00:00Z",
      twin_names: ["Giulia", "Marco"],
    },
  ],
};

const SOURCE: TwinImportSourcePayload = {
  project_id: SOURCE_PROJECT_ID,
  project_name: "Reception desk",
  snapshot_version_number: 2,
  approved_at: "2026-09-20T12:00:00Z",
  twins: [
    {
      twin_id: TWIN_ID,
      name: "Giulia",
      version_number: 3,
      content_hash: "a".repeat(64),
      validation_status: "PROJECT_GROUNDED_UT",
      summary: "Receptionist on the night shift",
      issue: null,
    },
    {
      twin_id: "44444444-4444-4444-8444-444444444444",
      name: "Marco",
      version_number: 1,
      content_hash: "b".repeat(64),
      validation_status: "PROJECT_GROUNDED_UT",
      summary: null,
      issue: "TWIN_NAME_ALREADY_USED",
    },
  ],
};

const IMPORTED: TwinImportPayload = {
  status: "TWIN_IMPORTED",
  twin: {
    twin_id: "55555555-5555-4555-8555-555555555555",
    version_id: "66666666-6666-4666-8666-666666666666",
    version_number: 1,
    name: "Giulia",
    content_hash: "c".repeat(64),
    validation_status: "PROJECT_GROUNDED_UT",
  },
  persona: {
    persona_id: "77777777-7777-4777-8777-777777777777",
    version_id: "88888888-8888-4888-8888-888888888888",
    version_number: 1,
    name: "Giulia",
  },
  snapshot: {
    version_id: "99999999-9999-4999-8999-999999999999",
    version_number: 4,
    content_hash: "d".repeat(64),
    twin_count: 3,
  },
  origin: {
    project_id: SOURCE_PROJECT_ID,
    project_name: "Reception desk",
    twin_id: TWIN_ID,
    twin_version_number: 3,
    twin_content_hash: "a".repeat(64),
    persona_id: "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa",
    persona_version_number: 2,
    persona_content_hash: "e".repeat(64),
  },
  gate_approval_required: true,
};

const DOCUMENT = {
  schema_version: 2,
  kind: "orchestwin.user-twin",
  origin: { project_id: SOURCE_PROJECT_ID, project_name: "Reception desk" },
  twin: { profile: { name: "Giulia" } },
};

function jsonResponse(payload: unknown, status = 200): Response {
  return new Response(JSON.stringify(payload), {
    status,
    headers: { "Content-Type": "application/json" },
  });
}

describe("Twin Imports API client", () => {
  it("lists the other projects that can give a twin with an authenticated GET", async () => {
    const fetchImpl = vi.fn<typeof fetch>().mockResolvedValue(jsonResponse(SOURCES));
    const api = createTwinImportsApi({ fetchImpl });

    const sources = await api.sources(PROJECT_ID, ACCESS_TOKEN);

    const call = fetchImpl.mock.calls[0];
    expect(call?.[0]).toBe(`/api/v1/projects/${PROJECT_ID}/user-modeling/twin-imports/sources`);
    expect(call?.[1]?.method).toBe("GET");
    expect(call?.[1]?.credentials).toBe("include");
    expect(call?.[1]?.headers).toEqual({
      Accept: "application/json",
      Authorization: `Bearer ${ACCESS_TOKEN}`,
    });
    expect(call?.[1]).not.toHaveProperty("body");
    expect(sources).toEqual(SOURCES);
  });

  it("reads the twins that another project can give with an authenticated GET", async () => {
    const fetchImpl = vi.fn<typeof fetch>().mockResolvedValue(jsonResponse(SOURCE));
    const api = createTwinImportsApi({ fetchImpl });

    const source = await api.source(PROJECT_ID, SOURCE_PROJECT_ID, ACCESS_TOKEN);

    const call = fetchImpl.mock.calls[0];
    expect(call?.[0]).toBe(
      `/api/v1/projects/${PROJECT_ID}/user-modeling/twin-imports/sources/${SOURCE_PROJECT_ID}`,
    );
    expect(call?.[1]?.method).toBe("GET");
    expect(call?.[1]?.credentials).toBe("include");
    expect(call?.[1]?.headers).toEqual({
      Accept: "application/json",
      Authorization: `Bearer ${ACCESS_TOKEN}`,
    });
    expect(call?.[1]).not.toHaveProperty("body");
    expect(source).toEqual(SOURCE);
  });

  it("imports a twin of another project with a JSON POST naming the project and the twin", async () => {
    const fetchImpl = vi.fn<typeof fetch>().mockResolvedValue(jsonResponse(IMPORTED, 201));
    const api = createTwinImportsApi({ fetchImpl });

    const result = await api.importFromProject(
      PROJECT_ID,
      SOURCE_PROJECT_ID,
      TWIN_ID,
      ACCESS_TOKEN,
    );

    const call = fetchImpl.mock.calls[0];
    expect(call?.[0]).toBe(`/api/v1/projects/${PROJECT_ID}/user-modeling/twin-imports`);
    expect(call?.[1]?.method).toBe("POST");
    expect(call?.[1]?.credentials).toBe("include");
    expect(call?.[1]?.headers).toEqual({
      Accept: "application/json",
      Authorization: `Bearer ${ACCESS_TOKEN}`,
      "Content-Type": "application/json",
    });
    expect(JSON.parse(String(call?.[1]?.body))).toEqual({
      source_project_id: SOURCE_PROJECT_ID,
      twin_id: TWIN_ID,
    });
    expect(result).toEqual(IMPORTED);
  });

  it("imports the document of a twin file with a JSON POST carrying the whole document", async () => {
    const fetchImpl = vi.fn<typeof fetch>().mockResolvedValue(jsonResponse(IMPORTED, 201));
    const api = createTwinImportsApi({ basePath: "/studio/api/v1/", fetchImpl });

    const result = await api.importDocument("project 1", DOCUMENT, ACCESS_TOKEN);

    const call = fetchImpl.mock.calls[0];
    expect(call?.[0]).toBe("/studio/api/v1/projects/project%201/user-modeling/twin-imports");
    expect(call?.[1]?.method).toBe("POST");
    expect(call?.[1]?.headers).toEqual({
      Accept: "application/json",
      Authorization: `Bearer ${ACCESS_TOKEN}`,
      "Content-Type": "application/json",
    });
    expect(JSON.parse(String(call?.[1]?.body))).toEqual({ document: DOCUMENT });
    expect(result).toEqual(IMPORTED);
  });

  it("encodes the identifiers placed in the path", async () => {
    const fetchImpl = vi
      .fn<typeof fetch>()
      .mockResolvedValueOnce(jsonResponse(SOURCE))
      .mockResolvedValueOnce(jsonResponse(SOURCES));
    const api = createTwinImportsApi({ basePath: "/studio/api/v1/", fetchImpl });

    await api.source("project/1", "source 2", ACCESS_TOKEN);
    await api.sources("project/1", ACCESS_TOKEN);

    expect(fetchImpl.mock.calls.map((call) => call[0])).toEqual([
      "/studio/api/v1/projects/project%2F1/user-modeling/twin-imports/sources/source%202",
      "/studio/api/v1/projects/project%2F1/user-modeling/twin-imports/sources",
    ]);
  });

  it("preserves the status and the typed code of a refused request", async () => {
    const fetchImpl = vi
      .fn<typeof fetch>()
      .mockResolvedValueOnce(
        jsonResponse({ detail: { code: "TWIN_IMPORT_SOURCES_UNAVAILABLE" } }, 503),
      )
      .mockResolvedValueOnce(jsonResponse({ detail: { code: "SOURCE_TWINS_NOT_APPROVED" } }, 409))
      .mockResolvedValueOnce(
        jsonResponse({ detail: { code: "TWIN_NAME_ALREADY_USED", location: "twin" } }, 409),
      )
      .mockResolvedValueOnce(jsonResponse({ detail: { code: "TWIN_DOCUMENT_INVALID" } }, 422))
      .mockResolvedValueOnce(new Response("", { status: 502 }));
    const api = createTwinImportsApi({ fetchImpl });

    await expect(api.sources(PROJECT_ID, ACCESS_TOKEN)).rejects.toMatchObject({
      name: "TwinImportsApiError",
      status: 503,
      code: "TWIN_IMPORT_SOURCES_UNAVAILABLE",
    });

    const refused = api.source(PROJECT_ID, SOURCE_PROJECT_ID, ACCESS_TOKEN);
    await expect(refused).rejects.toBeInstanceOf(TwinImportsApiError);
    await expect(refused).rejects.toMatchObject({
      name: "TwinImportsApiError",
      status: 409,
      code: "SOURCE_TWINS_NOT_APPROVED",
    });
    await expect(
      api.importFromProject(PROJECT_ID, SOURCE_PROJECT_ID, TWIN_ID, ACCESS_TOKEN),
    ).rejects.toMatchObject({
      status: 409,
      code: "TWIN_NAME_ALREADY_USED",
      payload: { detail: { code: "TWIN_NAME_ALREADY_USED", location: "twin" } },
    });
    await expect(api.importDocument(PROJECT_ID, DOCUMENT, ACCESS_TOKEN)).rejects.toMatchObject({
      status: 422,
      code: "TWIN_DOCUMENT_INVALID",
    });
    await expect(api.source(PROJECT_ID, SOURCE_PROJECT_ID, ACCESS_TOKEN)).rejects.toMatchObject({
      status: 502,
      code: null,
      payload: null,
    });
  });

  it("rejects a successful response whose body is not a JSON object", async () => {
    const fetchImpl = vi
      .fn<typeof fetch>()
      .mockResolvedValueOnce(jsonResponse([SOURCES.sources[0]]))
      .mockResolvedValueOnce(new Response("<html>proxy error</html>", { status: 200 }))
      .mockResolvedValueOnce(jsonResponse([], 201));
    const api = createTwinImportsApi({ fetchImpl });

    await expect(api.sources(PROJECT_ID, ACCESS_TOKEN)).rejects.toMatchObject({
      name: "TwinImportsApiError",
      status: 200,
      code: "INVALID_API_RESPONSE",
      payload: [SOURCES.sources[0]],
    });
    await expect(api.source(PROJECT_ID, SOURCE_PROJECT_ID, ACCESS_TOKEN)).rejects.toMatchObject({
      name: "TwinImportsApiError",
      status: 200,
      code: "INVALID_API_RESPONSE",
      payload: "<html>proxy error</html>",
    });
    await expect(api.importDocument(PROJECT_ID, DOCUMENT, ACCESS_TOKEN)).rejects.toMatchObject({
      status: 201,
      code: "INVALID_API_RESPONSE",
      payload: [],
    });
  });

  it("refuses to call the API without an access token", async () => {
    const fetchImpl = vi.fn<typeof fetch>();
    const api = createTwinImportsApi({ fetchImpl });

    await expect(api.sources(PROJECT_ID, "  ")).rejects.toMatchObject({
      status: 0,
      code: "ACCESS_TOKEN_REQUIRED",
    });
    await expect(api.source(PROJECT_ID, SOURCE_PROJECT_ID, " ")).rejects.toBeInstanceOf(
      TwinImportsApiError,
    );
    await expect(api.source(PROJECT_ID, SOURCE_PROJECT_ID, "")).rejects.toMatchObject({
      status: 0,
      code: "ACCESS_TOKEN_REQUIRED",
    });
    await expect(
      api.importFromProject(PROJECT_ID, SOURCE_PROJECT_ID, TWIN_ID, "   "),
    ).rejects.toMatchObject({ code: "ACCESS_TOKEN_REQUIRED" });
    await expect(api.importDocument(PROJECT_ID, DOCUMENT, "")).rejects.toMatchObject({
      code: "ACCESS_TOKEN_REQUIRED",
    });
    expect(fetchImpl).not.toHaveBeenCalled();
  });

  it("refuses an empty base path", () => {
    expect(() => createTwinImportsApi({ basePath: " / " })).toThrow(
      "Twin Imports API base path must not be empty",
    );
  });
});
