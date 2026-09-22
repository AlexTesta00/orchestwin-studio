export type TwinInsightKind = "NEED" | "FRUSTRATION" | "PREFERENCE" | "RISK" | "OPEN_QUESTION";

export interface TwinInsightPayload {
  kind: TwinInsightKind;
  text: string;
  confidence: number;
  grounded_on: string[];
}

export interface TwinTurnPayload {
  id: string;
  ordinal: number;
  question: string;
  reply: string;
  insights: TwinInsightPayload[];
  model_generation_id: string;
  content_hash: string;
  created_at: string;
  epistemic_status: "HYPOTHESIS";
  human_validation: "REQUIRED";
}

export interface TwinConversationPayload {
  id: string;
  project_id: string;
  twin_id: string;
  twin_version_number: number;
  twin_content_hash: string;
  twin_name: string;
  created_at: string;
  turns: TwinTurnPayload[];
}

export interface AskTwinInput {
  question: string;
  expected_turn_count: number;
}
