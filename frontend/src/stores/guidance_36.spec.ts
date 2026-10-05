import { createPinia, setActivePinia } from "pinia";
import { watch } from "vue";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { ApiError } from "@/api/client";
import type { AuthenticationApi, GuidanceMode, UserResponse } from "@/api/contracts";
import { useAuthStore } from "./auth";
import * as guidanceModule from "./guidance";
import { useGuidanceStore } from "./guidance";

function account(id: string, guidanceMode: GuidanceMode | null): UserResponse {
  return {
    id,
    email: `${id}@example.com`,
    is_active: true,
    created_at: "2026-10-03T00:00:00Z",
    guidance_mode: guidanceMode,
  };
}

function renewingApi(user: UserResponse): AuthenticationApi {
  return {
    register: vi.fn(),
    login: vi.fn(),
    logout: vi.fn(),
    me: vi.fn(),
    chooseGuidanceMode: vi.fn(),
    refresh: vi.fn(async () => ({
      access_token: "new-token",
      token_type: "bearer" as const,
      expires_at: "2026-10-05T08:15:00Z",
      user,
    })),
  };
}

async function renewAccess(user: UserResponse): Promise<void> {
  const auth = useAuthStore();
  const result = await auth.withAccessToken(renewingApi(user), async (token) => {
    if (token === "old-token") throw new ApiError(401, "invalid_authentication");
    return token;
  });
  expect(result).toBe("new-token");
}

function signIn(user: UserResponse): void {
  const auth = useAuthStore();
  auth.user = user;
  auth.accessToken = "old-token";
  auth.status = "authenticated";
}

