import { createPinia, setActivePinia } from "pinia";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { ApiError } from "@/api/client";
import type {
  AuthenticationApi,
  AuthenticationInput,
  AuthenticationResponse,
  UserResponse,
} from "@/api/contracts";

import { useAuthStore } from "./auth";

const USER: UserResponse = {
  id: "00000000-0000-4000-8000-000000000001",
  email: "owner@example.com",
  is_active: true,
  created_at: "2026-08-10T12:00:00Z",
};

function authenticationResponse(token: string): AuthenticationResponse {
  return {
    access_token: token,
    token_type: "bearer",
    expires_at: "2026-08-10T12:15:00Z",
    user: USER,
  };
}

class FakeAuthenticationApi implements AuthenticationApi {
  public refreshCalls = 0;
  public loginResult = authenticationResponse("login-token");
  public refreshResult = authenticationResponse("refresh-token");
  public refreshError: unknown | null = null;

  public async register(input: AuthenticationInput): Promise<AuthenticationResponse> {
    void input;

    return this.loginResult;
  }

  public async login(input: AuthenticationInput): Promise<AuthenticationResponse> {
    void input;

    return this.loginResult;
  }

  public async refresh(): Promise<AuthenticationResponse> {
    this.refreshCalls += 1;

    if (this.refreshError !== null) {
      throw this.refreshError;
    }

    return this.refreshResult;
  }

  public async logout(): Promise<void> {
    return undefined;
  }

  public async me(accessToken: string): Promise<UserResponse> {
    void accessToken;

    return USER;
  }
}

describe("useAuthStore", () => {
  beforeEach(() => {
    setActivePinia(createPinia());
  });

  it("keeps the access token only in store memory", async () => {
    const storageSetItem = vi.spyOn(window.Storage.prototype, "setItem");
    const api = new FakeAuthenticationApi();
    const store = useAuthStore();

    const succeeded = await store.login(api, {
      email: "owner@example.com",
      password: "correct horse battery staple",
    });

    expect(succeeded).toBe(true);
    expect(store.isAuthenticated).toBe(true);
    expect(store.accessToken).toBe("login-token");
    expect(storageSetItem).not.toHaveBeenCalled();
  });

  it("deduplicates concurrent refresh attempts", async () => {
    const api = new FakeAuthenticationApi();
    const store = useAuthStore();

    const results = await Promise.all([store.refresh(api), store.refresh(api), store.refresh(api)]);

    expect(results).toEqual([true, true, true]);
    expect(api.refreshCalls).toBe(1);
    expect(store.accessToken).toBe("refresh-token");
  });

  it("treats a missing bootstrap session as anonymous without a form error", async () => {
    const api = new FakeAuthenticationApi();
    const store = useAuthStore();

    api.refreshError = new ApiError(401, "invalid_refresh_token");

    const succeeded = await store.bootstrap(api);

    expect(succeeded).toBe(false);
    expect(store.status).toBe("anonymous");
    expect(store.isAuthenticated).toBe(false);
    expect(store.errorDetail).toBeNull();
    expect(api.refreshCalls).toBe(1);
  });

  it("reports an explicit refresh failure outside bootstrap", async () => {
    const api = new FakeAuthenticationApi();
    const store = useAuthStore();

    api.refreshError = new ApiError(401, "expired_refresh_token");

    const succeeded = await store.refresh(api);

    expect(succeeded).toBe(false);
    expect(store.status).toBe("anonymous");
    expect(store.errorDetail).toBe("expired_refresh_token");
  });

  it("refreshes once and retries an authorized operation", async () => {
    const api = new FakeAuthenticationApi();
    const store = useAuthStore();

    store.$patch({
      status: "authenticated",
      user: USER,
      accessToken: "expired-token",
      expiresAt: "2026-08-10T12:00:00Z",
    });

    const observedTokens: string[] = [];

    const result = await store.withAccessToken(api, async (token) => {
      observedTokens.push(token);

      if (token === "expired-token") {
        throw new ApiError(401, "invalid_authentication");
      }

      return "success";
    });

    expect(result).toBe("success");
    expect(observedTokens).toEqual(["expired-token", "refresh-token"]);
    expect(api.refreshCalls).toBe(1);
  });
});
