"use strict";

const { PROJECT_ID } = require("./fixtures");

const HASH = "a".repeat(64);
const SOURCE_HASH = "b".repeat(64);
const HYPOTHESIS_ID = "41000000-0000-4000-8000-000000000001";

function node(code, kind = "SCENARIO", extra = {}) {
  return {
    key: `${kind}:artifact:3:${HASH}:${code}`,
    code,
    kind,
    title: `${code} original <literal>`,
    reference: { artifact_id: "artifact", version_number: 3, content_hash: HASH },
    current: true,
    declared_context: {},
    ...extra,
  };
}

function outcome(extra = {}) {
  return {
    id: "42000000-0000-4000-8000-000000000001",
    code: "HVO-001",
    hypothesis_id: HYPOTHESIS_ID,
    hypothesis_version_number: 2,
    hypothesis_content_hash: HASH,
    session_ref: "TEST-software-fixture",
    session_kind: "SYNTHETIC_EXERCISE",
    outcome: "REFUTED",
    coverage: "PARTIAL",
    limitations: "Synthetic software fixture; no actual people or session.",
    evidence_id: "43000000-0000-4000-8000-000000000001",
    evidence_version: 2,
    evidence_content_hash: SOURCE_HASH,
    citation: { source_id: "43000000-0000-4000-8000-000000000001", source_version: 2, content_hash: SOURCE_HASH, quote: "Exact <script>bad()</script>\nquoted & text", start: 7, end: 50, start_line: 2, end_line: 3 },
    recorded_at: "2026-10-03T08:00:00+00:00",
    content_hash: HASH,
    effective_status: "RETIRED",
    source_text_available: false,
    gaps: [{ code: "SOURCE_TEXT_UNAVAILABLE" }],
    ...extra,
  };
}

function hypothesis(extra = {}) {
  const origin = node("UT-claim", "USER_TWIN_CLAIM");
  const twin = node("UT-001", "USER_TWIN");
  const scenario = node("SCN-001");
  const design = node("ALT-001", "DESIGN_ALTERNATIVE");
  return {
    id: HYPOTHESIS_ID,
    code: "HYP-001",
    version_number: 2,
    based_on_version_number: 1,
    origin_key: origin.key,
    origin_kind: origin.kind,
    origin_reference: origin.reference,
    twin_key: twin.key,
    twin_reference: twin.reference,
    scenario_key: scenario.key,
    scenario_reference: scenario.reference,
    design_key: design.key,
    design_reference: design.reference,
    question: "Owner question <literal>",
    task: "Owner completed task",
    observe: ["Observe the entered value", "Observe the requested correction"],
    limitations: "Synthetic fixture for editor rendering; no human validation claimed.",
    alternative_id: "alternative-id",
    anchor_keys: [],
    mockup_references: [],
    created_at: "2026-10-03T07:00:00+00:00",
    content_hash: HASH,
    current: true,
    state: "TO_VERIFY",
    partial_evidence: false,
    conflicting_outcomes: false,
    active_outcome_ids: [],
    outcomes: [outcome()],
    gaps: [{ code: "CONTEXT_OUTDATED", reference: "design_key" }],
    ...extra,
  };
}

function overview(extra = {}) {
  const candidate = node("UT-claim", "USER_TWIN_CLAIM");
  return {
    kind: "orchestwin.human-validation",
    schema_version: 1,
    project_id: PROJECT_ID,
    candidate_count: 1,
    candidates: [{ ...candidate, origin: candidate, twin_references: [node("UT-001", "USER_TWIN")], scenario_candidates: [node("SCN-001")], design_references: [], gaps: [{ code: "MISSING_DESIGN" }], limits: ["CANDIDATE_NOT_AN_OPERATIONAL_HYPOTHESIS"] }],
    hypotheses: [hypothesis()],
    outcomes: [outcome()],
    summary: { hypotheses: 1, to_verify: 1, confirmed: 0, refuted: 0, uncertain: 0, contested: 0, retired_outcomes: 1 },
    empirical_summary: { human_session_outcomes: 0, synthetic_exercise_outcomes: 0 },
    omitted_sections: ["design"],
    limits: ["OUTCOMES_DO_NOT_PROMOTE_TWIN_CLAIMS", "SYNTHETIC_EXERCISES_NOT_EMPIRICAL_VALIDATION"],
    ...extra,
  };
}

function walkthrough(extra = {}) {
  return {
    kind: "orchestwin.scenario-walkthrough",
    schema_version: 1,
    project_id: PROJECT_ID,
    scenario: node("SCN-001"),
    twin_references: [node("UT-001", "USER_TWIN")],
    task: "Enter the original amount <literal>",
    steps: [{ number: 1, text: "Original step & text", anchors: [], observe: [], gaps: [{ code: "STEP_ANCHOR_NOT_ATTESTED" }] }],
    reference: node("SCN-001").reference,
    design_references: [node("ALT-001", "DESIGN_ALTERNATIVE")],
    anchor_candidates: [node("ELM-001", "PROTOTYPE_ELEMENT", { declared_context: { mockup: { screen_code: "SCR-001", alternative_id: "alternative-id", prototype_id: "prototype-id", document_hashes: { "index.html": HASH } } } })],
    expected_outcome: "Original expected outcome",
    gaps: [],
    limits: ["SCENARIO_LEVEL_ANCHORS_ONLY", "SOFTWARE_NAVIGATION_NOT_HUMAN_OBSERVATION"],
    ...extra,
  };
}

module.exports = { HASH, SOURCE_HASH, hypothesis, node, outcome, overview, walkthrough };
