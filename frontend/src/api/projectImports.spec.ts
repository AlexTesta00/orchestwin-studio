import { describe, expect, it, vi } from "vitest";

import type { ProjectImportOriginPayload, ProjectImportPayload } from "../types/projectImports";
import { createProjectImportsApi, ProjectImportsApiError } from "./projectImports";

const PROJECT_ID = "11111111-1111-4111-8111-111111111111";
const SOURCE_ID = "22222222-2222-4222-8222-222222222222";
const ACCESS_TOKEN = "access-token";

const ORIGIN = {
  project_id: SOURCE_ID,
  project_name: "Reception desk",
  package_version: 3,
  package_content_hash: "a".repeat(64),
  schema_version: 2,
};

const STAGES = {
  brief: {
    version_id: "33333333-3333-4333-8333-333333333333",
    version_number: 1,
    content_hash: "b".repeat(64),
  },
};

const IMPORTED: ProjectImportPayload = {
  project: {
    id: PROJECT_ID,
    display_name: "Reception desk",
    mode: "GREENFIELD_GENERATION",
    created_at: "2026-09-27T10:00:00Z",
  },
  origin: ORIGIN,
  stages: STAGES,
  twins: [{ twin_id: "44444444-4444-4444-8444-444444444444", name: "Giulia" }],
  imported_at: "2026-09-27T10:00:00Z",
  approval_required: ["brief", "team", "twins", "requirements", "design"],
};

const ORIGIN_RECORD: ProjectImportOriginPayload = {
  origin: ORIGIN,
  stages: STAGES,
  imported_at: "2026-09-27T10:00:00Z",
  archive_hash: "c".repeat(64),
};

function jsonResponse(payload: unknown, status = 200): Response {
  return new Response(JSON.stringify(payload), {
    status,
    headers: { "Content-Type": "application/json" },
  });
}

function archive(): Blob {
  return new Blob(["PK"], { type: "application/zip" });
}

