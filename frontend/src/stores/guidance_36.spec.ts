import { createPinia, setActivePinia } from "pinia";
import { nextTick } from "vue";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { useAuthStore } from "./auth";
import { guidancePreferenceKey, readGuidancePreference, useGuidanceStore } from "./guidance";

function account(id: string) {
  return { id, email: `${id}@example.test`, is_active: true, created_at: "2026-10-03T00:00:00Z" };
}

describe("personal guidance in sprint 36", () => {
  beforeEach(() => {
    setActivePinia(createPinia());
    const values = new Map<string, string>();
    vi.stubGlobal("localStorage", {
      getItem: (key: string) => values.get(key) ?? null,
      setItem: (key: string, value: string) => values.set(key, value),
      clear: () => values.clear(),
    });
  });
  afterEach(() => vi.restoreAllMocks());

  it("defaults to guided and stores expert only for the authenticated account", async () => {
    const auth = useAuthStore();
    auth.user = account("owner-a");
    const guidance = useGuidanceStore();
    expect(guidance.mode).toBe("GUIDED");
    guidance.select("EXPERT");
    expect(window.localStorage.getItem(guidancePreferenceKey("owner-a"))).toBe("EXPERT");
    auth.user = account("owner-b");
    await nextTick();
    expect(guidance.mode).toBe("GUIDED");
    auth.user = account("owner-a");
    await nextTick();
    expect(guidance.mode).toBe("EXPERT");
  });

  it("makes no request when switching and preserves unrelated stored project data", () => {
    const fetchImpl = vi.spyOn(globalThis, "fetch");
    useAuthStore().user = account("owner");
    window.localStorage.setItem("project-draft", "unsaved form");
    const guidance = useGuidanceStore();
    guidance.select("EXPERT");
    guidance.select("GUIDED");
    expect(fetchImpl).not.toHaveBeenCalled();
    expect(window.localStorage.getItem("project-draft")).toBe("unsaved form");
  });

  it.each([null, "INVALID", "expert", "{}"])(
    "uses guided for an absent or invalid preference %s",
    (value) => {
      if (value !== null) window.localStorage.setItem(guidancePreferenceKey("owner"), value);
      expect(readGuidancePreference("owner")).toBe("GUIDED");
    },
  );

  it("uses guided when storage cannot be read and still allows the current session choice", () => {
    vi.spyOn(window.localStorage, "getItem").mockImplementation(() => {
      throw new Error("blocked");
    });
    vi.spyOn(window.localStorage, "setItem").mockImplementation(() => {
      throw new Error("blocked");
    });
    useAuthStore().user = account("owner");
    const guidance = useGuidanceStore();
    expect(guidance.mode).toBe("GUIDED");
    guidance.select("EXPERT");
    expect(guidance.mode).toBe("EXPERT");
  });

  it("ignores anonymous choices and prevents retroactive automatic generations", () => {
    const guidance = useGuidanceStore();
    guidance.select("EXPERT");
    expect(guidance.mode).toBe("GUIDED");
    useAuthStore().user = account("owner");
    guidance.suppressAutomatic("project:personas");
    guidance.select("GUIDED");
    expect(guidance.automaticAllowed("project:personas")).toBe(false);
    expect(guidance.automaticAllowed("other:personas")).toBe(true);
    guidance.select("EXPERT");
    expect(guidance.automaticAllowed("other:personas")).toBe(false);
  });
});
