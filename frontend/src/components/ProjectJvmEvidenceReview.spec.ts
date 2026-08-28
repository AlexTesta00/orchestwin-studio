import { createPinia } from "pinia";
import { flushPromises, mount } from "@vue/test-utils";
import { describe, expect, it } from "vitest";

import type { JvmExecutionApi } from "@/api/jvmExecution";
import type {
  ApplyJvmRepairProposalInput,
  JvmExecutionAttemptPayload,
  JvmExecutionReportPayload,
  JvmProfilePayload,
  JvmRepairProposalPayload,
  JvmSourceRevisionPayload,
} from "@/types/jvmExecution";
import ProjectJvmEvidenceReview from "./ProjectJvmEvidenceReview.vue";

const PROJECT_ID = "00000000-0000-4000-8000-00000000a101";
const OWNER_ID = "00000000-0000-4000-8000-00000000a102";
const REVISION_ID = "00000000-0000-4000-8000-00000000a103";
const EXECUTION_ID = "00000000-0000-4000-8000-00000000a104";
const PROPOSAL_ID = "00000000-0000-4000-8000-00000000a105";
const CREATED_AT = "2026-08-28T19:00:00+00:00";

const PROFILE: JvmProfilePayload = {
  profile_id: "jvm.kotlin-gradle",
  profile_version: "1.0.0",
  target: "JVM_KOTLIN",
  capability_status: "DESIGN_ONLY_LEVEL_C",
};

