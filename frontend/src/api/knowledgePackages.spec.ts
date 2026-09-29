import { describe, expect, it, vi } from "vitest";

import type {
  KnowledgePackageHistoryPayload,
  KnowledgePackagePublicationPayload,
  KnowledgePackageVersionPayload,
} from "../types/knowledgePackages";
import {
  createKnowledgePackagesApi,
  knowledgePackageFileName,
  KnowledgePackagesApiError,
} from "./knowledgePackages";

const PROJECT_ID = "11111111-1111-4111-8111-111111111111";
const ACCESS_TOKEN = "access-token";

const VERSION: KnowledgePackageVersionPayload = {
  id: "33333333-3333-4333-8333-333333333333",
  project_id: PROJECT_ID,
  project_name: "Reception desk",
  version_number: 3,
  schema_version: 1,
  content_hash: "c".repeat(64),
  archive_hash: "d".repeat(64),
  file_name: `orchestwin-${PROJECT_ID}-knowledge-v3.zip`,
  file_count: 12,
  archive_size: 20480,
  created_at: "2026-09-27T09:00:00Z",
  stages: [
    {
      stage: "brief",
      label: "Brief",
      version_number: 2,
      content_hash: "e".repeat(64),
    },
  ],
  twins: [
    {
      twin_id: "44444444-4444-4444-8444-444444444444",
      name: "Giulia",
      slug: "giulia",
      version_number: 1,
      document: "twins/giulia.md",
    },
  ],
  feedback: {
    reviews: 1,
    findings: 4,
    decisions: 2,
    discussions: 1,
    insights: 3,
  },
  diagram_count: 6,
  table_count: 4,
  entries: ["README.md", "manifest.json"],
};

const PUBLICATION: KnowledgePackagePublicationPayload = { reused: false, version: VERSION };

const HISTORY: KnowledgePackageHistoryPayload = { project_id: PROJECT_ID, versions: [VERSION] };

function jsonResponse(payload: unknown, status = 200): Response {
  return new Response(JSON.stringify(payload), {
    status,
    headers: { "Content-Type": "application/json" },
  });
}

function zipResponse(headers: Record<string, string> = {}): Response {
  const lookup = new Map(Object.entries(headers).map(([key, value]) => [key.toLowerCase(), value]));
  return {
    ok: true,
    status: 200,
    headers: { get: (name: string) => lookup.get(name.toLowerCase()) ?? null },
    text: async () => "PK",
    blob: async () => new Blob(["PK"], { type: "application/zip" }),
  } as unknown as Response;
}

