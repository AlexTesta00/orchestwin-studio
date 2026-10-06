import { createPinia, setActivePinia } from "pinia";
import { createMemoryHistory } from "vue-router";
import { describe, expect, it } from "vitest";

import type {
  AccessModeResponse,
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
  public async accessMode(): Promise<AccessModeResponse> {
    return { access_mode: "ACCOUNTS", registration_open: true };
  }

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

class LocalApi extends SignedInApi {
  public refreshCalls = 0;
  private failures: number;

  public constructor(guidanceMode: GuidanceMode | null, failures = 0) {
    super(guidanceMode);

    this.failures = failures;
  }

  public override async accessMode(): Promise<AccessModeResponse> {
    return { access_mode: "LOCAL_OWNER", registration_open: false };
  }

  public override async refresh(): Promise<AuthenticationResponse> {
    this.refreshCalls += 1;

    if (this.failures > 0) {
      this.failures -= 1;
      throw new Error("studio unavailable");
    }

    return super.refresh();
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

  it.each(["/login", "/register"])(
    "keeps %s open for a guest of a Studio with accounts",
    async (path) => {
      const { router, auth } = await open(new AnonymousApi(), path);

      expect(auth.accessMode).toBe("ACCOUNTS");
      expect(auth.isLocal).toBe(false);
      expect(router.currentRoute.value.path).toBe(path);
    },
  );

  it.each(["/login", "/register"])(
    "sends %s of a local Studio to the projects with the session it opens by itself",
    async (path) => {
      const api = new LocalApi("GUIDED");
      const { router, auth } = await open(api, path);

      expect(auth.isLocal).toBe(true);
      expect(auth.isAuthenticated).toBe(true);
      expect(router.currentRoute.value.name).toBe("projects");
      expect(api.refreshCalls).toBe(1);
    },
  );

  it("keeps the choice of the mode for the account of a local Studio", async () => {
    const { router } = await open(new LocalApi(null), "/login");

    expect(router.currentRoute.value.name).toBe("guidance-choice");
    expect(router.currentRoute.value.query.redirect).toBe("/projects");
  });

  it("opens the session of a local Studio again before showing the sign in page", async () => {
    const api = new LocalApi("EXPERT", 1);
    const { router, auth } = await open(api, "/");

    expect(router.currentRoute.value.name).toBe("overview");
    expect(auth.isLocal).toBe(true);
    expect(auth.isAuthenticated).toBe(false);

    await router.push("/login");

    expect(router.currentRoute.value.name).toBe("projects");
    expect(auth.isAuthenticated).toBe(true);
    expect(api.refreshCalls).toBe(2);
  });

  it("keeps the page asked for once a local Studio answers again", async () => {
    const api = new LocalApi(null, 1);
    const { router, auth } = await open(api, "/");

    await router.push(PROJECT_PATH);

    expect(auth.isAuthenticated).toBe(true);
    expect(router.currentRoute.value.name).toBe("guidance-choice");
    expect(router.currentRoute.value.query.redirect).toBe(PROJECT_PATH);
    expect(api.refreshCalls).toBe(2);
  });

  it("leaves the public pages open while a local Studio does not open the session", async () => {
    const api = new LocalApi("GUIDED", Number.POSITIVE_INFINITY);
    const { router, auth } = await open(api, "/projects");

    expect(auth.isLocal).toBe(true);
    expect(auth.isAuthenticated).toBe(false);
    expect(auth.errorDetail).toBeNull();
    expect(router.currentRoute.value.name).toBe("login");
    expect(router.currentRoute.value.query.redirect).toBe("/projects");

    await router.push("/register");

    expect(router.currentRoute.value.name).toBe("register");

    await router.push("/");

    expect(router.currentRoute.value.name).toBe("overview");
    expect(api.refreshCalls).toBe(4);
  });
});
