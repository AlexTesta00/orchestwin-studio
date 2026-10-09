import { describe, expect, it, vi } from "vitest";

import { createDesignCritiqueApi, DesignCritiqueApiError } from "./designCritique";
import type {
  DesignCritiqueRunPayload,
  DesignCritiqueSourcePayload,
} from "../types/designCritique";

const PROJECT_ID = "11111111-1111-4111-8111-111111111111";
const SOURCE_ID = "22222222-2222-4222-8222-222222222222";
const TWIN_ID = "44444444-4444-4444-8444-444444444444";
const ACCESS_TOKEN = "access-token";
const CRITIQUES = `/api/v1/projects/${PROJECT_ID}/design/critiques`;

const SOURCE: DesignCritiqueSourcePayload = {
  id: SOURCE_ID,
  project_id: PROJECT_ID,
  kind: "IMAGE",
  title: "Booking page",
  url: null,
  page: null,
  shots: [
    {
      code: "SCR-001",
      media_type: "image/png",
      byte_size: 8,
      sha256: "a".repeat(64),
      width: 1170,
      height: 2532,
      viewport_width: null,
    },
  ],
  created_at: "2026-10-09T10:00:00Z",
  content_hash: "b".repeat(64),
};

const RUN: DesignCritiqueRunPayload = {
  id: "33333333-3333-4333-8333-333333333333",
  project_id: PROJECT_ID,
  source: SOURCE,
  twins: [{ twin_id: TWIN_ID, version_number: 1, name: "Giulia" }],
  responses: [
    {
      twin_id: TWIN_ID,
      twin_version: 1,
      summary: "I find the times, but the button is far.",
      evidence_gaps: [],
      findings: [],
    },
  ],
  verdicts: [{ twin_id: TWIN_ID, anchor_key: "SCR-001", verdict: "WORKS" }],
  started_at: "2026-10-09T10:00:00Z",
  completed_at: "2026-10-09T10:02:22Z",
  duration_seconds: 142.2,
  cost_microusd: 0,
  content_hash: "c".repeat(64),
};

function jsonResponse(payload: unknown, status = 200): Response {
  return new Response(JSON.stringify(payload), {
    status,
    headers: { "Content-Type": "application/json" },
  });
}

function imageForm(): FormData {
  const form = new FormData();
  form.append("kind", "IMAGE");
  form.append("shots", new File(["fake-png"], "booking.png", { type: "image/png" }));
  return form;
}

