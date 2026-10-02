import { describe, expect, it, vi } from "vitest";
import { clearFollowedGenerations } from "./generationJobs";
import { createResearchEvidenceApi, ResearchEvidenceApiError } from "./researchEvidence";
import type { ResearchEvidenceInput, ResearchEvidencePayload } from "../types/researchEvidence";

const evidence = { id: "source/one", version: 2 } as ResearchEvidencePayload;
const input: ResearchEvidenceInput = {
  title: "Synthetic note",
  source_kind: "OWNER_INPUT",
  source_ref: "Test source",
  context: "Synthetic calculator",
  method: "Test text",
  collected_at: null,
  limitations: "Not empirical",
  empirical: false,
  text: "  Synthetic text\r\nsecond line\n",
  acknowledged: true,
};

describe("researchEvidence API", () => {
  it("preserves text and uses owner credentials for versioned source operations", async () => {
    const fetchImpl = vi
      .fn<typeof fetch>()
      .mockImplementation(
        async () =>
          new Response(JSON.stringify({ status: "EVIDENCE_ADDED", evidence }), { status: 201 }),
      );
    const api = createResearchEvidenceApi({ fetchImpl, basePath: "/test/" });
    await api.add("project/one", input, " test-token ");
    expect(fetchImpl).toHaveBeenCalledWith(
      "/test/projects/project%2Fone/evidence",
      expect.objectContaining({
        method: "POST",
        credentials: "include",
        body: JSON.stringify(input),
        headers: expect.objectContaining({ Authorization: "Bearer test-token" }),
      }),
    );
    await api.revise("project/one", evidence.id, input, "test-token");
    expect(fetchImpl.mock.calls[1]?.[0]).toBe(
      "/test/projects/project%2Fone/evidence/source%2Fone/versions",
    );
    await api.show("project/one", evidence.id, 2, false, "test-token");
    expect(fetchImpl.mock.calls[2]?.[0]).toContain("?version=2&text=false");
    await api.deleteText("project/one", evidence.id, "test-token");
    expect(fetchImpl.mock.calls[3]?.[1]).toMatchObject({
      method: "DELETE",
      body: '{"acknowledged":true}',
    });
    await api.retire("project/one", evidence.id, "Synthetic source withdrawn", "test-token");
    expect(fetchImpl.mock.calls[4]?.[1]?.body).toBe('{"reason":"Synthetic source withdrawn"}');
  });

  it("requests an asynchronous evidence proposal and uses the existing single decision", async () => {
    clearFollowedGenerations();
    const fetchImpl = vi
      .fn<typeof fetch>()
      .mockImplementation(
        async () =>
          new Response(
            JSON.stringify({ status: "TWIN_UPDATE_PROPOSED", update: { id: "update" } }),
          ),
      );
    const api = createResearchEvidenceApi({ fetchImpl });
    await api.propose("project", "twin", evidence, "it-IT", "test-token");
    expect(fetchImpl.mock.calls[0]?.[1]).toMatchObject({
      headers: expect.objectContaining({ Prefer: "respond-async" }),
      body: JSON.stringify({ locale: "it-IT", evidence_id: evidence.id, evidence_version: 2 }),
    });
    await api.decide(
      "project",
      "update",
      { decision: "APPROVE", kept: [{ index: 0, statement: "Owner correction" }] },
      "test-token",
    );
    expect(fetchImpl.mock.calls[1]?.[0]).toBe(
      "/api/v1/projects/project/twin-updates/update/decision",
    );
    expect(fetchImpl.mock.calls[1]?.[1]?.body).toBe(
      '{"decision":"APPROVE","kept":[{"index":0,"statement":"Owner correction"}]}',
    );
  });

  it("refuses missing authentication before sending text and never retains reflected text in errors", async () => {
    const fetchImpl = vi.fn<typeof fetch>().mockResolvedValue(
      new Response(
        JSON.stringify({
          detail: { code: "EVIDENCE_LIMIT", document: "synthetic reflected document" },
        }),
        { status: 422 },
      ),
    );
    const api = createResearchEvidenceApi({ fetchImpl });
    await expect(api.add("project", input, " ")).rejects.toMatchObject({
      code: "ACCESS_TOKEN_REQUIRED",
    });
    expect(fetchImpl).not.toHaveBeenCalled();
    const error = await api
      .add("project", input, "test-token")
      .catch((failure: unknown) => failure);
    expect(error).toBeInstanceOf(ResearchEvidenceApiError);
    expect(error).toMatchObject({ code: "EVIDENCE_LIMIT", payload: null });
    expect(String(error)).not.toContain("reflected document");
  });
});
