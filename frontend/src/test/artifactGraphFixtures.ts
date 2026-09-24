import type {
  ArtifactGraphLinkPayload,
  ArtifactGraphNodePayload,
  CrossStageArtifactGraphPayload,
} from "../types/artifacts";

export const ARTIFACT_GRAPH_PROJECT_ID = "00000000-0000-4000-8000-000000000001";
const REQUIREMENTS_ID = "00000000-0000-4000-8000-000000000010";
const DESIGN_ID = "00000000-0000-4000-8000-000000000020";
const REQUIREMENT_ID = "00000000-0000-4000-8000-000000000040";
const ALTERNATIVE_ID = "00000000-0000-4000-8000-000000000050";

const nodes: ArtifactGraphNodePayload[] = [
  {
    reference: {
      kind: "REQUIREMENTS_SPECIFICATION",
      artifact_id: REQUIREMENTS_ID,
      version_number: 1,
      content_hash: "a".repeat(64),
    },
    stage: "REQUIREMENTS",
    display_code: "REQSPEC-v1",
    title: "Requirements Specification",
  },
  {
    reference: {
      kind: "REQUIREMENT",
      artifact_id: REQUIREMENT_ID,
      version_number: null,
      content_hash: null,
    },
    stage: "REQUIREMENTS",
    display_code: "REQ-001",
    title: "Create reservations",
  },
  {
    reference: {
      kind: "DESIGN_PACKAGE",
      artifact_id: DESIGN_ID,
      version_number: 2,
      content_hash: "b".repeat(64),
    },
    stage: "DESIGN",
    display_code: "DESIGN-v2",
    title: "Design Exploration Package",
  },
  {
    reference: {
      kind: "DESIGN_ALTERNATIVE",
      artifact_id: ALTERNATIVE_ID,
      version_number: null,
      content_hash: null,
    },
    stage: "DESIGN",
    display_code: "DES-001",
    title: "Guided reservation workflow",
  },
];

const links: ArtifactGraphLinkPayload[] = [
  {
    kind: "CONTAINS",
    source: nodes[0]!.reference,
    target: nodes[1]!.reference,
  },
  {
    kind: "GROUNDED_IN",
    source: nodes[2]!.reference,
    target: nodes[0]!.reference,
  },
  {
    kind: "CONTAINS",
    source: nodes[2]!.reference,
    target: nodes[3]!.reference,
  },
  {
    kind: "TRACES_TO",
    source: nodes[3]!.reference,
    target: nodes[1]!.reference,
  },
];

export const ARTIFACT_GRAPH: CrossStageArtifactGraphPayload = {
  schema_version: 1,
  project_id: ARTIFACT_GRAPH_PROJECT_ID,
  requirements_reference: {
    kind: "REQUIREMENTS_SPECIFICATION",
    artifact_id: REQUIREMENTS_ID,
    version_number: 1,
    content_hash: "a".repeat(64),
  },
  design_reference: {
    kind: "DESIGN_PACKAGE",
    artifact_id: DESIGN_ID,
    version_number: 2,
    content_hash: "b".repeat(64),
  },
  nodes,
  links,
  stage_counts: {
    CONTEXT: 0,
    REQUIREMENTS: 2,
    DESIGN: 2,
  },
  content_hash: "d".repeat(64),
};
