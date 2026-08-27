import { createPinia } from "pinia";
import { flushPromises, mount } from "@vue/test-utils";
import { describe, expect, it } from "vitest";

import type { WebExecutionApi } from "@/api/webExecution";
import type {
  ApplyWebRepairProposalInput,
  WebBrowserEvidencePayload,
  WebExecutionAttemptPayload,
  WebExecutionReportPayload,
  WebRepairProposalPayload,
  WebSourceRevisionPayload,
} from "@/types/webExecution";
import ProjectWebEvidenceReview from "./ProjectWebEvidenceReview.vue";

const PROJECT_ID = "00000000-0000-4000-8000-00000000e101";
const OWNER_ID = "00000000-0000-4000-8000-00000000e102";
const REVISION_ID = "00000000-0000-4000-8000-00000000e103";
const EXECUTION_ID = "00000000-0000-4000-8000-00000000e104";
const PROPOSAL_ID = "00000000-0000-4000-8000-00000000e105";
const CHANGE_SET_ID = "00000000-0000-4000-8000-00000000e106";
const CREATED_AT = "2026-08-27T14:00:00+00:00";

const REVISION: WebSourceRevisionPayload = {
  id: REVISION_ID,
  project_id: PROJECT_ID,
  created_by_user_id: OWNER_ID,
  version_number: 1,
  based_on: null,
  target_selection: {
    target: "WEB_STATIC",
    language_configuration: { frontend: "STATIC_ASSETS", backend: null },
    layout: "SINGLE_ROOT",
  },
  validation_scope_hash: "1".repeat(64),
  origin: "DETERMINISTIC_FIXTURE",
  files: [],
  provenance_references: [],
  related_failure_signature: null,
  created_at: CREATED_AT,
  source_tree_hash: "2".repeat(64),
  content_hash: "3".repeat(64),
};

const EVIDENCE_REFERENCE = {
  storage_key: `sha256/44/${"4".repeat(64)}`,
  sha256_digest: "4".repeat(64),
  size_bytes: 120,
  media_type: "text/plain",
};

const REPORT: WebExecutionReportPayload = {
  source_revision_content_hash: REVISION.content_hash,
  source_tree_hash: REVISION.source_tree_hash,
  profile_id: "web.static",
  profile_version: "1.0.0",
  runner_image_digest: "5".repeat(64),
  policy_content_hash: "6".repeat(64),
  status: "FAILED",
  phase_results: [
    {
      phase: "TEST",
      status: "FAILED",
      command_plan_hashes: ["7".repeat(64)],
      started_at: CREATED_AT,
      completed_at: "2026-08-27T14:00:01+00:00",
      exit_codes: [1],
      stdout_refs: [EVIDENCE_REFERENCE],
      stderr_refs: [],
      artifact_refs: [],
      findings: [
        {
          code: "ASSERTION_FAILED",
          message: "Expected the accessible title.",
          source_tool: "playwright",
          location: "/",
        },
      ],
      failure_category: "TEST",
      failure_code: "TEST_PLAYWRIGHT_FAILED",
      normalized_summary: "The deterministic browser assertion failed.",
    },
  ],
  failure_signatures: [
    {
      category: "TEST",
      phase: "TEST",
      profile_id: "web.static",
      profile_version: "1.0.0",
      failure_code: "TEST_PLAYWRIGHT_FAILED",
      normalized_message: "The deterministic browser assertion failed.",
      subject_refs: ["/"],
      digest: "8".repeat(64),
    },
  ],
};

const EXECUTION: WebExecutionAttemptPayload = {
  id: EXECUTION_ID,
  project_id: PROJECT_ID,
  created_by_user_id: OWNER_ID,
  attempt_number: 1,
  previous_attempt_id: null,
  source_revision: {
    revision_id: REVISION_ID,
    project_id: PROJECT_ID,
    version_number: 1,
    content_hash: REVISION.content_hash,
    source_tree_hash: REVISION.source_tree_hash,
  },
  profile_validation_content_hash: "9".repeat(64),
  execution_plan_content_hash: "a".repeat(64),
  trigger: "PROFILE_VALIDATION",
  executed_phases: ["TEST"],
  report: REPORT,
  started_at: CREATED_AT,
  completed_at: "2026-08-27T14:00:01+00:00",
  content_hash: "b".repeat(64),
};

const BROWSER: WebBrowserEvidencePayload = {
  request: {
    source_revision_content_hash: REVISION.content_hash,
    source_tree_hash: REVISION.source_tree_hash,
    runner_image_digest: "c".repeat(64),
    base_url: "http://127.0.0.1:4173",
    routes: [{ route_id: "root", path: "/" }],
    policy: {
      maximum_routes: 5,
      maximum_console_messages_per_route: 100,
      maximum_failed_requests_per_route: 100,
      maximum_accessibility_findings_per_route: 200,
    },
    content_hash: "d".repeat(64),
  },
  status: "COLLECTED",
  routes: [
    {
      route: { route_id: "root", path: "/" },
      status: "COLLECTED",
      final_path: "/",
      screenshot_ref: { ...EVIDENCE_REFERENCE, media_type: "image/png" },
      dom_snapshot_ref: { ...EVIDENCE_REFERENCE, media_type: "text/html" },
      raw_playwright_ref: {
        ...EVIDENCE_REFERENCE,
        media_type: "application/json",
      },
      accessibility_report_ref: {
        ...EVIDENCE_REFERENCE,
        media_type: "application/json",
      },
      console_messages: [],
      failed_requests: [],
      accessibility_findings: [
        {
          rule_id: "document-title",
          impact: "SERIOUS",
          description: "Documents must have a title.",
          help_text: "Add a non-empty title element.",
          targets: ["html"],
        },
      ],
      failure_code: null,
      failure_message: null,
    },
  ],
  normalized_findings: [],
  content_hash: "e".repeat(64),
};

