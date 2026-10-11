import type { ApiRequestError } from "./requestError";

export function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

export function detailCode(payload: unknown): string | null {
  if (!isRecord(payload) || !isRecord(payload.detail)) {
    return null;
  }

  return typeof payload.detail.code === "string" ? payload.detail.code : null;
}

export async function responseBody(
  response: Response,
  ErrorClass?: typeof ApiRequestError,
  label = "",
): Promise<unknown> {
  const text = await response.text();

  if (text.trim().length === 0) {
    return null;
  }

  try {
    return JSON.parse(text) as unknown;
  } catch {
    if (ErrorClass === undefined) {
      return text;
    }

    throw new ErrorClass(`The ${label} API returned invalid JSON`, {
      status: response.status,
      code: "INVALID_API_RESPONSE",
      payload: text,
    });
  }
}

export function basePathOf(value: string, label: string): string {
  const normalized = value.trim().replace(/\/+$/, "");

  if (normalized.length === 0) {
    throw new Error(`${label} API base path must not be empty`);
  }

  return normalized;
}

export function absoluteBasePathOf(value: string, label: string): string {
  const normalized = value.trim().replace(/\/+$/u, "");

  if (normalized.length === 0 || !normalized.startsWith("/") || normalized.startsWith("//")) {
    throw new Error(`${label} API base path must be an absolute application path`);
  }

  return normalized;
}

export function accessTokenOf(value: string, ErrorClass: typeof ApiRequestError): string {
  const normalized = value.trim();

  if (normalized.length === 0) {
    throw new ErrorClass("Authentication is required", {
      status: 0,
      code: "ACCESS_TOKEN_REQUIRED",
      payload: null,
    });
  }

  return normalized;
}
