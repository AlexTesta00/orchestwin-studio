import { createPinia, setActivePinia } from "pinia";
import { beforeEach, describe, expect, it } from "vitest";

import { useShellStore } from "./shell";

describe("useShellStore", () => {
  beforeEach(() => {
    setActivePinia(createPinia());
  });

  it("starts with the primary navigation closed", () => {
    const store = useShellStore();

    expect(store.isNavigationOpen).toBe(false);
  });

  it("toggles and closes the primary navigation explicitly", () => {
    const store = useShellStore();

    store.toggleNavigation();
    expect(store.isNavigationOpen).toBe(true);

    store.toggleNavigation();
    expect(store.isNavigationOpen).toBe(false);

    store.closeNavigation();
    expect(store.isNavigationOpen).toBe(false);
  });
});
