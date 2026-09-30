import type { CritiqueVerdict, DevelopmentReferencePayload, FindingSeverity } from "./codeChanges";

export type TestApplicationKind = "URL" | "STATIC";

export type TestBrowserName = "chrome" | "firefox";

export type TestAction = "OPEN" | "CLICK" | "TYPE" | "SELECT" | "PRESS" | "CHECK";

export type TestExpectationKind =
  | "TEXT_VISIBLE"
  | "TEXT_ABSENT"
  | "ELEMENT_VISIBLE"
  | "ELEMENT_ABSENT"
  | "VALUE_IS"
  | "URL_CONTAINS"
  | "TITLE_CONTAINS";

export type TestRole =
  | "button"
  | "link"
  | "textbox"
  | "checkbox"
  | "radio"
  | "combobox"
  | "option"
  | "slider"
  | "spinbutton"
  | "switch"
  | "heading"
  | "text"
  | "image"
  | "alert"
  | "status"
  | "dialog"
  | "tab"
  | "listitem"
  | "cell"
  | "progressbar";

export type TestPathStatus = "PASSED" | "FAILED" | "BLOCKED" | "NOT_RUN";

export type TestStepStatus = "DONE" | "FAILED" | "BLOCKED" | "SKIPPED";

export type CriterionStatus = "PASSED" | "FAILED" | "BLOCKED" | "NOT_COVERED" | "NOT_RUN";

export interface TestApplicationPayload {
  kind: TestApplicationKind;
  address: string;
}

export interface TestBrowserPayload {
  name: TestBrowserName;
  version: string;
}

export interface TestRunReferencePayload {
  requirements_version_number: number;
  design_version_number: number;
  alternative_code: string | null;
}

export interface TestTargetPayload {
  role: TestRole | null;
  name: string;
}

export interface TestExpectationPayload {
  kind: TestExpectationKind;
  target: TestTargetPayload | null;
  text: string | null;
}

export interface TestStepPayload {
  action: TestAction;
  target: TestTargetPayload | null;
  value: string | null;
  expect: TestExpectationPayload | null;
}

export interface TestPathPayload {
  code: string;
  heading: string;
  criteria: string[];
  steps: TestStepPayload[];
}

export interface TestStepResultPayload {
  index: number;
  status: TestStepStatus;
  detail: string | null;
  url: string | null;
  title: string | null;
  screenshot: string | null;
}

export interface TestResultPayload {
  path: TestPathPayload;
  browser: TestBrowserName;
  status: TestPathStatus;
  seconds: number;
  steps: TestStepResultPayload[];
  page_text: string | null;
}

export interface TestRunSummaryPayload {
  passed: number;
  failed: number;
  blocked: number;
  not_covered: number;
  not_run: number;
}

export interface CriterionOutcomePayload {
  code: string;
  status: CriterionStatus;
  paths: string[];
}

export interface NotCoveredPayload {
  criterion: string;
  reason: string;
}

export interface TestFindingSubjectPayload {
  criterion: string | null;
  requirement: string | null;
  screen: string | null;
}

export interface TestFindingPayload {
  severity: FindingSeverity;
  text: string;
  about: TestFindingSubjectPayload;
  action: string | null;
}

export interface TestCritiquePayload {
  twin_id: string;
  twin_name: string;
  verdict: CritiqueVerdict;
  summary: string;
  findings: TestFindingPayload[];
}

export interface TestRunPayload {
  id: string;
  started_at: string;
  finished_at: string;
  recorded_at: string;
  application: TestApplicationPayload;
  browsers: TestBrowserPayload[];
  reference: TestRunReferencePayload;
  summary: TestRunSummaryPayload;
  criteria: CriterionOutcomePayload[];
  not_covered: NotCoveredPayload[];
  results: TestResultPayload[];
  critiques: TestCritiquePayload[];
  reviewed_at: string | null;
  cost_microusd: number;
}

export interface AcceptanceTestsOverviewPayload {
  project_id: string;
  reference: DevelopmentReferencePayload;
  plan_available: boolean;
  plans: number;
  runs: number;
  latest_run: TestRunPayload | null;
}
