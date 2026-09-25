import type { BriefField, ProjectBriefVersionResponse } from "@/api/contracts";
import type { BriefAssumptionResponse } from "@/api/workflow-contracts";

export type BriefDialogueStatus = "OPEN" | "READY" | "SYNTHESIZED" | "CLOSED";

export type DialogueAnswerKind = "TEXT" | "ITEM_LIST" | "UNKNOWN";

export type DialogueAnswerType = "TEXT" | "ITEM_LIST";

export interface DialogueAnswerPayload {
  kind: DialogueAnswerKind;
  text: string | null;
  items: string[] | null;
}

export interface BriefDialogueTurnPayload {
  id: string;
  dialogue_id: string;
  ordinal: number;
  field: BriefField | null;
  answer_type: DialogueAnswerType;
  question: string;
  model_generation_id: string;
  asked_at: string;
  answer: DialogueAnswerPayload | null;
  answered_at: string | null;
}

export interface BriefDialoguePayload {
  id: string;
  project_id: string;
  source_brief_version_number: number;
  statement: string;
  status: BriefDialogueStatus;
  created_at: string;
  question_limit: number;
  essential_fields: BriefField[];
  asked_fields: BriefField[];
  turns: BriefDialogueTurnPayload[];
  resulting_brief_version_number: number | null;
  synthesis_generation_id: string | null;
  completed_at: string | null;
}

export interface BriefDialogueProgress {
  questions_asked: number;
  question_limit: number;
  open_fields: BriefField[];
  open_essential_fields: BriefField[];
}

export type BriefDialogueOutcome =
  | "BRIEF_DIALOGUE_CURRENT"
  | "BRIEF_DIALOGUE_STARTED"
  | "BRIEF_QUESTION_ASKED"
  | "BRIEF_DIALOGUE_READY"
  | "BRIEF_SYNTHESIZED"
  | "BRIEF_DIALOGUE_CLOSED";

export interface BriefDialogueResponse {
  status: BriefDialogueOutcome;
  snapshot: BriefDialoguePayload;
  progress: BriefDialogueProgress;
  brief_version: ProjectBriefVersionResponse | null;
  assumptions: BriefAssumptionResponse[];
}

export interface DialogueAnswerInput {
  expected_turn_count: number;
  kind: DialogueAnswerKind;
  text?: string | null;
  items?: string[] | null;
}
