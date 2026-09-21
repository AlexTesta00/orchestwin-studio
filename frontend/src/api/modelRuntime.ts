import { ApiRequestError } from "./requestError";

export interface ModelRuntimeReadiness {
  mode: "DEVELOPMENT_FIXTURES" | "REAL_REQUIRED";
  ready: boolean;
  code?: string;
  components?: Record<string, { ready: boolean; code?: string }>;
}

export async function modelRuntimeReadiness(
  token: string,
  fetchImpl: typeof fetch = globalThis.fetch.bind(globalThis),
): Promise<ModelRuntimeReadiness> {
  if (!token.trim())
    throw new ApiRequestError("Authentication required", {
      status: 0,
      code: "ACCESS_TOKEN_REQUIRED",
      payload: null,
    });
  const response = await fetchImpl("/api/v1/model-runtime/readiness", {
    credentials: "include",
    headers: { Accept: "application/json", Authorization: `Bearer ${token.trim()}` },
  });
  const payload = (await response.json().catch(() => null)) as ModelRuntimeReadiness | null;
  if (
    (response.status !== 200 && response.status !== 503) ||
    !payload ||
    !["DEVELOPMENT_FIXTURES", "REAL_REQUIRED"].includes(payload.mode) ||
    typeof payload.ready !== "boolean" ||
    (response.status === 503 && payload.ready)
  ) {
    throw new ApiRequestError("Model status unavailable", {
      status: response.status,
      code: null,
      payload,
    });
  }
  return payload;
}
