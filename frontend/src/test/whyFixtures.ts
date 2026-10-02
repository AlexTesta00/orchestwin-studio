import type { WhyAnswer, WhyDocument, WhyNode } from "../types/why";

export function whyNode(values: Partial<WhyNode> = {}): WhyNode {
  return {
    key: "REQUIREMENT:req:3:hash",
    code: "REQ-001",
    kind: "REQUIREMENT",
    title: "Accessible keyboard input",
    display_status: "UNKNOWN",
    reference: { artifact_id: "req", version_number: 3, content_hash: "hash" },
    current: true,
    rationale: null,
    citations: [],
    validation_required: true,
    gaps: [],
    declared_context: { perspectives: [] },
    ...values,
  };
}

export function whyAnswer(target = whyNode(), values: Partial<WhyAnswer> = {}): WhyAnswer {
  return {
    kind: "orchestwin.why-answer",
    schema_version: 1,
    project_id: "project",
    target,
    summary: {
      upstream_count: 0,
      downstream_count: 0,
      complete_to_twin: false,
      complete_to_evidence: false,
      all_paths_complete: false,
      stop_reasons: ["MISSING_NEED"],
    },
    upstream: [],
    downstream: [],
    links: [],
    gaps: [],
    human_validation: [target],
    declared_context: target.declared_context,
    limits: ["MISSING_NEED"],
    ...values,
  };
}

export function whyDocument(nodes: WhyNode[]): WhyDocument {
  return {
    kind: "orchestwin.why",
    schema_version: 1,
    project_id: "project",
    nodes,
    links: [],
    omitted_sections: [],
  };
}
