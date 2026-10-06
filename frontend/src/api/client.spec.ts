import { describe, expect, it, vi } from "vitest";

import { ApiClient, ApiError, onRequestFailure, resolveApiBaseUrl } from "./client";
import { ApiRequestError } from "./requestError";

describe("ApiClient", () => {
  it("uses a same-origin API path by default", () => {
    expect(resolveApiBaseUrl("")).toBe("/api/v1");
  });

  it("normalizes a relative API base URL", () => {
    expect(resolveApiBaseUrl("/api/v1/")).toBe("/api/v1");
  });

  it("normalizes an absolute API base URL", () => {
    expect(resolveApiBaseUrl("http://localhost:8000/api/v1/")).toBe("http://localhost:8000/api/v1");
  });

  it("rejects protocol-relative API URLs", () => {
    expect(() => resolveApiBaseUrl("//example.test/api/v1")).toThrow(
      "API base URL must not be protocol-relative",
    );
  });

  it("binds the fetch implementation to the global scope", async () => {
    const receiverAwareFetch: typeof fetch = async function (
      this: typeof globalThis,
      input: RequestInfo | URL,
      init?: RequestInit,
    ): Promise<Response> {
      expect(this).toBe(globalThis);

      void input;
      void init;

      return new Response(
        JSON.stringify({
          access_token: "access-token",
          token_type: "bearer",
          expires_at: "2026-08-10T12:15:00Z",
          user: {
            id: "00000000-0000-4000-8000-000000000001",
            email: "owner@example.com",
            is_active: true,
            created_at: "2026-08-10T12:00:00Z",
            guidance_mode: null,
          },
        }),
        {
          status: 200,
          headers: {
            "Content-Type": "application/json",
          },
        },
      );
    };

    const client = new ApiClient("/api/v1", receiverAwareFetch);

    const response = await client.login({
      email: "owner@example.com",
      password: "correct horse battery staple",
    });

    expect(response.access_token).toBe("access-token");
  });

  it("sends credentials and JSON for login", async () => {
    const fetchImplementation = vi.fn<typeof fetch>().mockResolvedValue(
      new Response(
        JSON.stringify({
          access_token: "access-token",
          token_type: "bearer",
          expires_at: "2026-08-10T12:15:00Z",
          user: {
            id: "00000000-0000-4000-8000-000000000001",
            email: "owner@example.com",
            is_active: true,
            created_at: "2026-08-10T12:00:00Z",
            guidance_mode: "GUIDED",
          },
        }),
        {
          status: 200,
          headers: {
            "Content-Type": "application/json",
          },
        },
      ),
    );

    const client = new ApiClient("/api/v1", fetchImplementation);

    const response = await client.login({
      email: "owner@example.com",
      password: "correct horse battery staple",
    });

    expect(response.access_token).toBe("access-token");
    expect(fetchImplementation).toHaveBeenCalledOnce();

    const [requestUrl, request] = fetchImplementation.mock.calls[0] ?? [];

    expect(requestUrl).toBe("/api/v1/auth/login");
    expect(request?.credentials).toBe("include");
    expect(request?.method).toBe("POST");
  });

  it("maps API failures to a typed error", async () => {
    const fetchImplementation = vi.fn<typeof fetch>().mockResolvedValue(
      new Response(
        JSON.stringify({
          detail: "invalid_authentication",
        }),
        {
          status: 401,
          headers: {
            "Content-Type": "application/json",
          },
        },
      ),
    );

    const client = new ApiClient("/api/v1", fetchImplementation);

    await expect(
      client.login({
        email: "owner@example.com",
        password: "incorrect horse battery staple",
      }),
    ).rejects.toMatchObject({
      name: "ApiError",
      message: "invalid_authentication",
      status: 401,
      detail: "invalid_authentication",
    });
  });

  it("saves the guidance mode once with the bearer token and returns the account", async () => {
    const account = {
      id: "00000000-0000-4000-8000-000000000001",
      email: "owner@example.com",
      is_active: true,
      created_at: "2026-08-10T12:00:00Z",
      guidance_mode: "EXPERT",
    };
    const fetchImplementation = vi
      .fn<typeof fetch>()
      .mockResolvedValueOnce(new Response(JSON.stringify(account), { status: 200 }))
      .mockResolvedValueOnce(
        new Response(JSON.stringify({ detail: "guidance_mode_already_chosen" }), { status: 409 }),
      );
    const client = new ApiClient("/api/v1", fetchImplementation);

    await expect(client.chooseGuidanceMode("access-token", "EXPERT")).resolves.toEqual(account);
    await expect(client.chooseGuidanceMode("access-token", "GUIDED")).rejects.toMatchObject({
      name: "ApiError",
      status: 409,
      detail: "guidance_mode_already_chosen",
    });

    const [requestUrl, request] = fetchImplementation.mock.calls[0] ?? [];
    const headers = new Headers(request?.headers);
    expect(requestUrl).toBe("/api/v1/auth/guidance-mode");
    expect(request?.method).toBe("POST");
    expect(request?.credentials).toBe("include");
    expect(headers.get("Authorization")).toBe("Bearer access-token");
    expect(headers.get("Content-Type")).toBe("application/json");
    expect(JSON.parse(String(request?.body))).toEqual({ guidance_mode: "EXPERT" });
    expect(JSON.parse(String(fetchImplementation.mock.calls[1]?.[1]?.body))).toEqual({
      guidance_mode: "GUIDED",
    });
  });

  it("reads the access mode of the Studio without a bearer token", async () => {
    const mode = { access_mode: "LOCAL_OWNER", registration_open: false };
    const fetchImplementation = vi
      .fn<typeof fetch>()
      .mockResolvedValueOnce(new Response(JSON.stringify(mode), { status: 200 }))
      .mockResolvedValueOnce(
        new Response(JSON.stringify({ detail: "Not Found" }), { status: 404 }),
      );
    const client = new ApiClient("/api/v1", fetchImplementation);

    await expect(client.accessMode()).resolves.toEqual(mode);
    await expect(client.accessMode()).rejects.toMatchObject({
      name: "ApiError",
      status: 404,
      detail: "Not Found",
    });

    const [requestUrl, request] = fetchImplementation.mock.calls[0] ?? [];
    const headers = new Headers(request?.headers);
    expect(requestUrl).toBe("/api/v1/auth/mode");
    expect(request?.method).toBeUndefined();
    expect(request?.body).toBeUndefined();
    expect(request?.credentials).toBe("include");
    expect(headers.get("Authorization")).toBeNull();
    expect(headers.get("Accept")).toBe("application/json");
  });

  it("reports a rate-limited sign-in with its stable code", async () => {
    const fetchImplementation = vi.fn<typeof fetch>().mockResolvedValue(
      new Response(JSON.stringify({ detail: "too_many_attempts" }), {
        status: 429,
        headers: { "Content-Type": "application/json", "Retry-After": "600" },
      }),
    );
    const client = new ApiClient("/api/v1", fetchImplementation);
    await expect(
      client.login({ email: "owner@example.com", password: "Wrong password!" }),
    ).rejects.toMatchObject({ name: "ApiError", status: 429, detail: "too_many_attempts" });
  });

  it("preserves structured provider errors instead of calling them unexpected", async () => {
    const fetchImplementation = vi
      .fn<typeof fetch>()
      .mockResolvedValue(
        new Response(
          JSON.stringify({ detail: { code: "PROVIDER_UNAVAILABLE", stage: "MODEL_PROPOSAL" } }),
          { status: 503 },
        ),
      );
    const client = new ApiClient("/api/v1", fetchImplementation);
    await expect(client.generateProjectTeamProposal("token", "project-id")).rejects.toMatchObject({
      status: 503,
      detail: "PROVIDER_UNAVAILABLE",
    });
  });

  it("distinguishes gate conflict errors from typed domain conflict results", async () => {
    const fetchImplementation = vi
      .fn<typeof fetch>()
      .mockResolvedValueOnce(
        new Response(JSON.stringify({ detail: "gate_state_conflict" }), { status: 409 }),
      )
      .mockResolvedValueOnce(
        new Response(JSON.stringify({ status: "REJECTED", issue: "STALE_ARTIFACT" }), {
          status: 409,
        }),
      );
    const client = new ApiClient("/api/v1", fetchImplementation);
    await expect(client.decideAgentTeamGate("token", "project", "APPROVE")).rejects.toMatchObject({
      detail: "gate_state_conflict",
      status: 409,
    });
    await expect(client.decideAgentTeamGate("token", "project", "APPROVE")).resolves.toMatchObject({
      status: "REJECTED",
      issue: "STALE_ARTIFACT",
    });
  });

  it("tells the registered listeners about every failed answer and changes nothing else", async () => {
    const fetchImplementation = vi
      .fn<typeof fetch>()
      .mockResolvedValueOnce(
        new Response(JSON.stringify({ detail: { code: "PROJECT_NOT_FOUND" } }), { status: 404 }),
      )
      .mockResolvedValueOnce(new Response(JSON.stringify([]), { status: 200 }))
      .mockResolvedValueOnce(
        new Response(JSON.stringify({ detail: "gate_state_conflict" }), { status: 409 }),
      );
    const client = new ApiClient("/api/v1", fetchImplementation);
    const seen: [number, string][] = [];
    const broken = vi.fn(() => {
      throw new Error("listener failure");
    });
    const stopBroken = onRequestFailure(broken);
    const stop = onRequestFailure((error) => seen.push([error.status, error.detail]));

    await expect(client.getProject("token", "project")).rejects.toMatchObject({
      name: "ApiError",
      status: 404,
      detail: "PROJECT_NOT_FOUND",
    });
    await expect(client.listBriefVersions("token", "project")).resolves.toEqual([]);
    void new ApiRequestError("The sections request failed", {
      status: 422,
      code: "SECTIONS_INVALID",
      payload: null,
    });
    void new ApiError(0, "ACCESS_TOKEN_REQUIRED");
    void new ApiError(200, "INVALID_API_RESPONSE");
    stop();
    stopBroken();
    await expect(client.decideAgentTeamGate("token", "project", "APPROVE")).rejects.toMatchObject({
      status: 409,
      detail: "gate_state_conflict",
    });

    expect(seen).toEqual([
      [404, "PROJECT_NOT_FOUND"],
      [422, "SECTIONS_INVALID"],
    ]);
    expect(broken).toHaveBeenCalledTimes(2);
  });
});
