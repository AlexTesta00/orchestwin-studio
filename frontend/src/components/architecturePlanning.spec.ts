import { describe, expect, it } from "vitest";

import { ARCHITECTURE_PACKAGE } from "../test/architectureFixtures";
import {
  buildArchitecturePackageRevision,
  normalizeArchitectureOpenQuestions,
} from "./architecturePlanning";

describe("Architecture planning helpers", () => {
  it("normalizes and deduplicates owner questions", () => {
    expect(
      normalizeArchitectureOpenQuestions(
        " Confirm the execution profile. \n\nConfirm   the execution profile.\nReview API risks.",
      ),
    ).toEqual(["Confirm the execution profile.", "Review API risks."]);
  });

  it("preserves governed architecture identities while replacing open questions", () => {
    const revised = buildArchitecturePackageRevision(
      ARCHITECTURE_PACKAGE,
      "Confirm the deployment boundary.",
    );

    expect(revised).not.toBe(ARCHITECTURE_PACKAGE);
    expect(revised.grounding).toBe(ARCHITECTURE_PACKAGE.grounding);
    expect(revised.architecture).toBe(ARCHITECTURE_PACKAGE.architecture);
    expect(revised.test_plan).toBe(ARCHITECTURE_PACKAGE.test_plan);
    expect(revised.open_questions).toEqual(["Confirm the deployment boundary."]);
  });
});
