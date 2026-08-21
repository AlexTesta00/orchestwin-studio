import type { CrossStageArtifactGraphPayload } from "../types/artifacts";

const DEFAULT_API_BASE_PATH = "/api/v1";

export interface ArtifactGraphApiOptions {
  basePath?: string;
  fetchImpl?: typeof fetch;
}

export class ArtifactGraphApiError extends Error {
  readonly status: number;
  readonly code: string | null;
  readonly payload: unknown;

  constructor(
    message: string,
    options: {
      status: number;
      code: string | null;
      payload: unknown;
    },
  ) {
    super(message);
    this.name = "ArtifactGraphApiError";
    this.status = options.status;
    this.code = options.code;
    this.payload = options.payload;
  }
}

export interface ArtifactGraphApi {
  current(projectId: string, accessToken: string): Promise<CrossStageArtifactGraphPayload>;
  exportCurrent(projectId: string, accessToken: string): Promise<Blob>;
}

function normalizedBasePath(value: string): string {
  const normalized = value.trim().replace(/\/+$/, "");

  if (normalized.length === 0) {
    throw new Error("Artifact Graph API base path must not be empty");
  }

  return normalized;
}

function requiredAccessToken(value: string): string {
  const normalized = value.trim();

  if (normalized.length === 0) {
    throw new ArtifactGraphApiError("Authentication is required", {
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

function graphPath(basePath: string, projectId: string): string {
  return `${basePath}/projects/${encodeURIComponent(projectId)}/artifacts/graph`;
}

export function createArtifactGraphApi(options: ArtifactGraphApiOptions = {}): ArtifactGraphApi {
  const basePath = normalizedBasePath(options.basePath ?? DEFAULT_API_BASE_PATH);
  const fetchImpl = options.fetchImpl ?? globalThis.fetch.bind(globalThis);

  async function authenticatedFetch(
    path: string,
    accessToken: string,
    accept: string,
  ): Promise<Response> {
    const response = await fetchImpl(path, {
      method: "GET",
      credentials: "include",
      headers: {
        Accept: accept,
        Authorization: `Bearer ${requiredAccessToken(accessToken)}`,
      },
    });

    if (!response.ok) {
      const payload = await responsePayload(response);
      throw new ArtifactGraphApiError("The Artifact Graph request failed", {
        status: response.status,
        code: errorCode(payload),
        payload,
      });
    }

    return response;
  }

  return {
    async current(projectId, accessToken) {
      const response = await authenticatedFetch(
        graphPath(basePath, projectId),
        accessToken,
        "application/json",
      );
      const payload = await responsePayload(response);

      if (!isRecord(payload)) {
        throw new ArtifactGraphApiError("The Artifact Graph API returned invalid JSON", {
          status: response.status,
          code: "INVALID_API_RESPONSE",
          payload,
        });
      }

      return payload as unknown as CrossStageArtifactGraphPayload;
    },

    async exportCurrent(projectId, accessToken) {
      const response = await authenticatedFetch(
        `${graphPath(basePath, projectId)}/export`,
        accessToken,
        "application/json",
      );

      return response.blob();
    },
  };
}

export const artifactGraphApi = createArtifactGraphApi();