describe("Design Critique API client", () => {
  it("uploads the image as the form it receives, without setting the content type", async () => {
    const fetchImpl = vi
      .fn<typeof fetch>()
      .mockResolvedValue(jsonResponse({ source: SOURCE }, 201));
    const api = createDesignCritiqueApi({ fetchImpl });
    const form = imageForm();

    const source = await api.uploadSource(PROJECT_ID, form, ACCESS_TOKEN);

    const call = fetchImpl.mock.calls[0];
    expect(fetchImpl).toHaveBeenCalledTimes(1);
    expect(call?.[0]).toBe(`${CRITIQUES}/sources`);
    expect(call?.[1]?.method).toBe("POST");
    expect(call?.[1]?.credentials).toBe("include");
    expect(call?.[1]?.headers).toEqual({
      Accept: "application/json",
      Authorization: `Bearer ${ACCESS_TOKEN}`,
    });
    expect(call?.[1]?.body).toBe(form);
    expect(source).toEqual(SOURCE);
  });

  it("reads the source also when the Studio answers with the bare snapshot", async () => {
    const fetchImpl = vi.fn<typeof fetch>().mockResolvedValue(jsonResponse(SOURCE, 201));
    const api = createDesignCritiqueApi({ fetchImpl });

    expect(await api.uploadSource(PROJECT_ID, imageForm(), ACCESS_TOKEN)).toEqual(SOURCE);
  });

  it("asks for the critique with the source and the locale and reads the run", async () => {
    const fetchImpl = vi
      .fn<typeof fetch>()
      .mockResolvedValue(jsonResponse({ status: "DESIGN_CRITIQUE_RECORDED", run: RUN }, 201));
    const api = createDesignCritiqueApi({ fetchImpl });

    const result = await api.critique(
      PROJECT_ID,
      { source_id: SOURCE_ID, locale: "it-IT" },
      ACCESS_TOKEN,
    );

    const call = fetchImpl.mock.calls[0];
    expect(call?.[0]).toBe(CRITIQUES);
    expect(call?.[1]?.method).toBe("POST");
    expect(call?.[1]?.headers).toEqual({
      Accept: "application/json",
      Authorization: `Bearer ${ACCESS_TOKEN}`,
      "Content-Type": "application/json",
    });
    expect(JSON.parse(String(call?.[1]?.body))).toEqual({ source_id: SOURCE_ID, locale: "it-IT" });
    expect(result).toEqual({ status: "DESIGN_CRITIQUE_RECORDED", run: RUN });
  });

  it("lists the critiques and the supplied designs of the project", async () => {
    const fetchImpl = vi
      .fn<typeof fetch>()
      .mockResolvedValueOnce(jsonResponse({ items: [RUN] }))
      .mockResolvedValueOnce(jsonResponse({ items: [SOURCE] }));
    const api = createDesignCritiqueApi({ fetchImpl });

    expect(await api.runs(PROJECT_ID, ACCESS_TOKEN)).toEqual([RUN]);
    expect(await api.sources(PROJECT_ID, ACCESS_TOKEN)).toEqual([SOURCE]);

    expect(fetchImpl.mock.calls.map((call) => [call[0], call[1]?.method, call[1]?.body])).toEqual([
      [CRITIQUES, "GET", undefined],
      [`${CRITIQUES}/sources`, "GET", undefined],
    ]);
    expect(fetchImpl.mock.calls[0]?.[1]?.headers).toEqual({
      Accept: "application/json",
      Authorization: `Bearer ${ACCESS_TOKEN}`,
    });
  });

  it("reads a screenshot as an image with its type", async () => {
    const fetchImpl = vi.fn<typeof fetch>().mockResolvedValue(
      new Response("fake-png", {
        status: 200,
        headers: { "Content-Type": "image/png", "Cache-Control": "private, max-age=0" },
      }),
    );
    const api = createDesignCritiqueApi({ fetchImpl });

    const shot = await api.shot(PROJECT_ID, SOURCE_ID, "SCR-001", ACCESS_TOKEN);

    const call = fetchImpl.mock.calls[0];
    expect(call?.[0]).toBe(`${CRITIQUES}/sources/${SOURCE_ID}/shots/SCR-001`);
    expect(call?.[1]?.method).toBe("GET");
    expect(call?.[1]?.headers).toEqual({
      Accept: "image/png, image/jpeg",
      Authorization: `Bearer ${ACCESS_TOKEN}`,
    });
    expect(shot).toBeInstanceOf(Blob);
    expect(shot.type).toBe("image/png");
    expect(await shot.text()).toBe("fake-png");
  });

  it("keeps only the media type of a JPEG screenshot", async () => {
    const fetchImpl = vi
      .fn<typeof fetch>()
      .mockResolvedValue(
        new Response("fake-jpeg", { status: 200, headers: { "Content-Type": "IMAGE/JPEG; q=1" } }),
      );
    const api = createDesignCritiqueApi({ fetchImpl });

    expect((await api.shot(PROJECT_ID, SOURCE_ID, "SCR-002", ACCESS_TOKEN)).type).toBe(
      "image/jpeg",
    );
  });

  it("encodes the project and the source and keeps a custom base path", async () => {
    const fetchImpl = vi
      .fn<typeof fetch>()
      .mockResolvedValueOnce(jsonResponse({ items: [] }))
      .mockResolvedValueOnce(new Response("png", { headers: { "Content-Type": "image/png" } }));
    const api = createDesignCritiqueApi({ basePath: "/studio/api/v1/", fetchImpl });

    await api.runs("project 1", ACCESS_TOKEN);
    await api.shot("project 1", "source/1", "SCR 1", ACCESS_TOKEN);

    expect(fetchImpl.mock.calls.map((call) => call[0])).toEqual([
      "/studio/api/v1/projects/project%201/design/critiques",
      "/studio/api/v1/projects/project%201/design/critiques/sources/source%2F1/shots/SCR%201",
    ]);
  });

  it("keeps the status, the code and the payload of a refusal", async () => {
    const twins = { detail: { code: "DESIGN_CRITIQUE_TWINS_REQUIRED" } };
    const fetchImpl = vi
      .fn<typeof fetch>()
      .mockResolvedValueOnce(jsonResponse(twins, 409))
      .mockResolvedValueOnce(
        jsonResponse({ detail: { code: "DESIGN_CRITIQUE_IMAGE_TOO_LARGE" } }, 413),
      )
      .mockResolvedValueOnce(
        jsonResponse({ detail: { code: "DESIGN_CRITIQUE_SOURCE_NOT_FOUND" } }, 404),
      )
      .mockResolvedValueOnce(jsonResponse({ detail: [{ type: "uuid_parsing" }] }, 422))
      .mockResolvedValueOnce(new Response("Bad gateway", { status: 502 }));
    const api = createDesignCritiqueApi({ fetchImpl });
    const body = { source_id: SOURCE_ID, locale: "en-US" };

    const refused = api.critique(PROJECT_ID, body, ACCESS_TOKEN);
    await expect(refused).rejects.toBeInstanceOf(DesignCritiqueApiError);
    await expect(refused).rejects.toMatchObject({
      name: "DesignCritiqueApiError",
      status: 409,
      code: "DESIGN_CRITIQUE_TWINS_REQUIRED",
      payload: twins,
    });
    await expect(api.uploadSource(PROJECT_ID, imageForm(), ACCESS_TOKEN)).rejects.toMatchObject({
      status: 413,
      code: "DESIGN_CRITIQUE_IMAGE_TOO_LARGE",
    });
    await expect(api.shot(PROJECT_ID, SOURCE_ID, "SCR-001", ACCESS_TOKEN)).rejects.toMatchObject({
      status: 404,
      code: "DESIGN_CRITIQUE_SOURCE_NOT_FOUND",
    });
    await expect(api.critique(PROJECT_ID, body, ACCESS_TOKEN)).rejects.toMatchObject({
      status: 422,
      code: null,
    });
    await expect(api.runs(PROJECT_ID, ACCESS_TOKEN)).rejects.toMatchObject({
      status: 502,
      code: null,
      payload: "Bad gateway",
    });
  });

  it("refuses an answer it cannot read", async () => {
    const fetchImpl = vi
      .fn<typeof fetch>()
      .mockResolvedValueOnce(new Response("<html>proxy</html>", { status: 201 }))
      .mockResolvedValueOnce(jsonResponse({ status: "DESIGN_CRITIQUE_RECORDED", run: {} }, 201))
      .mockResolvedValueOnce(jsonResponse({ items: [{ id: "run" }] }))
      .mockResolvedValueOnce(jsonResponse({ sources: [SOURCE] }))
      .mockResolvedValueOnce(
        new Response("<html>login</html>", {
          status: 200,
          headers: { "Content-Type": "text/html" },
        }),
      );
    const api = createDesignCritiqueApi({ fetchImpl });
    const unreadable = { name: "DesignCritiqueApiError", code: "INVALID_API_RESPONSE" };

    await expect(api.uploadSource(PROJECT_ID, imageForm(), ACCESS_TOKEN)).rejects.toMatchObject({
      ...unreadable,
      status: 201,
    });
    await expect(
      api.critique(PROJECT_ID, { source_id: SOURCE_ID, locale: "en-US" }, ACCESS_TOKEN),
    ).rejects.toMatchObject(unreadable);
    await expect(api.runs(PROJECT_ID, ACCESS_TOKEN)).rejects.toMatchObject(unreadable);
    await expect(api.sources(PROJECT_ID, ACCESS_TOKEN)).rejects.toMatchObject(unreadable);
    await expect(api.shot(PROJECT_ID, SOURCE_ID, "SCR-001", ACCESS_TOKEN)).rejects.toMatchObject(
      unreadable,
    );
  });

  it("refuses to call the Studio without an access token", async () => {
    const fetchImpl = vi.fn<typeof fetch>();
    const api = createDesignCritiqueApi({ fetchImpl });

    await expect(api.uploadSource(PROJECT_ID, imageForm(), " ")).rejects.toMatchObject({
      status: 0,
      code: "ACCESS_TOKEN_REQUIRED",
    });
    await expect(api.shot(PROJECT_ID, SOURCE_ID, "SCR-001", "")).rejects.toMatchObject({
      code: "ACCESS_TOKEN_REQUIRED",
    });
    expect(fetchImpl).not.toHaveBeenCalled();
  });
});
