import { describe, expect, it, vi } from "vitest";

import { createFinalizationApi, FinalizationApiError } from "./finalization";

function jsonResponse(value: unknown, status = 200): Response {
  return new Response(JSON.stringify(value), {
    status,
    headers: { "Content-Type": "application/json" },
  });
}

describe("finalization API", () => {
  it("sends exact evaluation, Gate 8, and export requests", async () => {
    const fetchImpl = vi.fn<typeof fetch>().mockImplementation(async (input) => {
      const url = String(input);
      if (url.endsWith("/findings")) {
        return jsonResponse({ items: [] });
      }
      if (url.endsWith("/final-reviews")) {
        return jsonResponse({ items: [] });
      }
      return jsonResponse({
        snapshot: { id: "resource-1", ready_for_gate8: true },
        status: "APPLIED",
        message: "Applied.",
      });
    });
    const api = createFinalizationApi({ fetchImpl });

    await api.evaluationRun("evaluation-1", "token");
    await api.findings("evaluation-1", "token");
    await api.aggregation("evaluation-1", "token");
    await api.finalReviews("project-1", "token");
    await api.submitFinalReview(
      "review-1",
      {
        expected_version: 1,
        expected_content_hash: "a".repeat(64),
        gate_id: "gate-1",
        event_id: "event-1",
        occurred_at: "2026-08-31T04:00:00Z",
      },
      "token",
    );

    const lastCall = fetchImpl.mock.calls.at(-1);
    expect(String(lastCall?.[0])).toBe("/api/v1/final-reviews/review-1/submit");
    expect(lastCall?.[1]?.method).toBe("POST");
    expect(new Headers(lastCall?.[1]?.headers).get("Authorization")).toBe("Bearer token");
  });

  it("returns safe download metadata and typed failures", async () => {
    const downloadApi = createFinalizationApi({
      fetchImpl: vi.fn().mockResolvedValue(
        new Response(new Blob(["archive"]), {
          headers: {
            "Content-Type": "application/zip",
            "Content-Disposition": 'attachment; filename="project-export.zip"',
            ETag: '"sha256:abc"',
          },
        }),
      ),
    });

    const download = await downloadApi.downloadExport("export-1", "token");
    expect(download.filename).toBe("project-export.zip");
    expect(download.etag).toBe('"sha256:abc"');

    const failingApi = createFinalizationApi({
      fetchImpl: vi
        .fn()
        .mockResolvedValue(jsonResponse({ detail: { code: "FINAL_EXPORT_NOT_FOUND" } }, 404)),
    });
    await expect(failingApi.exportBundle("missing", "token")).rejects.toBeInstanceOf(
      FinalizationApiError,
    );
  });
});
