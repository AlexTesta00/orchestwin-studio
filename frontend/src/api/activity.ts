import { accessTokenOf, basePathOf, detailCode, isRecord } from "./http";
import { ApiRequestError } from "./requestError";
import {
  ACTIVITY_KIND,
  ACTIVITY_SCHEMA_VERSION,
  type ActivityEventsRecorded,
  type ActivityEventsRequest,
  type ActivitySessionEnded,
  type ActivitySessionStarted,
  type ActivitySessionState,
  type ProjectActivity,
} from "../types/activity";

export class ActivityApiError extends ApiRequestError {}

export interface ActivityApi {
  current(projectId: string, token: string): Promise<ProjectActivity>;
  session(projectId: string, token: string): Promise<ActivitySessionState>;
  start(projectId: string, sessionCode: string, token: string): Promise<ActivitySessionStarted>;
  end(projectId: string, sessionCode: string, token: string): Promise<ActivitySessionEnded>;
  record(
    projectId: string,
    request: ActivityEventsRequest,
    token: string,
    options?: { keepalive?: boolean },
  ): Promise<ActivityEventsRecorded>;
}

function isSession(value: unknown): boolean {
  return isRecord(value) && typeof value.code === "string" && typeof value.started_at === "string";
}

function hasStatus(expected: string): (payload: unknown) => boolean {
  return (payload) =>
    isRecord(payload) && payload.status === expected && isSession(payload.session);
}

export function createActivityApi(
  options: { basePath?: string; fetchImpl?: typeof fetch } = {},
): ActivityApi {
  const base = basePathOf(options.basePath ?? "/api/v1", "Activity");
  const fetchImpl = options.fetchImpl ?? globalThis.fetch.bind(globalThis);
  const path = (project: string) => `${base}/projects/${encodeURIComponent(project)}/activity`;

  async function request<T>(
    url: string,
    token: string,
    accepted: (payload: unknown) => boolean,
    init: { method?: "GET" | "POST"; body?: unknown; keepalive?: boolean } = {},
  ): Promise<T> {
    const response = await fetchImpl(url, {
      method: init.method ?? "GET",
      credentials: "include",
      headers: {
        Accept: "application/json",
        Authorization: `Bearer ${accessTokenOf(token, ActivityApiError)}`,
        ...(init.body === undefined ? {} : { "Content-Type": "application/json" }),
      },
      ...(init.body === undefined ? {} : { body: JSON.stringify(init.body) }),
      ...(init.keepalive === true ? { keepalive: true } : {}),
    });
    let payload: unknown;
    try {
      payload = await response.json();
    } catch {
      payload = null;
    }
    if (!response.ok) {
      throw new ActivityApiError("The activity request failed", {
        status: response.status,
        code: detailCode(payload),
        payload: null,
      });
    }
    if (!accepted(payload)) {
      throw new ActivityApiError("Activity API returned an invalid response", {
        status: response.status,
        code: "INVALID_API_RESPONSE",
        payload: null,
      });
    }
    return payload as T;
  }

  return {
    current: (project, token) =>
      request(
        path(project),
        token,
        (payload) =>
          isRecord(payload) &&
          payload.kind === ACTIVITY_KIND &&
          payload.schema_version === ACTIVITY_SCHEMA_VERSION,
      ),
    session: (project, token) =>
      request(
        `${path(project)}/session`,
        token,
        (payload) =>
          isRecord(payload) &&
          typeof payload.active === "boolean" &&
          (payload.session === null || isSession(payload.session)),
      ),
    start: (project, sessionCode, token) =>
      request(`${path(project)}/sessions`, token, hasStatus("ACTIVITY_SESSION_STARTED"), {
        method: "POST",
        body: { session_code: sessionCode },
      }),
    end: (project, sessionCode, token) =>
      request(
        `${path(project)}/sessions/${encodeURIComponent(sessionCode)}/end`,
        token,
        hasStatus("ACTIVITY_SESSION_ENDED"),
        { method: "POST" },
      ),
    record: (project, body, token, settings = {}) =>
      request(
        `${path(project)}/events`,
        token,
        (payload) =>
          isRecord(payload) &&
          payload.status === "ACTIVITY_EVENTS_RECORDED" &&
          typeof payload.recorded === "number",
        { method: "POST", body, keepalive: settings.keepalive === true },
      ),
  };
}

export const activityApi = createActivityApi();
