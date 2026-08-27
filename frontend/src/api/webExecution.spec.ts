import { describe, expect, it, vi } from "vitest";

import type {
  ApplyWebRepairProposalInput,
  CreateWebRepairProposalInput,
  CreateWebSourceRevisionInput,
  StartWebExecutionInput,
  WebExecutionAttemptPayload,
  WebRepairProposalPayload,
  WebSourceRevisionPayload,
} from "../types/webExecution";
import { createWebExecutionApi, WebExecutionApiError } from "./webExecution";

const PROJECT_ID = "00000000-0000-4000-8000-00000000b101";
const REVISION_ID = "00000000-0000-4000-8000-00000000b102";
const EXECUTION_ID = "00000000-0000-4000-8000-00000000b103";
const PROPOSAL_ID = "00000000-0000-4000-8000-00000000b104";

const REVISION: WebSourceRevisionPayload = {
  id: REVISION_ID,
  project_id: PROJECT_ID,
  created_by_user_id: "00000000-0000-4000-8000-00000000b105",
  version_number: 1,
  based_on: null,
  target_selection: {
    target: "WEB_STATIC",
    language_configuration: { frontend: "STATIC_ASSETS", backend: null },
    layout: "SINGLE_ROOT",
  },
  validation_scope_hash: "1".repeat(64),
  origin: "GENERATED_PLAN",
  files: [],
  provenance_references: [],
  related_failure_signature: null,
  created_at: "2026-08-27T14:00:00+00:00",
  source_tree_hash: "2".repeat(64),
  content_hash: "3".repeat(64),
};

const EXECUTION: WebExecutionAttemptPayload = {
  id: EXECUTION_ID,
  project_id: PROJECT_ID,
  created_by_user_id: "00000000-0000-4000-8000-00000000b105",
  attempt_number: 1,
  previous_attempt_id: null,
  source_revision: {
    revision_id: REVISION_ID,
    project_id: PROJECT_ID,
    version_number: 1,
    content_hash: REVISION.content_hash,
    source_tree_hash: REVISION.source_tree_hash,
  },
  profile_validation_content_hash: "4".repeat(64),
  execution_plan_content_hash: "5".repeat(64),
  trigger: "PROFILE_VALIDATION",
  executed_phases: ["VALIDATE"],
  report: {
    source_revision_content_hash: REVISION.content_hash,
    source_tree_hash: REVISION.source_tree_hash,
    profile_id: "web.static",
    profile_version: "1.0.0",
    runner_image_digest: "6".repeat(64),
    policy_content_hash: "7".repeat(64),
    status: "INCOMPLETE",
    phase_results: [],
    failure_signatures: [],
  },
  started_at: "2026-08-27T14:00:00+00:00",
  completed_at: "2026-08-27T14:00:01+00:00",
  content_hash: "8".repeat(64),
};

const PROPOSAL: WebRepairProposalPayload = {
  id: PROPOSAL_ID,
  project_id: PROJECT_ID,
  created_by_user_id: EXECUTION.created_by_user_id,
  base_revision: EXECUTION.source_revision,
  failure_signature: {
    category: "TEST",
    phase: "TEST",
    profile_id: "web.static",
    profile_version: "1.0.0",
    failure_code: "TEST_FAILED",
    normalized_message: "Static assertion failed.",
    subject_refs: [],
    digest: "9".repeat(64),
  },
  change_set: {
    id: "00000000-0000-4000-8000-00000000b106",
    project_id: PROJECT_ID,
    base_revision: EXECUTION.source_revision,
    changes: [],
    rationale: "Repair the deterministic fixture.",
    provenance_references: ["failure:fixture"],
    content_hash: "a".repeat(64),
  },
  attempt_number: 1,
  identical_failure_occurrences: 1,
  provenance_references: [],
  created_at: "2026-08-27T14:00:02+00:00",
};

function jsonResponse(payload: unknown, status = 200): Response {
  return new Response(JSON.stringify(payload), {
    status,
    headers: { "Content-Type": "application/json" },
  });
}

function sourceInput(): CreateWebSourceRevisionInput {
  return {
    target_selection: REVISION.target_selection,
    rationale: "Materialize the approved source plan.",
    files: [{ normalized_path: "index.html", content: "ready", media_type: "text/html" }],
    provenance_references: [
      {
        kind: "SOURCE_PLAN",
        reference_id: "source-plan-1",
        version_number: 1,
        content_hash: "b".repeat(64),
      },
    ],
  };
}

