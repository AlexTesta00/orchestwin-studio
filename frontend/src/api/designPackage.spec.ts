import { describe, expect, it, vi } from "vitest";

import { DesignPackageApiError, createDesignPackageApi } from "./designPackage";

const PROJECT_ID = "11111111-1111-4111-8111-111111111111";

function zipResponse(headers: Record<string, string> = {}, status = 200): Response {
  const lookup = new Map(Object.entries(headers).map(([key, value]) => [key.toLowerCase(), value]));
  return {
    ok: status >= 200 && status < 300,
    status,
    headers: { get: (name: string) => lookup.get(name.toLowerCase()) ?? null },
    text: async () => JSON.stringify({ detail: { code: "DESIGN_APPROVAL_REQUIRED" } }),
    blob: async () => new Blob(["PK"], { type: "application/zip" }),
  } as unknown as Response;
}

describe("Design Package API client", () => {
  it("downloads the authenticated zip and reads the file name from the headers", async () => {
    const fetchMock = vi.fn(async () =>
      zipResponse({
        "Content-Disposition": 'attachment; filename="orchestwin-demo-design-package.zip"',
        "X-Content-SHA256": "a".repeat(64),
      }),
    );
    const api = createDesignPackageApi({ fetchImpl: fetchMock });

    const result = await api.download(PROJECT_ID, "access-token");

    const [input, init] = fetchMock.mock.calls[0] as unknown as [string, RequestInit];
    expect(input).toBe(`/api/v1/projects/${PROJECT_ID}/design-package`);
    expect(init.method).toBe("GET");
    expect(init.credentials).toBe("include");
    expect(init.headers).toMatchObject({
      Accept: "application/zip",
      Authorization: "Bearer access-token",
    });
    expect(result.blob).toBeInstanceOf(Blob);
    expect(result.fileName).toBe("orchestwin-demo-design-package.zip");
    expect(result.contentHash).toBe("a".repeat(64));
  });

  it("falls back to the deterministic file name without a disposition header", async () => {
    const api = createDesignPackageApi({ fetchImpl: vi.fn(async () => zipResponse()) });

    const result = await api.download(PROJECT_ID, "access-token");

    expect(result.fileName).toBe(`orchestwin-${PROJECT_ID}-design-package.zip`);
    expect(result.contentHash).toBeNull();
  });

  it("preserves the typed block code when an approval is missing", async () => {
    const api = createDesignPackageApi({ fetchImpl: vi.fn(async () => zipResponse({}, 409)) });

    await expect(api.download(PROJECT_ID, "access-token")).rejects.toMatchObject({
      status: 409,
      code: "DESIGN_APPROVAL_REQUIRED",
    });
    await expect(api.download(PROJECT_ID, "access-token")).rejects.toBeInstanceOf(
      DesignPackageApiError,
    );
  });

  it("refuses to call the API without an access token", async () => {
    const fetchMock = vi.fn(async () => zipResponse());
    const api = createDesignPackageApi({ fetchImpl: fetchMock });

    await expect(api.download(PROJECT_ID, "   ")).rejects.toMatchObject({
      code: "ACCESS_TOKEN_REQUIRED",
    });
    expect(fetchMock).not.toHaveBeenCalled();
  });
});