describe("guidance mode chosen once for the account", () => {
  beforeEach(() => {
    setActivePinia(createPinia());
  });

  it("starts guided without a choice and allows nothing automatic before any access", () => {
    const guidance = useGuidanceStore();
    expect([guidance.mode, guidance.chosen, guidance.expert, guidance.accountId]).toEqual([
      "GUIDED",
      false,
      false,
      null,
    ]);
    expect(guidance.automaticAllowed("project:personas")).toBe(false);
  });

  it("reads the mode of the account and keeps the last known one when the account goes away", () => {
    const auth = useAuthStore();
    const guidance = useGuidanceStore();
    auth.user = account("owner-a", null);
    expect([guidance.mode, guidance.chosen, guidance.accountId]).toEqual([
      "GUIDED",
      false,
      "owner-a",
    ]);
    auth.user = account("owner-a", "EXPERT");
    expect([guidance.mode, guidance.chosen, guidance.expert]).toEqual(["EXPERT", true, true]);
    auth.user = null;
    expect([guidance.mode, guidance.chosen, guidance.expert, guidance.accountId]).toEqual([
      "EXPERT",
      true,
      true,
      null,
    ]);
    auth.user = account("owner-b", "GUIDED");
    expect([guidance.mode, guidance.chosen, guidance.accountId]).toEqual([
      "GUIDED",
      true,
      "owner-b",
    ]);
    auth.user = account("owner-c", null);
    expect([guidance.mode, guidance.chosen, guidance.accountId]).toEqual([
      "GUIDED",
      false,
      "owner-c",
    ]);
  });

  it("keeps the expert mode at every instant while the access is renewed", async () => {
    signIn(account("owner", "EXPERT"));
    const auth = useAuthStore();
    const guidance = useGuidanceStore();
    const samples: unknown[][] = [];
    const changes: unknown[] = [];
    const stops = [
      watch(
        () => auth.user,
        (user) =>
          samples.push([
            user === null,
            guidance.accountId,
            guidance.expert,
            guidance.chosen,
            guidance.automaticAllowed("project:personas"),
          ]),
        { flush: "sync" },
      ),
      watch(
        () => guidance.mode,
        (value) => changes.push(value),
        { flush: "sync" },
      ),
      watch(
        () => guidance.automaticAllowed("project:personas"),
        (value) => changes.push(value),
        { flush: "sync" },
      ),
    ];

    await renewAccess(account("owner", "EXPERT"));
    stops.forEach((stop) => stop());

    expect(samples).toEqual([
      [true, null, true, true, false],
      [false, "owner", true, true, false],
    ]);
    expect(changes).toEqual([]);
    expect([guidance.mode, guidance.chosen, guidance.accountId]).toEqual(["EXPERT", true, "owner"]);
  });

  it("keeps the suppressed keys of a guided account and allows nothing during the renewal", async () => {
    signIn(account("owner", "GUIDED"));
    const auth = useAuthStore();
    const guidance = useGuidanceStore();
    guidance.suppressAutomatic("project:personas");
    const samples: unknown[][] = [];
    const stop = watch(
      () => auth.user,
      (user) =>
        samples.push([
          user === null,
          guidance.mode,
          guidance.automaticAllowed("project:personas"),
          guidance.automaticAllowed("other:personas"),
        ]),
      { flush: "sync" },
    );

    await renewAccess(account("owner", "GUIDED"));
    stop();

    expect(samples).toEqual([
      [true, "GUIDED", false, false],
      [false, "GUIDED", false, true],
    ]);
    expect(guidance.automaticAllowed("project:personas")).toBe(false);
    expect(guidance.automaticAllowed("other:personas")).toBe(true);
  });

  it("takes the mode of a different account and clears the suppressed keys only then", () => {
    const auth = useAuthStore();
    auth.user = account("owner-a", "GUIDED");
    const guidance = useGuidanceStore();
    guidance.suppressAutomatic("project:personas");
    expect(guidance.automaticAllowed("project:personas")).toBe(false);
    expect(guidance.automaticAllowed("other:personas")).toBe(true);
    auth.user = account("owner-a", "GUIDED");
    auth.user = null;
    auth.user = account("owner-a", "GUIDED");
    expect(guidance.automaticAllowed("project:personas")).toBe(false);
    auth.user = account("owner-b", "GUIDED");
    expect(guidance.automaticAllowed("project:personas")).toBe(true);
    guidance.suppressAutomatic("project:personas");
    auth.user = account("owner-c", "EXPERT");
    expect([guidance.mode, guidance.expert, guidance.accountId]).toEqual([
      "EXPERT",
      true,
      "owner-c",
    ]);
    expect(guidance.automaticAllowed("other:personas")).toBe(false);
  });

  it("allows nothing automatic for an account without a choice", () => {
    const auth = useAuthStore();
    auth.user = account("owner", null);
    const guidance = useGuidanceStore();
    expect([guidance.mode, guidance.chosen, guidance.expert]).toEqual(["GUIDED", false, false]);
    expect(guidance.automaticAllowed("project:personas")).toBe(false);
    expect(guidance.automaticAllowed("other:personas")).toBe(false);
  });

  it("neither reads nor writes the browser storage and ignores the old browser preference", () => {
    const values = new Map([["orchestwin.guidance.v1.owner", "EXPERT"]]);
    const storage = {
      getItem: vi.fn((key: string) => values.get(key) ?? null),
      setItem: vi.fn((key: string, value: string) => {
        values.set(key, value);
      }),
      removeItem: vi.fn((key: string) => {
        values.delete(key);
      }),
    };
    vi.stubGlobal("localStorage", storage);
    const auth = useAuthStore();
    auth.user = account("owner", null);
    const guidance = useGuidanceStore();
    expect([guidance.mode, guidance.chosen]).toEqual(["GUIDED", false]);
    auth.user = account("owner", "GUIDED");
    guidance.suppressAutomatic("project:personas");
    expect([guidance.mode, guidance.automaticAllowed("other:personas")]).toEqual(["GUIDED", true]);
    expect(storage.getItem).not.toHaveBeenCalled();
    expect(storage.setItem).not.toHaveBeenCalled();
    expect(storage.removeItem).not.toHaveBeenCalled();
    expect(values.get("orchestwin.guidance.v1.owner")).toBe("EXPERT");
  });

  it("offers no way to change the mode", () => {
    useAuthStore().user = account("owner", "GUIDED");
    const guidance = useGuidanceStore();
    expect(Object.keys(guidanceModule)).toEqual(["useGuidanceStore"]);
    expect(guidance).not.toHaveProperty("select");
    expect(guidance.mode).toBe("GUIDED");
  });
});
