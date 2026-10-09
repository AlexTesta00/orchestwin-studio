import { describe, expect, it, vi } from "vitest";

import {
  createDesignIterationsApi,
  type DesignIterationItem,
  type IterationJobBody,
} from "./designIterations";

const PROJECT_ID = "00000000-0000-4000-8000-000000000101";
const SOURCE_ID = "00000000-0000-4000-8000-000000004401";

function response(status: number, body: unknown): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "Content-Type": "application/json" },
  });
}

function sentBody(fetchImpl: { mock: { calls: Parameters<typeof fetch>[] } }, index: number) {
  return JSON.parse(String(fetchImpl.mock.calls[index]?.[1]?.body)) as Record<string, unknown>;
}

const BASE: IterationJobBody = {
  design_version_id: "00000000-0000-4000-8000-000000000160",
  design_content_hash: "1".repeat(64),
  request: "Ridisegna il mockup perché riproduca l'aspetto del design fornito «Hotel desk».",
  assertions: [],
};

const ITERATION: DesignIterationItem = {
  generation_id: "generation-1",
  requested_at: "2026-10-09T10:00:00+00:00",
  request: BASE.request,
  assertions: [],
  changes: ["The layout follows the supplied design"],
  status: "PROPOSED",
  base_design_version_number: 2,
  applied_design_version_number: null,
  cost_microusd: 0,
};

describe("design iterations api with a supplied design", () => {
  it("sends the supplied design of a redraw only when it is given", async () => {
    const fetchImpl = vi.fn<typeof fetch>(async () =>
      response(202, { job_id: "job-1", kind: "ITERATION", status: "RUNNING" }),
    );
    const api = createDesignIterationsApi({ fetchImpl });

    await api.startJob(PROJECT_ID, { ...BASE, critique_source_id: SOURCE_ID }, "token");
    await api.startJob(PROJECT_ID, BASE, "token");

    expect(fetchImpl.mock.calls.map((call) => String(call[0]))).toEqual([
      `/api/v1/projects/${PROJECT_ID}/design/iterations/jobs`,
      `/api/v1/projects/${PROJECT_ID}/design/iterations/jobs`,
    ]);
    expect(sentBody(fetchImpl, 0)).toEqual({ ...BASE, critique_source_id: SOURCE_ID });
    expect(Object.keys(sentBody(fetchImpl, 1))).toEqual([
      "design_version_id",
      "design_content_hash",
      "request",
      "assertions",
    ]);
  });

  it("keeps the supplied design next to every iteration of the list", async () => {
    const items: DesignIterationItem[] = [
      { ...ITERATION, critique_source_id: SOURCE_ID },
      { ...ITERATION, generation_id: "generation-0", critique_source_id: null },
      { ...ITERATION, generation_id: "generation-old" },
    ];
    const api = createDesignIterationsApi({ fetchImpl: async () => response(200, { items }) });

    const listed = await api.list(PROJECT_ID, "token");

    expect(listed.items.map((item) => item.critique_source_id)).toEqual([
      SOURCE_ID,
      null,
      undefined,
    ]);
    expect(listed).toEqual({ items });
  });
});
