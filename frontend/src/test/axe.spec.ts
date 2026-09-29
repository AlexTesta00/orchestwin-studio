import axe from "axe-core";
import { afterEach, describe, expect, it, vi } from "vitest";

import { expectAccessible } from "./axe";

function region(html: string): HTMLElement {
  const root = document.createElement("section");
  root.setAttribute("aria-label", "Prova");
  root.innerHTML = html;
  return root;
}

describe("accessibility helper", () => {
  afterEach(() => {
    vi.restoreAllMocks();
  });

  it("checks the frames by default and lets a caller leave them out", async () => {
    const run = vi.spyOn(axe, "run");
    await expectAccessible(region("<p>Contenuto</p>"));
    expect(run.mock.calls[0]?.[1]).toMatchObject({ iframes: true });
    await expectAccessible(region("<p>Contenuto</p>"), { iframes: false });
    expect(run.mock.calls[1]?.[1]).toMatchObject({ iframes: false });
  });

  it("passes on a component that embeds a frame when frames are left out", async () => {
    const root = region('<iframe title="Anteprima del mockup" srcdoc="<p>Mockup</p>"></iframe>');
    await expectAccessible(root, { iframes: false });
    expect(root.isConnected).toBe(false);
  });

  it("still reports the violations of the component itself", async () => {
    const root = region('<button type="button"></button>');
    await expect(expectAccessible(root, { iframes: false })).rejects.toThrow(/button-name/);
  });
});
