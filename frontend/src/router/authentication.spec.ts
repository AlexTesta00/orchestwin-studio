import { createPinia, setActivePinia } from "pinia";
import { createMemoryHistory } from "vue-router";
import { describe, expect, it } from "vitest";

import type {
  AuthenticationApi,
  AuthenticationInput,
  AuthenticationResponse,
  GuidanceMode,
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
  guidance_mode: null,
};

const PROJECT_PATH = "/projects/00000000-0000-4000-8000-000000000002";

class AnonymousApi implements AuthenticationApi {
  public async register(input: AuthenticationInput): Promise<AuthenticationResponse> {
    void input;

    throw new Error("not used");
  }

  public async login(input: AuthenticationInput): Promise<AuthenticationResponse> {
    void input;

    throw new Error("not used");
  }

  public async refresh(): Promise<AuthenticationResponse> {
    throw new Error("anonymous");
  }

  public async logout(): Promise<void> {
    return undefined;
  }

  public async me(accessToken: string): Promise<UserResponse> {
    void accessToken;

    return USER;
  }

  public async chooseGuidanceMode(accessToken: string, mode: GuidanceMode): Promise<UserResponse> {
    void accessToken;

    return { ...USER, guidance_mode: mode };
  }
}

class SignedInApi extends AnonymousApi {
  private readonly account: UserResponse;

  public constructor(guidanceMode: GuidanceMode | null) {
    super();

    this.account = { ...USER, guidance_mode: guidanceMode };
  }

  public override async refresh(): Promise<AuthenticationResponse> {
    return {
      access_token: "access-token",
      token_type: "bearer",
      expires_at: "2026-08-10T12:15:00Z",
      user: this.account,
    };
  }
}

async function open(api: AuthenticationApi, path: string) {
  const pinia = createPinia();
  setActivePinia(pinia);

  const router = createAppRouter(createMemoryHistory());

  installAuthenticationGuard(router, pinia, api);

  await router.push(path);
  await router.isReady();

  return { router, auth: useAuthStore(pinia) };
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

  it.each(["/projects", PROJECT_PATH])(
    "sends an account without a mode from %s to the choice and remembers the page",
    async (path) => {
      const { router, auth } = await open(new SignedInApi(null), path);

      expect(auth.isAuthenticated).toBe(true);
      expect(router.currentRoute.value.name).toBe("guidance-choice");
      expect(router.currentRoute.value.path).toBe("/guidance");
      expect(router.currentRoute.value.query.redirect).toBe(path);
    },
  );

  it("lets an account without a mode open the choice and the home page", async () => {
    const { router } = await open(new SignedInApi(null), "/guidance");

    expect(router.currentRoute.value.name).toBe("guidance-choice");
    expect(router.currentRoute.value.query.redirect).toBeUndefined();

    await router.push("/");

    expect(router.currentRoute.value.name).toBe("overview");
  });

  it("sends an account without a mode from the sign in page to the choice", async () => {
    const { router } = await open(new SignedInApi(null), "/login");

    expect(router.currentRoute.value.name).toBe("guidance-choice");
    expect(router.currentRoute.value.query.redirect).toBe("/projects");
  });

  it.each<GuidanceMode>(["GUIDED", "EXPERT"])(
    "sends an account with the %s mode from the choice to the projects",
    async (mode) => {
      const { router } = await open(new SignedInApi(mode), "/guidance");

      expect(router.currentRoute.value.name).toBe("projects");
      expect(router.currentRoute.value.query.redirect).toBeUndefined();
    },
  );

  it("sends a guest from the choice to the sign in and keeps the home page open", async () => {
    const { router, auth } = await open(new AnonymousApi(), "/guidance");

    expect(auth.isAuthenticated).toBe(false);
    expect(router.currentRoute.value.name).toBe("login");
    expect(router.currentRoute.value.query.redirect).toBe("/guidance");

    await router.push("/");

    expect(router.currentRoute.value.name).toBe("overview");
  });
});