describe("Project Imports API client", () => {
  it("uploads the archive as a form without setting the content type", async () => {
    const fetchImpl = vi.fn<typeof fetch>().mockResolvedValue(jsonResponse(IMPORTED, 201));
    const api = createProjectImportsApi({ fetchImpl });

    const imported = await api.importArchive(
      archive(),
      "orchestwin-knowledge-v3.zip",
      null,
      ACCESS_TOKEN,
    );

    const call = fetchImpl.mock.calls[0];
    expect(call?.[0]).toBe("/api/v1/project-imports");
    expect(call?.[1]?.method).toBe("POST");
    expect(call?.[1]?.credentials).toBe("include");
    expect(call?.[1]?.headers).toEqual({
      Accept: "application/json",
      Authorization: `Bearer ${ACCESS_TOKEN}`,
    });
    const body = call?.[1]?.body;
    expect(body).toBeInstanceOf(FormData);
    const form = body as FormData;
    const file = form.get("archive");
    expect(file).toBeInstanceOf(File);
    expect((file as File).name).toBe("orchestwin-knowledge-v3.zip");
    expect(await (file as File).text()).toBe("PK");
    expect(form.has("display_name")).toBe(false);
    expect([...form.keys()]).toEqual(["archive"]);
    expect(imported).toEqual(IMPORTED);
  });

  it("sends the name of the new project only when it is given", async () => {
    const fetchImpl = vi.fn<typeof fetch>().mockResolvedValue(jsonResponse(IMPORTED, 201));
    const api = createProjectImportsApi({ basePath: "/studio/api/v1/", fetchImpl });

    await api.importArchive(archive(), "folder.zip", "Front desk 2027", ACCESS_TOKEN);

    const call = fetchImpl.mock.calls[0];
    expect(call?.[0]).toBe("/studio/api/v1/project-imports");
    const form = call?.[1]?.body as FormData;
    expect([...form.keys()]).toEqual(["archive", "display_name"]);
    expect(form.get("display_name")).toBe("Front desk 2027");
  });

  it("keeps the status, the code and the location of a refused archive", async () => {
    const fetchImpl = vi
      .fn<typeof fetch>()
      .mockResolvedValueOnce(
        jsonResponse({ detail: { code: "FOLDER_TAMPERED", location: "requirements.json" } }, 422),
      )
      .mockResolvedValueOnce(
        jsonResponse({ detail: { code: "FOLDER_ARCHIVE_TOO_LARGE", location: null } }, 413),
      )
      .mockResolvedValueOnce(new Response("Bad gateway", { status: 502 }));
    const api = createProjectImportsApi({ fetchImpl });

    const tampered = api.importArchive(archive(), "folder.zip", null, ACCESS_TOKEN);
    await expect(tampered).rejects.toBeInstanceOf(ProjectImportsApiError);
    await expect(tampered).rejects.toMatchObject({
      name: "ProjectImportsApiError",
      status: 422,
      code: "FOLDER_TAMPERED",
      location: "requirements.json",
    });
    await expect(
      api.importArchive(archive(), "folder.zip", null, ACCESS_TOKEN),
    ).rejects.toMatchObject({
      status: 413,
      code: "FOLDER_ARCHIVE_TOO_LARGE",
      location: null,
    });
    await expect(
      api.importArchive(archive(), "folder.zip", null, ACCESS_TOKEN),
    ).rejects.toMatchObject({
      status: 502,
      code: null,
      location: null,
      payload: "Bad gateway",
    });
  });

  it("reads where an imported project comes from", async () => {
    const fetchImpl = vi.fn<typeof fetch>().mockResolvedValue(jsonResponse(ORIGIN_RECORD));
    const api = createProjectImportsApi({ fetchImpl });

    const origin = await api.origin("project 1", ACCESS_TOKEN);

    const call = fetchImpl.mock.calls[0];
    expect(call?.[0]).toBe("/api/v1/projects/project%201/import");
    expect(call?.[1]?.method).toBe("GET");
    expect(call?.[1]?.credentials).toBe("include");
    expect(call?.[1]?.headers).toEqual({
      Accept: "application/json",
      Authorization: `Bearer ${ACCESS_TOKEN}`,
    });
    expect(call?.[1]).not.toHaveProperty("body");
    expect(origin).toEqual(ORIGIN_RECORD);
  });

  it("returns no origin for a project that was not imported and fails on other errors", async () => {
    const fetchImpl = vi
      .fn<typeof fetch>()
      .mockResolvedValueOnce(
        jsonResponse({ detail: { code: "PROJECT_IMPORT_NOT_FOUND", location: null } }, 404),
      )
      .mockResolvedValueOnce(jsonResponse({ detail: { code: "PROJECT_NOT_FOUND" } }, 404))
      .mockResolvedValueOnce(
        jsonResponse({ detail: { code: "PROJECT_IMPORT_SERVICE_UNAVAILABLE" } }, 503),
      );
    const api = createProjectImportsApi({ fetchImpl });

    await expect(api.origin(PROJECT_ID, ACCESS_TOKEN)).resolves.toBeNull();
    await expect(api.origin(PROJECT_ID, ACCESS_TOKEN)).rejects.toMatchObject({
      name: "ProjectImportsApiError",
      status: 404,
      code: "PROJECT_NOT_FOUND",
    });
    await expect(api.origin(PROJECT_ID, ACCESS_TOKEN)).rejects.toMatchObject({
      status: 503,
      code: "PROJECT_IMPORT_SERVICE_UNAVAILABLE",
    });
  });

  it("rejects a successful response whose body is not a JSON object", async () => {
    const fetchImpl = vi
      .fn<typeof fetch>()
      .mockResolvedValueOnce(new Response("<html>proxy error</html>", { status: 201 }))
      .mockResolvedValueOnce(jsonResponse([]));
    const api = createProjectImportsApi({ fetchImpl });

    await expect(
      api.importArchive(archive(), "folder.zip", null, ACCESS_TOKEN),
    ).rejects.toMatchObject({
      name: "ProjectImportsApiError",
      status: 201,
      code: "INVALID_API_RESPONSE",
      payload: "<html>proxy error</html>",
    });
    await expect(api.origin(PROJECT_ID, ACCESS_TOKEN)).rejects.toMatchObject({
      status: 200,
      code: "INVALID_API_RESPONSE",
      payload: [],
    });
  });

  it("refuses to call the API without an access token", async () => {
    const fetchImpl = vi.fn<typeof fetch>();
    const api = createProjectImportsApi({ fetchImpl });

    await expect(api.importArchive(archive(), "folder.zip", null, " ")).rejects.toBeInstanceOf(
      ProjectImportsApiError,
    );
    await expect(api.importArchive(archive(), "folder.zip", "Name", "")).rejects.toMatchObject({
      status: 0,
      code: "ACCESS_TOKEN_REQUIRED",
      location: null,
    });
    await expect(api.origin(PROJECT_ID, "   ")).rejects.toMatchObject({
      code: "ACCESS_TOKEN_REQUIRED",
    });
    expect(fetchImpl).not.toHaveBeenCalled();
  });
});
