import { createPinia, setActivePinia } from "pinia";
import { createMemoryHistory } from "vue-router";
import { describe, expect, it } from "vitest";

import type {
  AuthenticationApi,
  AuthenticationInput,
  AuthenticationResponse,
  UserResponse,
} from "@/api/contracts";
import { useAuthStore } from "@/stores/auth";

import { installAuthenticationGuard } from "./authentication";
import { createAppRouter } from "./index";

const USER: UserResponse = {
  id: "00000000-0000-4000-8000-000000000001",
  email: "owner@example.com",
  is_active: true,
  created_at: "2026-08-10T12:00:00Z",
};

class AnonymousApi implements AuthenticationApi {
  public async register(input: AuthenticationInput): Promise<AuthenticationResponse> {
    throw new Error("not used");
  }

  public async login(input: AuthenticationInput): Promise<AuthenticationResponse> {
    throw new Error("not used");
  }

  public async refresh(): Promise<AuthenticationResponse> {
    throw new Error("anonymous");
  }

  public async logout(): Promise<void> {
    return undefined;
  }

  public async me(accessToken: string): Promise<UserResponse> {
    return USER;
  }
}

describe("authentication router guard", () => {
  it("redirects anonymous project navigation to login", async () => {
    const pinia = createPinia();
    setActivePinia(pinia);

    const router = createAppRouter(createMemoryHistory());
    installAuthenticationGuard(router, pinia, new AnonymousApi());

    await router.push("/projects");
    await router.isReady();

    expect(router.currentRoute.value.name).toBe("login");
    expect(router.currentRoute.value.query.redirect).toBe("/projects");
    expect(useAuthStore(pinia).isAuthenticated).toBe(false);
  });
});
