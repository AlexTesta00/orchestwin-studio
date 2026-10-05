import type { AgentIdentifier } from "@/api/team-contracts";
import type { HumanGatePayload } from "./design";
import type { BoundGeneratedMockupPayload, GeneratedScreenPayload } from "./designMockups";
import type { RequirementsSpecificationPayload } from "./requirements";
import type { ProfileReplacementRequest } from "./userModeling";

export const WORKFLOW_TARGETS = [
  "BRIEF",
  "TEAM",
  "USER_TWINS",
  "EVIDENCE",
  "SCENARIOS",
  "NEEDS",
  "REQUIREMENTS",
  "JOURNEYS",
  "DESIGN",
  "EVALUATION",
  "PACKAGE",
] as const;
export type WorkflowTarget = (typeof WORKFLOW_TARGETS)[number];
export interface WorkflowReference {
  artifact_id: string;
  version_number: number;
  content_hash: string;
}
export interface WorkflowDecisionInput {
  target: WorkflowTarget;
  action: "DECLARE_MISSING" | "RESOLVE_MISSING";
  reason: string;
  base_context: Partial<Record<WorkflowTarget, WorkflowReference>>;
}
export interface WorkflowDecision extends WorkflowDecisionInput {
  id: string;
  project_id: string;
  sequence: number;
  recorded_at: string;
  content_hash: string;
}
export interface ProvidedPrototype {
  id: string;
  code: string;
  project_id: string;
  version_number: number;
  based_on_version_number: number | null;
  definition_reference: WorkflowReference;
  title: string;
  declared_origin?: string;
  visual_choices: Record<string, string>;
  mockup: BoundGeneratedMockupPayload;
  created_at: string;
  content_hash: string;
}
export interface ProvidedPrototypeInput {
  title: string;
  declared_origin?: string;
  visual_choices: Record<string, string>;
  mockup: { title?: string; styles: string; screens: GeneratedScreenPayload[] };
  expected_definition_reference: WorkflowReference;
  expected_version_number: number;
}
export interface WorkflowInputsPayload {
  kind: "orchestwin.workflow-inputs";
  schema_version: 1;
  project_id: string;
  decisions: WorkflowDecision[];
  prototypes: ProvidedPrototype[];
  limits: string[];
}
export interface OwnerTeamInput {
  selected_agent_ids: AgentIdentifier[];
  owner_rationales: { agent_id: AgentIdentifier; statement: string }[];
}
export interface OwnerProfilesInput {
  profiles: { persona_id: string; name: string; observations: ProfileReplacementRequest[] }[];
}
export interface OwnerDefinitionInput {
  specification: RequirementsSpecificationPayload;
}
export interface ProvidedPrototypeGateResult {
  outcome: string;
  issue?: string | null;
  gate: HumanGatePayload | null;
}
