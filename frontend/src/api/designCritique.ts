import { ApiRequestError } from "./requestError";

import type {
  DesignCritiqueRequest,
  DesignCritiqueResultPayload,
  DesignCritiqueRunPayload,
  DesignCritiqueSourcePayload,
} from "../types/designCritique";

const DEFAULT_API_BASE_PATH = "/api/v1";
const JSON_MEDIA_TYPE = "application/json";
const SHOT_MEDIA_TYPES: ReadonlySet<string> = new Set(["image/png", "image/jpeg"]);

type HttpMethod = "GET" | "POST";

interface Outgoing {
  method: HttpMethod;
  accept: string;
  form?: FormData;
  json?: DesignCritiqueRequest;
}

export interface DesignCritiqueApiOptions {
  basePath?: string;
  fetchImpl?: typeof fetch;
}

export class DesignCritiqueApiError extends ApiRequestError {}

export interface DesignCritiqueApi {
  uploadSource(
    projectId: string,
    form: FormData,
    accessToken: string,
  ): Promise<DesignCritiqueSourcePayload>;
  sources(projectId: string, accessToken: string): Promise<DesignCritiqueSourcePayload[]>;
  shot(projectId: string, sourceId: string, code: string, accessToken: string): Promise<Blob>;
  critique(
    projectId: string,
    body: DesignCritiqueRequest,
    accessToken: string,
  ): Promise<DesignCritiqueResultPayload>;
  runs(projectId: string, accessToken: string): Promise<DesignCritiqueRunPayload[]>;
}

function normalizedBasePath(value: string): string {
  const normalized = value.trim().replace(/\/+$/, "");

  if (normalized.length === 0) {
    throw new Error("Design Critique API base path must not be empty");
  }

  return normalized;
}

function requiredAccessToken(value: string): string {
  const normalized = value.trim();

  if (normalized.length === 0) {
    throw new DesignCritiqueApiError("Authentication is required", {
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

function errorCode(payload: unknown): string | null {
  if (!isRecord(payload) || !isRecord(payload.detail)) {
    return null;
  }

  return typeof payload.detail.code === "string" ? payload.detail.code : null;
}

function isSource(value: unknown): value is DesignCritiqueSourcePayload {
  return (
    isRecord(value) &&
    typeof value.id === "string" &&
    typeof value.title === "string" &&
    typeof value.kind === "string" &&
    Array.isArray(value.shots)
  );
}

function isRun(value: unknown): value is DesignCritiqueRunPayload {
  return (
    isRecord(value) &&
    typeof value.id === "string" &&
    isSource(value.source) &&
    Array.isArray(value.twins) &&
    Array.isArray(value.responses) &&
    Array.isArray(value.verdicts)
  );
}

function itemsOf<T>(payload: unknown, accepts: (value: unknown) => value is T): T[] | null {
  if (!isRecord(payload) || !Array.isArray(payload.items) || !payload.items.every(accepts)) {
    return null;
  }

  return payload.items;
}

function sourceOf(payload: unknown): DesignCritiqueSourcePayload | null {
  if (isRecord(payload) && isSource(payload.source)) {
    return payload.source;
  }

  return isSource(payload) ? payload : null;
}

function mediaTypeOf(response: Response): string {
  return (response.headers.get("Content-Type") ?? "").split(";")[0]?.trim().toLowerCase() ?? "";
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

function critiquesPath(basePath: string, projectId: string): string {
  return `${basePath}/projects/${encodeURIComponent(projectId)}/design/critiques`;
}

export function createDesignCritiqueApi(options: DesignCritiqueApiOptions = {}): DesignCritiqueApi {
  const basePath = normalizedBasePath(options.basePath ?? DEFAULT_API_BASE_PATH);

  function send(path: string, outgoing: Outgoing, accessToken: string): Promise<Response> {
    const headers: Record<string, string> = {
      Accept: outgoing.accept,
      Authorization: `Bearer ${requiredAccessToken(accessToken)}`,
    };
    const init: RequestInit = { method: outgoing.method, credentials: "include", headers };

    if (outgoing.form !== undefined) {
      init.body = outgoing.form;
    } else if (outgoing.json !== undefined) {
      headers["Content-Type"] = JSON_MEDIA_TYPE;
      init.body = JSON.stringify(outgoing.json);
    }

    const fetchImpl = options.fetchImpl ?? globalThis.fetch.bind(globalThis);
    return fetchImpl(path, init);
  }

  function failure(response: Response, payload: unknown): DesignCritiqueApiError {
    return new DesignCritiqueApiError("The design critique request failed", {
      status: response.status,
      code: errorCode(payload),
      payload,
    });
  }

  function unexpected(response: Response, payload: unknown): DesignCritiqueApiError {
    return new DesignCritiqueApiError("The Design Critique API returned an unexpected answer", {
      status: response.status,
      code: "INVALID_API_RESPONSE",
      payload,
    });
  }

  async function exchange(
    path: string,
    outgoing: Outgoing,
    accessToken: string,
  ): Promise<{ response: Response; payload: unknown }> {
    const response = await send(path, outgoing, accessToken);
    const payload = await responsePayload(response);

    if (!response.ok) {
      throw failure(response, payload);
    }

    return { response, payload };
  }

  return {
    async uploadSource(projectId, form, accessToken) {
      const { response, payload } = await exchange(
        `${critiquesPath(basePath, projectId)}/sources`,
        { method: "POST", accept: JSON_MEDIA_TYPE, form },
        accessToken,
      );
      const source = sourceOf(payload);

      if (source === null) {
        throw unexpected(response, payload);
      }

      return source;
    },

    async sources(projectId, accessToken) {
      const { response, payload } = await exchange(
        `${critiquesPath(basePath, projectId)}/sources`,
        { method: "GET", accept: JSON_MEDIA_TYPE },
        accessToken,
      );
      const items = itemsOf(payload, isSource);

      if (items === null) {
        throw unexpected(response, payload);
      }

      return items;
    },

    async shot(projectId, sourceId, code, accessToken) {
      const response = await send(
        `${critiquesPath(basePath, projectId)}/sources/${encodeURIComponent(sourceId)}/shots/${encodeURIComponent(code)}`,
        { method: "GET", accept: [...SHOT_MEDIA_TYPES].join(", ") },
        accessToken,
      );

      if (!response.ok) {
        throw failure(response, await responsePayload(response));
      }

      const type = mediaTypeOf(response);

      if (!SHOT_MEDIA_TYPES.has(type)) {
        throw unexpected(response, null);
      }

      return new Blob([await response.arrayBuffer()], { type });
    },

    async critique(projectId, body, accessToken) {
      const { response, payload } = await exchange(
        critiquesPath(basePath, projectId),
        {
          method: "POST",
          accept: JSON_MEDIA_TYPE,
          json: { source_id: body.source_id, locale: body.locale },
        },
        accessToken,
      );

      if (
        !isRecord(payload) ||
        payload.status !== "DESIGN_CRITIQUE_RECORDED" ||
        !isRun(payload.run)
      ) {
        throw unexpected(response, payload);
      }

      return { status: "DESIGN_CRITIQUE_RECORDED", run: payload.run };
    },

    async runs(projectId, accessToken) {
      const { response, payload } = await exchange(
        critiquesPath(basePath, projectId),
        { method: "GET", accept: JSON_MEDIA_TYPE },
        accessToken,
      );
      const items = itemsOf(payload, isRun);

      if (items === null) {
        throw unexpected(response, payload);
      }

      return items;
    },
  };
}

export const designCritiqueApi = createDesignCritiqueApi();