describe("Knowledge Packages API client", () => {
  it("publishes the project with an authenticated POST without a body", async () => {
    const fetchImpl = vi
      .fn<typeof fetch>()
      .mockResolvedValueOnce(jsonResponse(PUBLICATION, 201))
      .mockResolvedValueOnce(jsonResponse({ reused: true, version: VERSION }));
    const api = createKnowledgePackagesApi({ fetchImpl });

    const created = await api.publish(PROJECT_ID, ACCESS_TOKEN);
    const reused = await api.publish(PROJECT_ID, ACCESS_TOKEN);

    const call = fetchImpl.mock.calls[0];
    expect(call?.[0]).toBe(`/api/v1/projects/${PROJECT_ID}/knowledge-packages`);
    expect(call?.[1]?.method).toBe("POST");
    expect(call?.[1]?.credentials).toBe("include");
    expect(call?.[1]?.headers).toEqual({
      Accept: "application/json",
      Authorization: `Bearer ${ACCESS_TOKEN}`,
    });
    expect(call?.[1]).not.toHaveProperty("body");
    expect(created).toEqual(PUBLICATION);
    expect(reused).toEqual({ reused: true, version: VERSION });
  });

  it("lists the history and sends the limit only when it is given", async () => {
    const fetchImpl = vi.fn<typeof fetch>().mockImplementation(async () => jsonResponse(HISTORY));
    const api = createKnowledgePackagesApi({ basePath: "/studio/api/v1/", fetchImpl });

    const history = await api.history("project 1", ACCESS_TOKEN);
    await api.history("project 1", ACCESS_TOKEN, 5);

    expect(history).toEqual(HISTORY);
    expect(fetchImpl.mock.calls.map((call) => [call[0], call[1]?.method])).toEqual([
      ["/studio/api/v1/projects/project%201/knowledge-packages", "GET"],
      ["/studio/api/v1/projects/project%201/knowledge-packages?limit=5", "GET"],
    ]);
    expect(fetchImpl.mock.calls[1]?.[1]?.headers).toEqual({
      Accept: "application/json",
      Authorization: `Bearer ${ACCESS_TOKEN}`,
    });
  });

  it("downloads the archive of a version with the file name and the hash of the headers", async () => {
    const fetchImpl = vi.fn<typeof fetch>().mockResolvedValue(
      zipResponse({
        "Content-Disposition": 'attachment; filename="orchestwin-demo-knowledge-v3.zip"',
        "X-Content-SHA256": "d".repeat(64),
      }),
    );
    const api = createKnowledgePackagesApi({ fetchImpl });

    const result = await api.download(PROJECT_ID, 3, ACCESS_TOKEN);

    const call = fetchImpl.mock.calls[0];
    expect(call?.[0]).toBe(`/api/v1/projects/${PROJECT_ID}/knowledge-packages/3/archive`);
    expect(call?.[1]?.method).toBe("GET");
    expect(call?.[1]?.credentials).toBe("include");
    expect(call?.[1]?.headers).toEqual({
      Accept: "application/zip",
      Authorization: `Bearer ${ACCESS_TOKEN}`,
    });
    expect(result.blob).toBeInstanceOf(Blob);
    expect(result.fileName).toBe("orchestwin-demo-knowledge-v3.zip");
    expect(result.archiveHash).toBe("d".repeat(64));
  });

  it("falls back to the deterministic file name without a disposition header", async () => {
    const api = createKnowledgePackagesApi({
      fetchImpl: vi.fn<typeof fetch>().mockResolvedValue(zipResponse()),
    });

    const result = await api.download(PROJECT_ID, 7, ACCESS_TOKEN);

    expect(knowledgePackageFileName(PROJECT_ID, 7)).toBe(
      `orchestwin-${PROJECT_ID}-knowledge-v7.zip`,
    );
    expect(result.fileName).toBe(knowledgePackageFileName(PROJECT_ID, 7));
    expect(result.archiveHash).toBeNull();
  });

  it("preserves the typed codes of a blocked publication and of a missing archive", async () => {
    const fetchImpl = vi
      .fn<typeof fetch>()
      .mockResolvedValueOnce(jsonResponse({ detail: { code: "DESIGN_APPROVAL_REQUIRED" } }, 409))
      .mockResolvedValueOnce(jsonResponse({ detail: { code: "KNOWLEDGE_PACKAGE_NOT_FOUND" } }, 404))
      .mockResolvedValueOnce(jsonResponse({ detail: { code: "PROJECT_NOT_FOUND" } }, 404));
    const api = createKnowledgePackagesApi({ fetchImpl });

    const blocked = api.publish(PROJECT_ID, ACCESS_TOKEN);
    await expect(blocked).rejects.toBeInstanceOf(KnowledgePackagesApiError);
    await expect(blocked).rejects.toMatchObject({
      name: "KnowledgePackagesApiError",
      status: 409,
      code: "DESIGN_APPROVAL_REQUIRED",
    });
    await expect(api.download(PROJECT_ID, 9, ACCESS_TOKEN)).rejects.toMatchObject({
      name: "KnowledgePackagesApiError",
      status: 404,
      code: "KNOWLEDGE_PACKAGE_NOT_FOUND",
    });
    await expect(api.history(PROJECT_ID, ACCESS_TOKEN)).rejects.toMatchObject({
      status: 404,
      code: "PROJECT_NOT_FOUND",
    });
  });

  it("rejects a successful response whose body is not a JSON object", async () => {
    const fetchImpl = vi
      .fn<typeof fetch>()
      .mockResolvedValueOnce(new Response("<html>proxy error</html>", { status: 201 }))
      .mockResolvedValueOnce(jsonResponse([]));
    const api = createKnowledgePackagesApi({ fetchImpl });

    await expect(api.publish(PROJECT_ID, ACCESS_TOKEN)).rejects.toMatchObject({
      name: "KnowledgePackagesApiError",
      status: 201,
      code: "INVALID_API_RESPONSE",
      payload: "<html>proxy error</html>",
    });
    await expect(api.history(PROJECT_ID, ACCESS_TOKEN)).rejects.toMatchObject({
      status: 200,
      code: "INVALID_API_RESPONSE",
      payload: [],
    });
  });

  it("refuses to call the API without an access token", async () => {
    const fetchImpl = vi.fn<typeof fetch>();
    const api = createKnowledgePackagesApi({ fetchImpl });

    await expect(api.publish(PROJECT_ID, " ")).rejects.toBeInstanceOf(KnowledgePackagesApiError);
    await expect(api.publish(PROJECT_ID, " ")).rejects.toMatchObject({
      status: 0,
      code: "ACCESS_TOKEN_REQUIRED",
    });
    await expect(api.history(PROJECT_ID, "")).rejects.toMatchObject({
      code: "ACCESS_TOKEN_REQUIRED",
    });
    await expect(api.download(PROJECT_ID, 1, "   ")).rejects.toMatchObject({
      code: "ACCESS_TOKEN_REQUIRED",
    });
    expect(fetchImpl).not.toHaveBeenCalled();
  });
});
