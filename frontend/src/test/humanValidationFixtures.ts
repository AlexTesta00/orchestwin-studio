import type {
  HumanValidationOutcome,
  HumanValidationOverview,
  OperationalHypothesis,
  ScenarioWalkthrough,
  ValidationCandidate,
} from "../types/humanValidation";
import type { ResearchEvidencePayload } from "../types/researchEvidence";
import { whyDocument, whyNode } from "./whyFixtures";

export const VALIDATION_QUOTE = "  Prova sintetica: 2 + 2 = 4.\nNessuna persona coinvolta.";
export const VALIDATION_SOURCE_ID = "33333333-3333-4333-8333-333333333333";
export const VALIDATION_HASH = "a".repeat(64);
export const VALIDATION_TWIN = whyNode({
  key: "twin",
  code: "UT-001",
  kind: "USER_TWIN",
  title: "Calculator twin",
  validation_required: false,
  reference: { artifact_id: "twin-id", version_number: 1, content_hash: VALIDATION_HASH },
});
export const VALIDATION_ORIGIN = whyNode({
  key: "origin",
  code: "UT-001:user_twin.goals",
  kind: "USER_TWIN_CLAIM",
  title: "Goals",
  reference: { artifact_id: "twin-id", version_number: 1, content_hash: VALIDATION_HASH },
});
export const VALIDATION_SCENARIO = whyNode({
  key: "scenario",
  code: "SCN-001",
  kind: "SCENARIO",
  title: "Calculator scenario",
  validation_required: false,
  reference: { artifact_id: "scenario-id", version_number: 2, content_hash: VALIDATION_HASH },
  declared_context: {
    perspectives: [],
    scenario: {
      goal: "Calcolare 2 + 2",
      steps: ["Inserire 2 + 2", "Leggere il risultato"],
      expected_outcome: "Il risultato è 4",
    },
  },
});
export const VALIDATION_DESIGN = whyNode({
  key: "design",
  code: "DES-001",
  kind: "DESIGN_ALTERNATIVE",
  title: "Calculator design",
  validation_required: false,
  reference: { artifact_id: "alternative-id", version_number: 3, content_hash: VALIDATION_HASH },
});
export const VALIDATION_ANCHOR = whyNode({
  key: "element",
  code: "ELM-001",
  kind: "PROTOTYPE_ELEMENT",
  title: "Equals button",
  validation_required: false,
  reference: { artifact_id: "element-id", version_number: 3, content_hash: VALIDATION_HASH },
  declared_context: {
    perspectives: [],
    mockup: {
      alternative_id: "alternative-id",
      prototype_id: "prototype-id",
      screen_code: "SCR-001",
      source: "LATEST",
      document_hashes: { "SCR-001": "rendered-hash" },
    },
  },
});

export function validationDocument() {
  return {
    ...whyDocument([
      VALIDATION_TWIN,
      VALIDATION_ORIGIN,
      VALIDATION_SCENARIO,
      VALIDATION_DESIGN,
      VALIDATION_ANCHOR,
    ]),
    links: [
      { source: "origin", target: "twin", kind: "CLAIM_OF" },
      { source: "scenario", target: "twin", kind: "ACTOR" },
    ],
  };
}

export function validationCandidate(
  overrides: Partial<ValidationCandidate> = {},
): ValidationCandidate {
  return {
    key: VALIDATION_ORIGIN.key,
    code: VALIDATION_ORIGIN.code,
    kind: VALIDATION_ORIGIN.kind,
    title: VALIDATION_ORIGIN.title,
    reference: VALIDATION_ORIGIN.reference,
    origin: VALIDATION_ORIGIN,
    twin_references: [VALIDATION_TWIN],
    scenario_candidates: [],
    design_references: [],
    gaps: [{ code: "MISSING_SCENARIO" }],
    limits: ["CANDIDATE_NOT_AN_OPERATIONAL_HYPOTHESIS"],
    ...overrides,
  };
}

export function operationalHypothesis(
  overrides: Partial<OperationalHypothesis> = {},
): OperationalHypothesis {
  return {
    id: "11111111-1111-4111-8111-111111111111",
    code: "HYP-001",
    version_number: 1,
    based_on_version_number: null,
    project_id: "project",
    owner_user_id: "owner",
    origin_key: "origin",
    origin_reference: VALIDATION_ORIGIN.reference,
    origin_kind: "USER_TWIN_CLAIM",
    twin_key: "twin",
    twin_reference: VALIDATION_TWIN.reference,
    scenario_key: "scenario",
    scenario_reference: VALIDATION_SCENARIO.reference,
    design_key: "design",
    design_reference: VALIDATION_DESIGN.reference,
    alternative_id: "alternative-id",
    anchor_keys: [],
    mockup_references: [],
    question: "Dove si legge il risultato?",
    task: null,
    observe: ["Individuazione del risultato"],
    limitations: "Fixture sintetica; nessuna sessione avvenuta",
    created_at: "2026-10-03T08:00:00Z",
    content_hash: "b".repeat(64),
    state: "TO_VERIFY",
    current: true,
    active_outcome_ids: [],
    outcomes: [],
    partial_evidence: false,
    conflicting_outcomes: false,
    gaps: [],
    ...overrides,
  };
}