function executionInput(): StartWebExecutionInput {
  return {
    source_revision_id: REVISION_ID,
    profile_id: "web.static",
    profile_version: "1.0.0",
    policy_content_hash: "c".repeat(64),
    runners: {
      execution_runner_image_digest: "d".repeat(64),
      browser_runner_image_digest: "e".repeat(64),
    },
    purpose: "PROFILE_VALIDATION",
    trigger: "PROFILE_VALIDATION",
    authorization_id: null,
    rerun_phases: null,
    declared_routes: [{ route_id: "root", path: "/" }],
  };
}

describe("Web execution API", () => {
  it("uses typed project and execution resource paths", async () => {
    const fetchImpl = vi
      .fn<typeof fetch>()
      .mockResolvedValueOnce(jsonResponse({ items: [REVISION] }))
      .mockResolvedValueOnce(jsonResponse({ items: [EXECUTION] }))
      .mockResolvedValueOnce(jsonResponse({ snapshot: EXECUTION.report }))
      .mockResolvedValueOnce(jsonResponse({ items: [PROPOSAL] }));
    const api = createWebExecutionApi({ fetchImpl });

    await expect(api.sourceRevisions(PROJECT_ID, "token")).resolves.toEqual([REVISION]);
    await expect(api.executions(PROJECT_ID, "token")).resolves.toEqual([EXECUTION]);
    await expect(api.executionReport(EXECUTION_ID, "token")).resolves.toEqual(EXECUTION.report);
    await expect(api.repairProposals(EXECUTION_ID, "token")).resolves.toEqual([PROPOSAL]);

    expect(fetchImpl.mock.calls.map(([path]) => path)).toEqual([
      `/api/v1/projects/${PROJECT_ID}/web-source-revisions`,
      `/api/v1/projects/${PROJECT_ID}/web-executions`,
      `/api/v1/web-executions/${EXECUTION_ID}/report`,
      `/api/v1/web-executions/${EXECUTION_ID}/repair-proposals`,
    ]);
  });

  it("serializes source, execution, and repair command bodies without command strings", async () => {
    const fetchImpl = vi
      .fn<typeof fetch>()
      .mockResolvedValueOnce(
        jsonResponse(
          { status: "SOURCE_REVISION_CREATED", snapshot: REVISION, message: "Created" },
          201,
        ),
      )
      .mockResolvedValueOnce(
        jsonResponse(
          { status: "EXECUTION_RECORDED", snapshot: EXECUTION, message: "Recorded" },
          201,
        ),
      )
      .mockResolvedValueOnce(
        jsonResponse({ status: "REPAIR_PROPOSED", snapshot: PROPOSAL, message: "Proposed" }, 201),
      )
      .mockResolvedValueOnce(
        jsonResponse({ status: "REPAIR_APPLIED", snapshot: REVISION, message: "Applied" }),
      );
    const api = createWebExecutionApi({ fetchImpl });
    const repairInput: CreateWebRepairProposalInput = {
      base_revision_content_hash: REVISION.content_hash,
      failure_signature_digest: PROPOSAL.failure_signature.digest,
      changes: [
        {
          operation: "REPLACE",
          normalized_path: "index.html",
          content: "repaired",
          media_type: "text/html",
        },
      ],
      rationale: "Repair the failing deterministic fixture.",
    };
    const applyInput: ApplyWebRepairProposalInput = {
      base_revision_content_hash: REVISION.content_hash,
      proposal_content_hash: PROPOSAL.change_set.content_hash,
      approval_id: null,
    };

    await api.createSourceRevision(PROJECT_ID, sourceInput(), "token");
    await api.startExecution(PROJECT_ID, executionInput(), "token");
    await api.createRepairProposal(EXECUTION_ID, repairInput, "token");
    await api.applyRepairProposal(EXECUTION_ID, PROPOSAL_ID, applyInput, "token");

    const bodies = fetchImpl.mock.calls.map(([, init]) => String(init?.body ?? ""));
    expect(bodies[0]).toContain("index.html");
    expect(bodies[1]).toContain("PROFILE_VALIDATION");
    expect(bodies[2]).toContain("REPLACE");
    expect(bodies[3]).toContain(PROPOSAL.change_set.content_hash);
    expect(bodies.join(" ")).not.toContain("shell_command");
    expect(bodies.join(" ")).not.toContain("host_command");
  });

  it("returns typed error metadata and rejects missing access tokens", async () => {
    const api = createWebExecutionApi({
      fetchImpl: vi
        .fn<typeof fetch>()
        .mockResolvedValue(
          jsonResponse({ detail: { code: "WEB_EXECUTION_RESOURCE_NOT_FOUND" } }, 404),
        ),
    });

    await expect(api.execution(EXECUTION_ID, "token")).rejects.toMatchObject({
      status: 404,
      code: "WEB_EXECUTION_RESOURCE_NOT_FOUND",
    });
    await expect(api.execution(EXECUTION_ID, "  ")).rejects.toBeInstanceOf(WebExecutionApiError);
  });
});
