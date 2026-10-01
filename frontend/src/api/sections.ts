import { PROJECT_STAGES } from "./contracts";
import { ApiRequestError } from "./requestError";

import type { ProjectSectionsPayload, SectionsAlignmentPayload } from "../types/sections";

const DEFAULT_API_BASE_PATH = "/api/v1";
const ABSENT_STATUSES: ReadonlySet<number> = new Set([404, 405]);
const STAGES: ReadonlySet<string> = new Set(PROJECT_STAGES);
const STATES: ReadonlySet<string> = new Set([
  "NOT_STARTED",
  "IN_PROGRESS",
  "FINE",
  "UPDATE_AVAILABLE",
  "TO_UPDATE",
]);
const ALIGNABLE: ReadonlySet<string> = new Set(["USER_TWINS", "REQUIREMENTS", "DESIGN"]);
const STATUSES: ReadonlySet<string> = new Set(["ALIGNED", "PARTIAL", "NOTHING_TO_ALIGN"]);
const OUTCOMES: ReadonlySet<string> = new Set(["ALIGNED", "BLOCKED", "SKIPPED"]);

export interface SectionsApiOptions {
  basePath?: string;
  fetchImpl?: typeof fetch;
}

export class SectionsApiError extends ApiRequestError {}

export interface SectionsApi {
  read(projectId: string, accessToken: string): Promise<ProjectSectionsPayload | null>;
  align(projectId: string, accessToken: string): Promise<SectionsAlignmentPayload>;
}

function normalizedBasePath(value: string): string {
  const normalized = value.trim().replace(/\/+$/, "");

  if (normalized.length === 0) {
    throw new Error("Sections API base path must not be empty");
  }

  return normalized;
}

function requiredAccessToken(value: string): string {
  const normalized = value.trim();

  if (normalized.length === 0) {
    throw new SectionsApiError("Authentication is required", {
      status: 0,
      code: "ACCESS_TOKEN_REQUIRED",
      payload: null,
    });
  }

  return normalized;
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

function isTextList(value: unknown): boolean {
  return Array.isArray(value) && value.every((item) => typeof item === "string");
}

function isVersion(value: unknown): boolean {
  return value === null || (typeof value === "number" && Number.isInteger(value));
}

function errorCode(payload: unknown): string | null {
  if (!isRecord(payload) || !isRecord(payload.detail)) {
    return null;
  }

  return typeof payload.detail.code === "string" ? payload.detail.code : null;
}

async function responsePayload(response: Response): Promise<unknown> {
  const text = await response.text();

  if (text.trim().length === 0) {
    return null;
  }

  try {
    return JSON.parse(text) as unknown;
  } catch {
    return text;
  }
}

function isSection(value: unknown): boolean {
  return (
    isRecord(value) &&
    typeof value.key === "string" &&
    STAGES.has(value.key) &&
    typeof value.state === "string" &&
    STATES.has(value.state) &&
    isVersion(value.version_number) &&
    isTextList(value.reasons) &&
    (value.blocked === null || typeof value.blocked === "string") &&
    isTextList(value.codes)
  );
}

function isAlignmentSummary(value: unknown): boolean {
  return (
    isRecord(value) &&
    typeof value.available === "boolean" &&
    Array.isArray(value.sections) &&
    value.sections.every((key) => typeof key === "string" && ALIGNABLE.has(key)) &&
    isTextList(value.uncovered_codes)
  );
}

function isSections(value: unknown): boolean {
  return (
    isRecord(value) &&
    typeof value.first_pass_complete === "boolean" &&
    Array.isArray(value.sections) &&
    value.sections.every(isSection) &&
    isAlignmentSummary(value.alignment)
  );
}

function isResult(value: unknown): boolean {
  return (
    isRecord(value) &&
    typeof value.key === "string" &&
    ALIGNABLE.has(value.key) &&
    typeof value.outcome === "string" &&
    OUTCOMES.has(value.outcome) &&
    (value.issue === null || typeof value.issue === "string") &&
    isVersion(value.version_number) &&
    isTextList(value.codes)
  );
}

function isAlignment(value: unknown): boolean {
  return (
    isRecord(value) &&
    typeof value.status === "string" &&
    STATUSES.has(value.status) &&
    Array.isArray(value.results) &&
    value.results.every(isResult) &&
    isSections(value.sections)
  );
}

function sectionsPath(basePath: string, projectId: string): string {
  return `${basePath}/projects/${encodeURIComponent(projectId)}/sections`;
}

export function createSectionsApi(options: SectionsApiOptions = {}): SectionsApi {
  const basePath = normalizedBasePath(options.basePath ?? DEFAULT_API_BASE_PATH);
  const fetchImpl = options.fetchImpl ?? globalThis.fetch.bind(globalThis);

  async function request(
    path: string,
    method: "GET" | "POST",
    accessToken: string,
  ): Promise<{ response: Response; payload: unknown }> {
    const response = await fetchImpl(path, {
      method,
      credentials: "include",
      headers: {
        Accept: "application/json",
        Authorization: `Bearer ${requiredAccessToken(accessToken)}`,
      },
    });

    return { response, payload: await responsePayload(response) };
  }

  function failure(response: Response, payload: unknown): SectionsApiError {
    return new SectionsApiError("The sections request failed", {
      status: response.status,
      code: errorCode(payload),
      payload,
    });
  }

  function invalid(response: Response, payload: unknown): SectionsApiError {
    return new SectionsApiError("The Sections API returned invalid JSON", {
      status: response.status,
      code: "INVALID_API_RESPONSE",
      payload,
    });
  }

  return {
    async read(projectId, accessToken) {
      const { response, payload } = await request(
        sectionsPath(basePath, projectId),
        "GET",
        accessToken,
      );

      if (ABSENT_STATUSES.has(response.status)) {
        return null;
      }

      if (!response.ok) {
        throw failure(response, payload);
      }

      if (!isSections(payload)) {
        throw invalid(response, payload);
      }

      return payload as unknown as ProjectSectionsPayload;
    },

    async align(projectId, accessToken) {
      const { response, payload } = await request(
        `${sectionsPath(basePath, projectId)}/alignment`,
        "POST",
        accessToken,
      );

      if (!response.ok) {
        throw failure(response, payload);
      }

      if (!isAlignment(payload)) {
        throw invalid(response, payload);
      }

      return payload as unknown as SectionsAlignmentPayload;
    },
  };
}

export const sectionsApi = createSectionsApi();