export function validationOutcome(
  overrides: Partial<HumanValidationOutcome> = {},
): HumanValidationOutcome {
  return {
    id: "22222222-2222-4222-8222-222222222222",
    code: "HVO-001",
    project_id: "project",
    owner_user_id: "owner",
    hypothesis_id: operationalHypothesis().id,
    hypothesis_version_number: 1,
    hypothesis_content_hash: operationalHypothesis().content_hash,
    session_ref: "SYN-001",
    session_kind: "SYNTHETIC_EXERCISE",
    outcome: "UNCERTAIN",
    coverage: "PARTIAL",
    limitations: "Fixture sintetica; non empirica; nessuna persona coinvolta",
    evidence_id: VALIDATION_SOURCE_ID,
    evidence_version: 1,
    evidence_content_hash: VALIDATION_HASH,
    citation: {
      source_id: VALIDATION_SOURCE_ID,
      source_version: 1,
      content_hash: VALIDATION_HASH,
      quote: VALIDATION_QUOTE,
      start: 0,
      end: Array.from(VALIDATION_QUOTE).length,
      start_line: 1,
      end_line: 2,
    },
    recorded_at: "2026-10-03T08:30:00Z",
    content_hash: "c".repeat(64),
    effective_status: "ACTIVE",
    source_text_available: true,
    gaps: [],
    ...overrides,
  };
}

export function validationOverview(
  overrides: Partial<HumanValidationOverview> = {},
): HumanValidationOverview {
  return {
    kind: "orchestwin.human-validation",
    schema_version: 1,
    project_id: "project",
    candidates: [validationCandidate()],
    candidate_count: 1,
    hypotheses: [],
    outcomes: [],
    summary: {
      hypotheses: 0,
      to_verify: 0,
      confirmed: 0,
      refuted: 0,
      uncertain: 0,
      contested: 0,
      retired_outcomes: 0,
    },
    empirical_summary: { human_session_outcomes: 0, synthetic_exercise_outcomes: 0 },
    omitted_sections: [],
    limits: ["OUTCOMES_DO_NOT_PROMOTE_TWIN_CLAIMS"],
    ...overrides,
  };
}

export function validationSource(
  overrides: Partial<ResearchEvidencePayload> = {},
): ResearchEvidencePayload {
  return {
    id: VALIDATION_SOURCE_ID,
    code: "EVD-001",
    version: 1,
    title: "Appunto sintetico della calcolatrice",
    source_kind: "OWNER_INPUT",
    source_ref: "Fixture sintetica anonimizzata",
    context: "Prova software sulla calcolatrice",
    method: "Fixture del contratto; nessuna sessione",
    collected_at: null,
    limitations: "Non empirica; nessuna persona coinvolta",
    empirical: false,
    content_hash: VALIDATION_HASH,
    character_count: VALIDATION_QUOTE.length,
    byte_count: new TextEncoder().encode(VALIDATION_QUOTE).length,
    created_at: "2026-10-03T08:00:00Z",
    status: "ACTIVE",
    retired_at: null,
    retired_reason: null,
    text_available: true,
    ...overrides,
  };
}

export function validationWalkthrough(
  overrides: Partial<ScenarioWalkthrough> = {},
): ScenarioWalkthrough {
  return {
    kind: "orchestwin.scenario-walkthrough",
    schema_version: 1,
    project_id: "project",
    scenario: VALIDATION_SCENARIO,
    twin_references: [VALIDATION_TWIN],
    task: "Calcolare 2 + 2",
    steps: [
      {
        number: 1,
        text: "Inserire 2 + 2",
        anchors: [],
        observe: [],
        gaps: [{ code: "STEP_ANCHOR_NOT_ATTESTED" }],
      },
      {
        number: 2,
        text: "Leggere il risultato",
        anchors: [],
        observe: [],
        gaps: [{ code: "STEP_ANCHOR_NOT_ATTESTED" }],
      },
    ],
    reference: VALIDATION_SCENARIO.reference,
    design_references: [VALIDATION_DESIGN],
    anchor_candidates: [VALIDATION_ANCHOR],
    expected_outcome: "Il risultato è 4",
    gaps: [],
    limits: ["SOFTWARE_NAVIGATION_NOT_HUMAN_OBSERVATION"],
    ...overrides,
  };
}
