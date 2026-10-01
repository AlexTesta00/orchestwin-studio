import type {
  ArchetypePayload,
  PersonaVersionPayload,
  ProfileObservationPayload,
  ReadableClaim,
  ReadableClaimStatus,
  TwinRepresentationPayload,
  UserTwinVersionPayload,
} from "../types/userModeling";

export function observationDisplayStatus(
  observation: ProfileObservationPayload,
): ReadableClaimStatus {
  if (observation.value.kind === "UNKNOWN" || observation.value.kind === "ABSTAINED")
    return "UNKNOWN";
  if (observation.epistemic_status === "CONTESTED") return "CONTESTED";
  if (observation.epistemic_status === "MODEL_INFERRED") return "INFERRED";
  if (
    ["EMPIRICALLY_SUPPORTED", "HUMAN_VALIDATED"].includes(observation.epistemic_status) &&
    observation.provenance.some(
      (reference) =>
        reference.source_kind === "EMPIRICAL_RESEARCH" && reference.source_id.trim().length > 0,
    )
  )
    return "EVIDENCED";
  return "HYPOTHESIZED";
}

export function readableClaim(
  observation: ProfileObservationPayload | undefined,
  field: string,
): ReadableClaim {
  return observation === undefined
    ? {
        observation_key: `user_twin.${field}`,
        value: { kind: "UNKNOWN", text: null, items: [], reason: null },
        display_status: "UNKNOWN",
        rationale: null,
        provenance: [],
      }
    : {
        observation_key: observation.observation_key,
        value: observation.value,
        display_status: observationDisplayStatus(observation),
        rationale: observation.rationale,
        provenance: observation.provenance,
      };
}

export function twinRepresentation(
  twin: UserTwinVersionPayload,
  persona?: PersonaVersionPayload,
): TwinRepresentationPayload {
  if (twin.view !== undefined) return twin.view;
  const find = (field: string) =>
    twin.profile.observations.find(
      (observation) => observation.observation_key === `user_twin.${field}`,
    );
  const reference = twin.profile.persona_reference;
  const citedPersona =
    persona?.project_id === twin.project_id &&
    persona.persona_id === reference.persona_id &&
    persona.version_number === reference.version_number &&
    persona.content_hash === reference.content_hash
      ? persona
      : undefined;
  const description = readableClaim(
    find("description") ??
      citedPersona?.profile.observations.find(
        (observation) => observation.observation_key === "persona.summary",
      ),
    "description",
  );
  return {
    basis: "PROVISIONAL",
    represents: readableClaim(find("represents"), "represents"),
    does_not_represent: readableClaim(find("does_not_represent"), "does_not_represent"),
    contexts: readableClaim(find("context_of_use"), "context_of_use"),
    evidence_gaps: readableClaim(find("evidence_gaps"), "evidence_gaps"),
    empirically_supported_fields: [],
    unsupported_fields: twin.profile.observations.map((observation) =>
      observation.observation_key.replace(/^user_twin\./u, ""),
    ),
    persona: {
      description,
      goals: readableClaim(find("goals"), "goals"),
      needs: readableClaim(find("information_needs"), "information_needs"),
      behaviours: readableClaim(find("recurring_tasks"), "recurring_tasks"),
      pain_points: readableClaim(find("pain_points"), "pain_points"),
      constraints: readableClaim(find("operational_constraints"), "operational_constraints"),
      contexts: readableClaim(find("context_of_use"), "context_of_use"),
    },
  };
}

export function archetypeOf(version: PersonaVersionPayload): ArchetypePayload {
  const value = (field: string) =>
    version.profile.observations.find(
      (observation) => observation.observation_key === `persona.${field}`,
    )?.value;
  const text = (field: string) => {
    const observation = value(field);
    return observation?.kind === "TEXT" ? (observation.text ?? "") : "";
  };
  const goals = value("goals");
  return {
    persona_id: version.persona_id,
    version_id: version.id,
    version_number: version.version_number,
    name: version.profile.name,
    description: text("summary"),
    role: text("role"),
    goals: goals?.kind === "ITEMS" ? goals.items : [],
    context: text("context_of_use") || null,
    source: version.profile.source,
    confirmation_status: version.profile.confirmation_status,
    archived: version.profile.archived === true,
  };
}

export function claimText(claim: ReadableClaim, locale: "en" | "it"): string {
  if (claim.value.kind === "TEXT") return claim.value.text ?? "";
  if (claim.value.kind === "ITEMS") return claim.value.items.join(" · ");
  return locale === "it" ? "Sconosciuto" : "Unknown";
}