const PROPOSAL: WebRepairProposalPayload = {
  id: PROPOSAL_ID,
  project_id: PROJECT_ID,
  created_by_user_id: OWNER_ID,
  base_revision: EXECUTION.source_revision,
  failure_signature: REPORT.failure_signatures[0]!,
  change_set: {
    id: CHANGE_SET_ID,
    project_id: PROJECT_ID,
    base_revision: EXECUTION.source_revision,
    changes: [
      {
        normalized_path: "index.html",
        operation: "REPLACE",
        content_sha256: "f".repeat(64),
        size_bytes: 42,
        storage_key: `sha256/ff/${"f".repeat(64)}`,
        media_type: "text/html",
      },
    ],
    rationale: "Add the missing accessible document title.",
    provenance_references: ["failure:document-title"],
    content_hash: "0".repeat(64),
  },
  attempt_number: 1,
  identical_failure_occurrences: 1,
  provenance_references: [],
  created_at: "2026-08-27T14:00:02+00:00",
};

class FakeWebExecutionApi {
  appliedInput: ApplyWebRepairProposalInput | null = null;

  async sourceRevisions(): Promise<WebSourceRevisionPayload[]> {
    return [REVISION];
  }

  async executions(): Promise<WebExecutionAttemptPayload[]> {
    return [EXECUTION];
  }

  async execution(): Promise<WebExecutionAttemptPayload> {
    return EXECUTION;
  }

  async executionReport(): Promise<WebExecutionReportPayload> {
    return REPORT;
  }

  async browserEvidence(): Promise<WebBrowserEvidencePayload> {
    return BROWSER;
  }

  async repairProposals(): Promise<WebRepairProposalPayload[]> {
    return [PROPOSAL];
  }

  async applyRepairProposal(
    _executionId: string,
    _proposalId: string,
    input: ApplyWebRepairProposalInput,
  ): Promise<WebSourceRevisionPayload> {
    this.appliedInput = input;
    return {
      ...REVISION,
      id: "00000000-0000-4000-8000-00000000e107",
      version_number: 2,
    };
  }
}

const authorize = async <T>(operation: (accessToken: string) => Promise<T>): Promise<T> =>
  operation("token");

describe("ProjectWebEvidenceReview", () => {
  it("keeps phase, raw, browser, axe, and failure evidence visibly distinct", async () => {
    const api = new FakeWebExecutionApi();
    const wrapper = mount(ProjectWebEvidenceReview, {
      props: {
        projectId: PROJECT_ID,
        authorize,
        api: api as unknown as WebExecutionApi,
      },
      global: { plugins: [createPinia()] },
    });
    await flushPromises();

    expect(wrapper.text()).toContain("Execution, browser, and repair evidence");
    expect(wrapper.text()).toContain("TEST_PLAYWRIGHT_FAILED");
    expect(wrapper.text()).toContain(EVIDENCE_REFERENCE.storage_key);
    expect(wrapper.text()).toContain("SERIOUS · document-title");
    expect(wrapper.text()).toContain("not complete WCAG certification");
    expect(wrapper.text()).toContain("REPLACE · index.html");
  });

  it("applies one exact proposal tuple and leaves approval optional", async () => {
    const api = new FakeWebExecutionApi();
    const wrapper = mount(ProjectWebEvidenceReview, {
      props: {
        projectId: PROJECT_ID,
        authorize,
        api: api as unknown as WebExecutionApi,
      },
      global: { plugins: [createPinia()] },
    });
    await flushPromises();

    const repairSection = wrapper.get("section[aria-labelledby='web-repair-proposals-title']");
    await repairSection.get("button").trigger("click");
    await flushPromises();

    expect(api.appliedInput).toEqual({
      base_revision_content_hash: REVISION.content_hash,
      proposal_content_hash: PROPOSAL.change_set.content_hash,
      approval_id: null,
    });
  });

  it("renders the Italian evidence and methodological labels", async () => {
    const wrapper = mount(ProjectWebEvidenceReview, {
      props: {
        projectId: PROJECT_ID,
        locale: "it",
        authorize,
        api: new FakeWebExecutionApi() as unknown as WebExecutionApi,
      },
      global: { plugins: [createPinia()] },
    });
    await flushPromises();

    expect(wrapper.text()).toContain("Evidenze di esecuzione, browser e repair");
    expect(wrapper.text()).toContain("Firme stabili degli errori");
    expect(wrapper.text()).toContain("certificazione WCAG completa");
  });
});
