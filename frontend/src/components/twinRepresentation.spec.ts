import { describe, expect, it } from "vitest";
import type { ProfileObservationPayload, UserTwinVersionPayload } from "../types/userModeling";
import { observationDisplayStatus, readableClaim, twinRepresentation } from "./twinRepresentation";

const observation: ProfileObservationPayload = {
  observation_key: "user_twin.goals",
  value: { kind: "ITEMS", text: null, items: ["Fast check-in"], reason: null },
  epistemic_status: "HUMAN_VALIDATED",
  confidence: 1,
  provenance: [
    {
      source_kind: "OWNER_INPUT",
      source_id: "owner",
      source_version: null,
      content_hash: null,
      locator: null,
      summary: null,
    },
  ],
  human_validation: "NOT_REQUIRED",
  rationale: null,
};
describe("conservative twin representation", () => {
  it.each(["USER_PROVIDED", "EMPIRICALLY_SUPPORTED", "HUMAN_VALIDATED"] as const)(
    "does not treat %s and owner input as empirical evidence",
    (epistemic_status) => {
      expect(observationDisplayStatus({ ...observation, epistemic_status })).toBe("HYPOTHESIZED");
    },
  );
  it.each(["UNKNOWN", "ABSTAINED"] as const)(
    "shows %s as unknown even when technically supported",
    (kind) => {
      expect(
        observationDisplayStatus({
          ...observation,
          value: { kind, text: null, items: [], reason: "Missing research" },
        }),
      ).toBe("UNKNOWN");
    },
  );
  it("distinguishes inference, explicit contestation and real empirical provenance", () => {
    expect(observationDisplayStatus({ ...observation, epistemic_status: "MODEL_INFERRED" })).toBe(
      "INFERRED",
    );
    expect(observationDisplayStatus({ ...observation, epistemic_status: "CONTESTED" })).toBe(
      "CONTESTED",
    );
    expect(
      observationDisplayStatus({
        ...observation,
        provenance: [{ ...observation.provenance[0]!, source_kind: "EMPIRICAL_RESEARCH" }],
      }),
    ).toBe("EVIDENCED");
  });
  it("does not invent absent declarations or an empirical basis for a legacy twin", () => {
    const reference = { artifact_id: "artifact", version_number: 1, content_hash: "hash" };
    const twin: UserTwinVersionPayload = {
      id: "version",
      project_id: "project",
      twin_id: "twin",
      version_number: 1,
      based_on_version_number: null,
      content_hash: "hash",
      created_by_user_id: "owner",
      created_at: "2026-10-01",
      profile: {
        name: "Receptionist",
        persona_reference: {
          persona_id: "persona",
          version_number: 1,
          content_hash: "persona-hash",
          source: "OWNER_PROVIDED",
          kind: "PERSONA",
          confirmation_status: "CONFIRMED",
        },
        project_brief_reference: reference,
        agent_team_reference: reference,
        catalog_version: 1,
        catalog_content_hash: "hash",
        validation_status: "OWNER_APPROVED_UT",
        observations: [observation],
      },
    };
    const view = twinRepresentation(twin);
    expect(view.basis).toBe("PROVISIONAL");
    expect(view.does_not_represent).toEqual(readableClaim(undefined, "does_not_represent"));
    expect(view.persona.description.display_status).toBe("UNKNOWN");
    expect(view.persona.goals.display_status).toBe("HYPOTHESIZED");
    expect(twin.profile.observations).toHaveLength(1);
  });
});
