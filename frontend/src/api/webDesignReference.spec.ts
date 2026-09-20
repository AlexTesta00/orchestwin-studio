import { describe, expect, it, vi } from "vitest";
import { createSourceDesignApi } from "./webDesignReference";

describe("source design reference API", () => {
  it("requests the exact owned revision with authentication", async () => {
    const fetch = vi
      .fn()
      .mockResolvedValue(new Response(JSON.stringify({ source: { revision_id: "revision/a" } })));
    const result = await createSourceDesignApi(fetch).reference("project/a", "revision/a", "token");
    expect(fetch).toHaveBeenCalledWith(
      "/api/v1/projects/project%2Fa/web-source-revisions/revision%2Fa/design-reference",
      {
        credentials: "include",
        headers: { Accept: "application/json", Authorization: "Bearer token" },
      },
    );
    expect(result.source.revision_id).toBe("revision/a");
  });

  it("rejects inaccessible source ancestry", async () => {
    const fetch = vi.fn().mockResolvedValue(new Response("", { status: 409 }));
    await expect(
      createSourceDesignApi(fetch).reference("project", "revision", "token"),
    ).rejects.toMatchObject({ status: 409, detail: "SOURCE_DESIGN_REFERENCE_UNAVAILABLE" });
  });
});