const REVISION: JvmSourceRevisionPayload = {
  id: REVISION_ID,
  project_id: PROJECT_ID,
  created_by_user_id: OWNER_ID,
  version_number: 1,
  based_on: null,
  target_selection: {
    target: "JVM_KOTLIN",
    language: "KOTLIN",
    build_system: "GRADLE_KOTLIN_DSL",
    layout: "SINGLE_MODULE",
    jdk_major: 21,
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

const REPORT: JvmExecutionReportPayload = {
  target_selection: REVISION.target_selection,
  execution_plan_content_hash: "5".repeat(64),
  status: "FAILED",
  phase_results: [
    {
      phase: "TEST",
      status: "FAILED",
      command_plan_hash: "6".repeat(64),
      started_at: CREATED_AT,
      completed_at: "2026-08-28T19:00:01+00:00",
      exit_codes: [1],
      stdout_refs: [EVIDENCE_REFERENCE],
      stderr_refs: [],
      artifact_refs: [],
      findings: [
        {
          code: "ASSERTION_FAILED",
          message: "Expected calculator result 4.",
          source_tool: "junit",
          location: "CalculatorTest.kt",
        },
      ],
      failure_category: "TEST",
      failure_code: "JVM_TEST_FAILED",
      normalized_summary: "The Kotlin calculator fixture test failed.",
    },
  ],
  failure_signatures: [
    {
      category: "TEST",
      phase: "TEST",
      failure_code: "JVM_TEST_FAILED",
      normalized_message: "The Kotlin calculator fixture test failed.",
      signature: "7".repeat(64),
    },
  ],
};

const EXECUTION: JvmExecutionAttemptPayload = {
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
  profile_id: PROFILE.profile_id,
  profile_version: PROFILE.profile_version,
  profile_validation_content_hash: "8".repeat(64),
  execution_plan_content_hash: "5".repeat(64),
  runner_id: "jvm.gradle",
  runner_version: "1.0.0",
  runner_image_digest: "9".repeat(64),
  policy_content_hash: "a".repeat(64),
  trigger: "PROFILE_VALIDATION",
  executed_phases: ["TEST"],
  report: REPORT,
  started_at: CREATED_AT,
  completed_at: "2026-08-28T19:00:01+00:00",
  content_hash: "b".repeat(64),
};

const PROPOSAL: JvmRepairProposalPayload = {
  id: PROPOSAL_ID,
  project_id: PROJECT_ID,
  created_by_user_id: OWNER_ID,
  base_revision: EXECUTION.source_revision,
  failure_signature: REPORT.failure_signatures[0]!,
  change_set: {
    id: "00000000-0000-4000-8000-00000000a106",
    content_hash: "c".repeat(64),
    changes: [
      {
        normalized_path: "src/main/kotlin/org/orchestwin/calculator/Calculator.kt",
        operation: "REPLACE",
        content_sha256: "d".repeat(64),
        size_bytes: 42,
        storage_key: `sha256/dd/${"d".repeat(64)}`,
        media_type: "text/x-kotlin",
      },
    ],
    rationale: "Repair the bounded Kotlin calculator fixture.",
  },
  attempt_number: 1,
  identical_failure_occurrences: 1,
  created_at: "2026-08-28T19:00:02+00:00",
};

class FakeJvmExecutionApi {
  appliedInput: ApplyJvmRepairProposalInput | null = null;

  async profiles(): Promise<JvmProfilePayload[]> {
    return [PROFILE];
  }
  async sourceRevisions(): Promise<JvmSourceRevisionPayload[]> {
    return [REVISION];
  }
  async executions(): Promise<JvmExecutionAttemptPayload[]> {
    return [EXECUTION];
  }
  async execution(): Promise<JvmExecutionAttemptPayload> {
    return EXECUTION;
  }
  async executionReport(): Promise<JvmExecutionReportPayload> {
    return REPORT;
  }
  async repairProposals(): Promise<JvmRepairProposalPayload[]> {
    return [PROPOSAL];
  }
  async applyRepairProposal(
    _executionId: string,
    _proposalId: string,
    input: ApplyJvmRepairProposalInput,
  ): Promise<JvmSourceRevisionPayload> {
    this.appliedInput = input;
    return { ...REVISION, id: "00000000-0000-4000-8000-00000000a107", version_number: 2 };
  }
}

const authorize = async <T>(operation: (accessToken: string) => Promise<T>): Promise<T> =>
  operation("token");

describe("ProjectJvmEvidenceReview", () => {
  it("keeps phase, raw artifact, failure, and repair evidence visibly distinct", async () => {
    const wrapper = mount(ProjectJvmEvidenceReview, {
      props: {
        projectId: PROJECT_ID,
        authorize,
        api: new FakeJvmExecutionApi() as unknown as JvmExecutionApi,
      },
      global: { plugins: [createPinia()] },
    });
    await flushPromises();

    expect(wrapper.text()).toContain("Execution and bounded repair evidence");
    expect(wrapper.text()).toContain("JVM_TEST_FAILED");
    expect(wrapper.text()).toContain(EVIDENCE_REFERENCE.storage_key);
    expect(wrapper.text()).toContain("Stable failure signatures");
    expect(wrapper.text()).toContain(
      "REPLACE · src/main/kotlin/org/orchestwin/calculator/Calculator.kt",
    );
    expect(wrapper.text()).toContain(
      "do not by themselves establish general LLM generation quality",
    );
  });

  it("applies one exact proposal tuple with optional Gate 7 approval", async () => {
    const api = new FakeJvmExecutionApi();
    const wrapper = mount(ProjectJvmEvidenceReview, {
      props: { projectId: PROJECT_ID, authorize, api: api as unknown as JvmExecutionApi },
      global: { plugins: [createPinia()] },
    });
    await flushPromises();

    const repairSection = wrapper.get("section[aria-labelledby='jvm-repair-proposals-title']");
    await repairSection.get("button").trigger("click");
    await flushPromises();

    expect(api.appliedInput).toEqual({
      base_revision_content_hash: REVISION.content_hash,
      proposal_content_hash: PROPOSAL.change_set?.content_hash,
      approval_id: null,
    });
  });

  it("renders the Italian evidence and methodological labels", async () => {
    const wrapper = mount(ProjectJvmEvidenceReview, {
      props: {
        projectId: PROJECT_ID,
        locale: "it",
        authorize,
        api: new FakeJvmExecutionApi() as unknown as JvmExecutionApi,
      },
      global: { plugins: [createPinia()] },
    });
    await flushPromises();

    expect(wrapper.text()).toContain("Evidenze di esecuzione e repair limitato");
    expect(wrapper.text()).toContain("Firme stabili degli errori");
    expect(wrapper.text()).toContain("validazione empirica dei User Twin");
  });
});
