import { createPinia, setActivePinia } from "pinia";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { ApiError } from "@/api/client";
import { ArtifactGraphApiError } from "@/api/artifacts";
import { DesignApiError } from "@/api/design";
import { RequirementsApiError } from "@/api/requirements";
import { UserModelingApiError } from "@/api/userModeling";
import type {
  AuthenticationApi,
  AuthenticationInput,
  AuthenticationResponse,
  GuidanceMode,
  UserResponse,
} from "@/api/contracts";

import { useAuthStore } from "./auth";

const USER: UserResponse = {
  id: "00000000-0000-4000-8000-000000000001",
  email: "owner@example.com",
  is_active: true,
  created_at: "2026-08-10T12:00:00Z",
  guidance_mode: null,
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
  public meResult: UserResponse = USER;
  public meError: unknown | null = null;
  public meTokens: string[] = [];
  public chooseErrors: unknown[] = [];
  public chooseCalls: [string, GuidanceMode][] = [];

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
    this.meTokens.push(accessToken);

    if (this.meError !== null) {
      throw this.meError;
    }

    return this.meResult;
  }

  public async chooseGuidanceMode(accessToken: string, mode: GuidanceMode): Promise<UserResponse> {
    this.chooseCalls.push([accessToken, mode]);
    const failure = this.chooseErrors.shift();

    if (failure !== undefined) {
      throw failure;
    }

    return { ...USER, guidance_mode: mode };
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

  it.each([ArtifactGraphApiError, DesignApiError, RequirementsApiError, UserModelingApiError])(
    "refreshes expired authentication for domain client %s",
    async (ErrorType) => {
      const api = new FakeAuthenticationApi();
      const store = useAuthStore();
      await store.login(api, { email: USER.email, password: "test" });
      const failure = new ErrorType("Expired", { status: 401, code: "EXPIRED", payload: null });
      const operation = vi.fn().mockRejectedValueOnce(failure).mockResolvedValueOnce("success");
      expect(await store.withAccessToken(api, operation)).toBe("success");
      expect(operation.mock.calls).toEqual([["login-token"], ["refresh-token"]]);
      expect(api.refreshCalls).toBe(1);
      expect(failure.name).toBe(ErrorType.name);
    },
  );

  it.each([403, 409, 422, 502, 503])(
    "does not replay a failed operation with status %s",
    async (status) => {
      const api = new FakeAuthenticationApi();
      const store = useAuthStore();
      await store.login(api, { email: USER.email, password: "test" });
      const failure = new DesignApiError("Rejected", {
        status,
        code: "REJECTED",
        payload: null,
      });
      const operation = vi.fn().mockRejectedValue(failure);
      await expect(store.withAccessToken(api, operation)).rejects.toBe(failure);
      expect(operation).toHaveBeenCalledTimes(1);
      expect(api.refreshCalls).toBe(0);
    },
  );

  it.each<GuidanceMode>(["GUIDED", "EXPERT"])(
    "saves the %s mode once and keeps the returned account",
    async (mode) => {
      const api = new FakeAuthenticationApi();
      const store = useAuthStore();
      await store.login(api, { email: USER.email, password: "test" });

      expect(await store.chooseGuidanceMode(api, mode)).toBe("chosen");
      expect(api.chooseCalls).toEqual([["login-token", mode]]);
      expect(store.user).toEqual({ ...USER, guidance_mode: mode });
      expect(store.status).toBe("authenticated");
      expect(api.meTokens).toEqual([]);
    },
  );

  it("reads the account again when the mode was already chosen", async () => {
    const api = new FakeAuthenticationApi();
    const store = useAuthStore();
    await store.login(api, { email: USER.email, password: "test" });
    api.chooseErrors = [new ApiError(409, "guidance_mode_already_chosen")];
    api.meResult = { ...USER, guidance_mode: "GUIDED" };

    expect(await store.chooseGuidanceMode(api, "EXPERT")).toBe("already_chosen");
    expect(api.chooseCalls).toEqual([["login-token", "EXPERT"]]);
    expect(api.meTokens).toEqual(["login-token"]);
    expect(store.user?.guidance_mode).toBe("GUIDED");
    expect(store.status).toBe("authenticated");
    expect(store.errorDetail).toBeNull();
  });

  it.each([
    new ApiError(500, "unexpected_api_error"),
    new ApiError(422, "validation_error"),
    new ApiError(409, "conflict"),
    new TypeError("Failed to fetch"),
  ])("fails on %s without touching the session", async (failure) => {
    const api = new FakeAuthenticationApi();
    const store = useAuthStore();
    await store.login(api, { email: USER.email, password: "test" });
    const account = store.user;
    api.chooseErrors = [failure];

    expect(await store.chooseGuidanceMode(api, "EXPERT")).toBe("failed");
    expect(store.status).toBe("authenticated");
    expect(store.user).toBe(account);
    expect(store.errorDetail).toBeNull();
    expect(store.accessToken).toBe("login-token");
    expect(api.meTokens).toEqual([]);
    expect(api.refreshCalls).toBe(0);
  });

  it("fails without touching the session when the account cannot be read again", async () => {
    const api = new FakeAuthenticationApi();
    const store = useAuthStore();
    await store.login(api, { email: USER.email, password: "test" });
    const account = store.user;
    api.chooseErrors = [new ApiError(409, "guidance_mode_already_chosen")];
    api.meError = new ApiError(503, "service_unavailable");

    expect(await store.chooseGuidanceMode(api, "GUIDED")).toBe("failed");
    expect(store.user).toBe(account);
    expect(store.status).toBe("authenticated");
    expect(store.errorDetail).toBeNull();
  });

  it("renews an expired access token once before saving the choice", async () => {
    const api = new FakeAuthenticationApi();
    const store = useAuthStore();
    await store.login(api, { email: USER.email, password: "test" });
    api.chooseErrors = [new ApiError(401, "invalid_authentication")];

    expect(await store.chooseGuidanceMode(api, "EXPERT")).toBe("chosen");
    expect(api.chooseCalls).toEqual([
      ["login-token", "EXPERT"],
      ["refresh-token", "EXPERT"],
    ]);
    expect(api.refreshCalls).toBe(1);
    expect(store.user?.guidance_mode).toBe("EXPERT");
  });
});
