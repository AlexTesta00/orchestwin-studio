import { describe, expect, it } from "vitest";

import {
  BASE_DESIGN_PACKAGE,
  DESIGN_ALTERNATIVE_ID,
  SECOND_DESIGN_ALTERNATIVE_ID,
} from "../test/designFixtures";
import { buildSelectedDesignPackage } from "./designPrototype";

describe("design prototype builder", () => {
  it("creates a deterministic trusted prototype without mutating the source package", () => {
    const first = buildSelectedDesignPackage(BASE_DESIGN_PACKAGE, DESIGN_ALTERNATIVE_ID);
    const second = buildSelectedDesignPackage(BASE_DESIGN_PACKAGE, DESIGN_ALTERNATIVE_ID);

    expect(first).toEqual(second);
    expect(first).not.toBe(BASE_DESIGN_PACKAGE);
    expect(BASE_DESIGN_PACKAGE.owner_selected_alternative_id).toBeNull();
    expect(BASE_DESIGN_PACKAGE.prototype).toBeNull();
    expect(first.owner_selected_alternative_id).toBe(DESIGN_ALTERNATIVE_ID);
    expect(first.prototype?.design_alternative_id).toBe(DESIGN_ALTERNATIVE_ID);
    expect(first.prototype?.screens).toHaveLength(3);
    expect(first.prototype?.transitions).toHaveLength(2);
    expect(first.prototype?.supported_viewports).toEqual(["DESKTOP", "MOBILE", "TABLET"]);
  });

  it("rejects an alternative outside the current Design Package", () => {
    expect(() =>
      buildSelectedDesignPackage(BASE_DESIGN_PACKAGE, "00000000-0000-4000-8000-000000000999"),
    ).toThrow("does not belong");
  });

  it("produces different prototype identities for different alternatives", () => {
    const first = buildSelectedDesignPackage(BASE_DESIGN_PACKAGE, DESIGN_ALTERNATIVE_ID);
    const second = buildSelectedDesignPackage(BASE_DESIGN_PACKAGE, SECOND_DESIGN_ALTERNATIVE_ID);

    expect(first.prototype?.id).not.toBe(second.prototype?.id);
    expect(first.prototype?.entry_screen_id).not.toBe(second.prototype?.entry_screen_id);
  });
});
