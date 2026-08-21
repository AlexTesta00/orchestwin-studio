import type {
  ArtifactGraphLinkPayload,
  ArtifactGraphNodePayload,
  CrossStageArtifactGraphPayload,
} from "../types/artifacts";

export const ARTIFACT_GRAPH_PROJECT_ID = "00000000-0000-4000-8000-000000000001";
const REQUIREMENTS_ID = "00000000-0000-4000-8000-000000000010";
const DESIGN_ID = "00000000-0000-4000-8000-000000000020";
const ARCHITECTURE_PACKAGE_ID = "00000000-0000-4000-8000-000000000030";
const REQUIREMENT_ID = "00000000-0000-4000-8000-000000000040";
const ALTERNATIVE_ID = "00000000-0000-4000-8000-000000000050";
const ARCHITECTURE_ID = "00000000-0000-4000-8000-000000000060";
const TEST_CASE_ID = "00000000-0000-4000-8000-000000000070";

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
  {
    reference: {
      kind: "ARCHITECTURE_PACKAGE",
      artifact_id: ARCHITECTURE_PACKAGE_ID,
      version_number: 1,
      content_hash: "c".repeat(64),
    },
    stage: "ARCHITECTURE",
    display_code: "ARCH-v1",
    title: "Architecture and Test Plan Package",
  },
  {
    reference: {
      kind: "SOFTWARE_ARCHITECTURE",
      artifact_id: ARCHITECTURE_ID,
      version_number: null,
      content_hash: null,
    },
    stage: "ARCHITECTURE",
    display_code: "ARC-001",
    title: "Reservation platform architecture",
  },
  {
    reference: {
      kind: "TEST_CASE",
      artifact_id: TEST_CASE_ID,
      version_number: null,
      content_hash: null,
    },
    stage: "TESTING",
    display_code: "TST-001",
    title: "Create a reservation end to end",
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
  {
    kind: "GROUNDED_IN",
    source: nodes[4]!.reference,
    target: nodes[2]!.reference,
  },
  {
    kind: "CONTAINS",
    source: nodes[4]!.reference,
    target: nodes[5]!.reference,
  },
  {
    kind: "REALIZES",
    source: nodes[5]!.reference,
    target: nodes[3]!.reference,
  },
  {
    kind: "TESTS",
    source: nodes[6]!.reference,
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
  architecture_reference: {
    kind: "ARCHITECTURE_PACKAGE",
    artifact_id: ARCHITECTURE_PACKAGE_ID,
    version_number: 1,
    content_hash: "c".repeat(64),
  },
  nodes,
  links,
  stage_counts: {
    CONTEXT: 0,
    REQUIREMENTS: 2,
    DESIGN: 2,
    ARCHITECTURE: 2,
    TESTING: 1,
  },
  content_hash: "d".repeat(64),
};
