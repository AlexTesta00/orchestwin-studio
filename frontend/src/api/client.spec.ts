import { describe, expect, it, vi } from "vitest";

import {
  ApiClient,
  ApiError,
  resolveApiBaseUrl,
} from "./client";

describe("ApiClient", () => {
  it("normalizes the configured API base URL", () => {
    expect(resolveApiBaseUrl("http://localhost:8000/api/v1/")).toBe(
      "http://localhost:8000/api/v1",
    );
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
    const client = new ApiClient(
      "http://localhost:8000/api/v1",
      fetchImplementation,
    );

    const response = await client.login({
      email: "owner@example.com",
      password: "correct horse battery staple",
    });

    expect(response.access_token).toBe("access-token");
    expect(fetchImplementation).toHaveBeenCalledOnce();

    const [, request] = fetchImplementation.mock.calls[0] ?? [];

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
    const client = new ApiClient(
      "http://localhost:8000/api/v1",
      fetchImplementation,
    );

    await expect(
      client.login({
        email: "owner@example.com",
        password: "incorrect horse battery staple",
      }),
    ).rejects.toEqual(
      expect.objectContaining<ApiError>({
        status: 401,
        detail: "invalid_authentication",
      }),
    );
  });
});