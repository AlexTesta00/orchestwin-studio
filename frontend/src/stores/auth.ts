import { computed, ref } from "vue";
import { defineStore } from "pinia";

import { ApiError, type ApiClient } from "@/api/client";
import type {
  AuthenticationApi,
  AuthenticationInput,
  AuthenticationResponse,
  UserResponse,
} from "@/api/contracts";

export type AuthenticationStatus = "idle" | "loading" | "authenticated" | "anonymous";

type AuthorizedOperation<T> = (accessToken: string) => Promise<T>;

function errorCode(error: unknown): string {
  if (error instanceof ApiError) {
    return error.detail;
  }

  return "unexpected_error";
}

export const useAuthStore = defineStore("auth", () => {
  const status = ref<AuthenticationStatus>("idle");
  const user = ref<UserResponse | null>(null);
  const accessToken = ref<string | null>(null);
  const expiresAt = ref<string | null>(null);
  const errorDetail = ref<string | null>(null);

  let refreshInFlight: Promise<boolean> | null = null;

  const isAuthenticated = computed(
    () => status.value === "authenticated" && user.value !== null && accessToken.value !== null,
  );

  function applyAuthentication(response: AuthenticationResponse): void {
    user.value = response.user;
    accessToken.value = response.access_token;
    expiresAt.value = response.expires_at;
    errorDetail.value = null;
    status.value = "authenticated";
  }

  function clearAuthentication(): void {
    user.value = null;
    accessToken.value = null;
    expiresAt.value = null;
    status.value = "anonymous";
  }

  async function register(api: AuthenticationApi, input: AuthenticationInput): Promise<boolean> {
    status.value = "loading";
    errorDetail.value = null;

    try {
      applyAuthentication(await api.register(input));
      return true;
    } catch (error: unknown) {
      clearAuthentication();
      errorDetail.value = errorCode(error);
      return false;
    }
  }

  async function login(api: AuthenticationApi, input: AuthenticationInput): Promise<boolean> {
    status.value = "loading";
    errorDetail.value = null;

    try {
      applyAuthentication(await api.login(input));
      return true;
    } catch (error: unknown) {
      clearAuthentication();
      errorDetail.value = errorCode(error);
      return false;
    }
  }

  async function refresh(api: AuthenticationApi, reportError = true): Promise<boolean> {
    if (refreshInFlight !== null) {
      return refreshInFlight;
    }

    refreshInFlight = (async () => {
      status.value = "loading";

      if (reportError) {
        errorDetail.value = null;
      }

      try {
        applyAuthentication(await api.refresh());
        return true;
      } catch (error: unknown) {
        clearAuthentication();
        errorDetail.value = reportError ? errorCode(error) : null;
        return false;
      } finally {
        refreshInFlight = null;
      }
    })();

    return refreshInFlight;
  }

  async function bootstrap(api: AuthenticationApi): Promise<boolean> {
    if (isAuthenticated.value) {
      return true;
    }

    return refresh(api, false);
  }

  async function logout(api: AuthenticationApi): Promise<void> {
    try {
      await api.logout();
    } finally {
      clearAuthentication();
      errorDetail.value = null;
    }
  }

  async function withAccessToken<T>(
    api: AuthenticationApi,
    operation: AuthorizedOperation<T>,
  ): Promise<T> {
    if (accessToken.value === null) {
      const refreshed = await refresh(api);

      if (!refreshed || accessToken.value === null) {
        throw new ApiError(401, "invalid_authentication");
      }
    }

    try {
      return await operation(accessToken.value);
    } catch (error: unknown) {
      if (!(error instanceof ApiError) || error.status !== 401) {
        throw error;
      }

      clearAuthentication();

      const refreshed = await refresh(api);

      if (!refreshed || accessToken.value === null) {
        throw error;
      }

      return operation(accessToken.value);
    }
  }

  return {
    status,
    user,
    accessToken,
    expiresAt,
    errorDetail,
    isAuthenticated,
    register,
    login,
    refresh,
    bootstrap,
    logout,
    withAccessToken,
  };
});

export type AuthenticationClient = Pick<
  ApiClient,
  "register" | "login" | "refresh" | "logout" | "me"
>;
