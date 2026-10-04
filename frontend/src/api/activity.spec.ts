import { describe, expect, it, vi } from "vitest";

import { ActivityApiError, createActivityApi } from "./activity";
import type { ActivityEventsRequest } from "../types/activity";

const response = (payload: unknown, status = 200) =>
  ({ ok: status < 400, status, json: async () => payload }) as Response;

const SESSION = { code: "SES-P01", started_at: "2026-10-04T09:00:00+00:00" };

const BATCH: ActivityEventsRequest = {
  session_code: "SES-P01",
  source: "WEB",
  events: [
    {
      kind: "SECTION_OPENED",
      section: "DESIGN",
      target: null,
      client_at: "2026-10-04T09:00:01.000Z",
      duration_ms: null,
      status: null,
    },
  ],
};

describe("Activity API", () => {
  it("reads the session and the activity document of the project without a body", async () => {
    const fetchImpl = vi
      .fn()
      .mockResolvedValueOnce(response({ active: true, session: SESSION }))
      .mockResolvedValueOnce(response({ active: false, session: null }))
      .mockResolvedValueOnce(
        response({ kind: "orchestwin.project-activity", schema_version: 1, events: [] }),
      );
    const api = createActivityApi({ fetchImpl });

    await expect(api.session("project/a", " token ")).resolves.toEqual({
      active: true,
      session: SESSION,
    });
    await expect(api.session("project/a", "token")).resolves.toEqual({
      active: false,
      session: null,
    });
    await api.current("project/a", "token");

    expect(fetchImpl.mock.calls.map((call) => call[0])).toEqual([
      "/api/v1/projects/project%2Fa/activity/session",
      "/api/v1/projects/project%2Fa/activity/session",
      "/api/v1/projects/project%2Fa/activity",
    ]);
    for (const [, init] of fetchImpl.mock.calls)
      expect(init).toEqual({
        method: "GET",
        credentials: "include",
        headers: { Accept: "application/json", Authorization: "Bearer token" },
      });
  });

  it("starts and ends a session with its code only and sends a batch, kept alive only when asked", async () => {
    const fetchImpl = vi
      .fn()
      .mockResolvedValueOnce(
        response({ status: "ACTIVITY_SESSION_STARTED", session: SESSION }, 201),
      )
      .mockResolvedValueOnce(response({ status: "ACTIVITY_EVENTS_RECORDED", recorded: 1 }, 202))
      .mockResolvedValueOnce(response({ status: "ACTIVITY_EVENTS_RECORDED", recorded: 1 }, 202))
      .mockResolvedValueOnce(
        response({
          status: "ACTIVITY_SESSION_ENDED",
          session: { ...SESSION, ended_at: "2026-10-04T10:00:00+00:00" },
        }),
      );
    const api = createActivityApi({ basePath: "/studio/api/", fetchImpl });

    await api.start("project", "SES-P01", "token");
    await expect(api.record("project", BATCH, "token")).resolves.toEqual({
      status: "ACTIVITY_EVENTS_RECORDED",
      recorded: 1,
    });
    await api.record("project", BATCH, "token", { keepalive: true });
    await api.end("project", "SES-P01", "token");

    const [start, batch, kept, end] = fetchImpl.mock.calls;
    expect(start?.[0]).toBe("/studio/api/projects/project/activity/sessions");
    expect(start?.[1]).toMatchObject({ method: "POST", credentials: "include" });
    expect(JSON.parse(start?.[1].body)).toEqual({ session_code: "SES-P01" });
    expect(start?.[1].headers).toEqual({
      Accept: "application/json",
      Authorization: "Bearer token",
      "Content-Type": "application/json",
    });
    expect(batch?.[0]).toBe("/studio/api/projects/project/activity/events");
    expect(JSON.parse(batch?.[1].body)).toEqual(BATCH);
    expect(batch?.[1]).not.toHaveProperty("keepalive");
    expect(kept?.[1]).toMatchObject({ method: "POST", keepalive: true });
    expect(end?.[0]).toBe("/studio/api/projects/project/activity/sessions/SES-P01/end");
    expect(end?.[1]).toEqual({
      method: "POST",
      credentials: "include",
      headers: { Accept: "application/json", Authorization: "Bearer token" },
    });
  });

  it.each([
    [409, "ACTIVITY_SESSION_ACTIVE"],
    [409, "ACTIVITY_SESSION_CODE_USED"],
    [409, "ACTIVITY_SESSION_NOT_ACTIVE"],
    [409, "ACTIVITY_JOURNAL_FULL"],
    [422, "ACTIVITY_INPUT_INVALID"],
    [404, "PROJECT_NOT_FOUND"],
    [503, "ACTIVITY_SERVICE_UNAVAILABLE"],
  ])("keeps the %s code %s without copying the answer", async (status, code) => {
    const fetchImpl = vi
      .fn()
      .mockResolvedValue(response({ detail: { code, session_code: "SES-PRIVATE" } }, status));
    const failure = createActivityApi({ fetchImpl }).start("project", "SES-P01", "token");

    await expect(failure).rejects.toBeInstanceOf(ActivityApiError);
    await expect(failure).rejects.toMatchObject({ status, code, detail: code, payload: null });
  });

  it("asks nothing without a token and refuses answers of another shape", async () => {
    const fetchImpl = vi
      .fn()
      .mockResolvedValueOnce(response({ active: "yes", session: null }))
      .mockResolvedValueOnce(response({ status: "ACTIVITY_SESSION_ENDED", session: SESSION }))
      .mockResolvedValueOnce(response({ kind: "orchestwin.project-activity", schema_version: 2 }))
      .mockResolvedValueOnce(response({ status: "ACTIVITY_EVENTS_RECORDED" }, 202));
    const api = createActivityApi({ fetchImpl });

    await expect(api.session("project", " ")).rejects.toMatchObject({
      status: 0,
      code: "ACCESS_TOKEN_REQUIRED",
    });
    expect(fetchImpl).not.toHaveBeenCalled();
    for (const call of [
      () => api.session("project", "token"),
      () => api.start("project", "SES-P01", "token"),
      () => api.current("project", "token"),
      () => api.record("project", BATCH, "token"),
    ]) {
      await expect(call()).rejects.toMatchObject({ code: "INVALID_API_RESPONSE", payload: null });
    }
    expect(() => createActivityApi({ basePath: " / ", fetchImpl })).toThrow(
      "Activity API base path must not be empty",
    );
  });
});
