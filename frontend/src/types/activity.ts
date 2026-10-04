export const SECTIONS = [
  "BRIEF",
  "TEAM",
  "USER_TWINS",
  "REQUIREMENTS",
  "DESIGN",
  "PACKAGE",
] as const;
export type ActivitySection = (typeof SECTIONS)[number];

export const ACTORS = ["OWNER", "MODEL", "STUDIO"] as const;
export type ActivityActor = (typeof ACTORS)[number];

export const JOURNAL_KINDS = {
  WEB: [
    "SECTION_OPENED",
    "DETAIL_OPENED",
    "WHY_OPENED",
    "MOCKUP_OPENED",
    "MODE_CHANGED",
    "LOCALE_SET",
    "PAGE_HIDDEN",
    "PAGE_VISIBLE",
    "REQUEST_FAILED",
  ],
  UT: ["COMMAND_STARTED", "COMMAND_FINISHED", "GENERATION_WAITED"],
} as const;
export type WebJournalKind = (typeof JOURNAL_KINDS.WEB)[number];
export type UtJournalKind = (typeof JOURNAL_KINDS.UT)[number];

export const SESSION_KINDS = ["SESSION_STARTED", "SESSION_ENDED"] as const;
export type SessionKind = (typeof SESSION_KINDS)[number];

export const SESSION_CODE_PATTERN = "SES-[A-Z0-9][A-Z0-9-]{0,19}";
export const TARGET_PATTERN = "[A-Za-z0-9][A-Za-z0-9_.:-]{0,79}";
export const STATUS_PATTERN = "[A-Za-z0-9][A-Za-z0-9_.:-]{0,63}";

export const MAX_BATCH_EVENTS = 50;
export const MAX_JOURNAL_EVENTS = 20000;
export const MAX_DURATION_MS = 86_400_000;
export const MAX_DWELL_INTERVAL_SECONDS = 14_400;

export const ACTIVITY_KIND = "orchestwin.project-activity";
export const ACTIVITY_SCHEMA_VERSION = 1;

export function fullMatch(pattern: string, value: unknown): value is string {
  return typeof value === "string" && new RegExp(`^(?:${pattern})$`).test(value);
}

export type ActivityErrorCode =
  | "PROJECT_NOT_FOUND"
  | "ACTIVITY_SERVICE_UNAVAILABLE"
  | "ACTIVITY_SESSION_ACTIVE"
  | "ACTIVITY_SESSION_CODE_USED"
  | "ACTIVITY_SESSION_NOT_ACTIVE"
  | "ACTIVITY_JOURNAL_FULL"
  | "ACTIVITY_INPUT_INVALID"
  | "ACTIVITY_RECORDS_INVALID";

export interface ActivityEventInput {
  kind: WebJournalKind;
  section: ActivitySection | null;
  target: string | null;
  client_at: string;
  duration_ms: number | null;
  status: string | null;
}

export interface ActivityEventsRequest {
  session_code: string;
  source: "WEB";
  events: ActivityEventInput[];
}

export interface ActivitySessionReference {
  code: string;
  started_at: string;
}

export interface ActivitySessionState {
  active: boolean;
  session: ActivitySessionReference | null;
}

export interface ActivitySessionStarted {
  status: "ACTIVITY_SESSION_STARTED";
  session: ActivitySessionReference;
}

export interface ActivitySessionEnded {
  status: "ACTIVITY_SESSION_ENDED";
  session: ActivitySessionReference & { ended_at: string };
}

export interface ActivityEventsRecorded {
  status: "ACTIVITY_EVENTS_RECORDED";
  recorded: number;
}

export interface ProjectActivityEvent {
  number: number;
  at: string;
  source: "SERVER" | "WEB" | "UT" | "STUDIO";
  section: ActivitySection | null;
  kind: string;
  actor: ActivityActor;
  code: string | null;
  version_number: number | null;
  duration_ms: number | null;
  outcome: string | null;
  purpose: string | null;
  role: string | null;
  session_code: string | null;
  target: string | null;
}

export interface ProjectActivitySection {
  key: ActivitySection;
  first_event_at: string | null;
  last_event_at: string | null;
  first_approved_at: string | null;
  approved_at: string | null;
  elapsed_seconds: number | null;
  owner_actions: number;
  gate: { submissions: number; approvals: number; revision_requests: number; rejections: number };
  generations: {
    count: number;
    succeeded: number;
    failed: number;
    retries: number;
    wait_seconds: number;
  };
  journal: {
    opened: number;
    dwell_seconds: number;
    details_opened: number;
    why_opened: number;
    mockups_opened: number;
  };
}

export interface ProjectActivitySession {
  code: string;
  started_at: string;
  ended_at: string | null;
  events: number;
  sources: string[];
  discarded_intervals: number;
}

export interface ProjectActivity {
  kind: typeof ACTIVITY_KIND;
  schema_version: typeof ACTIVITY_SCHEMA_VERSION;
  project_id: string;
  events: ProjectActivityEvent[];
  sections: ProjectActivitySection[];
  brief_dialogue: {
    questions: number;
    answered: number;
    unknown_answers: number;
    answer_seconds: number[];
  };
  sessions: ProjectActivitySession[];
  totals: {
    events: number;
    owner_actions: number;
    generations: number;
    generation_wait_seconds: number;
    first_event_at: string | null;
    last_event_at: string | null;
  };
  limits: string[];
}
