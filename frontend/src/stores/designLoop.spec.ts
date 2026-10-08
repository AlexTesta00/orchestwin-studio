import { createPinia, setActivePinia } from "pinia";
import { beforeEach, describe, expect, it, vi } from "vitest";

import type { DesignLoopApi } from "../api/designLoop";
import { DesignLoopApiError } from "../api/designLoop";
import type {
  DesignDiscussionPayload,
  DesignEvaluationComparisonPayload,
  DesignEvaluationRunPayload,
  FindingValidationPayload,
  InsightApplicationPayload,
  SyntheticFindingPayload,
  TwinEvaluationResponsePayload,
} from "../types/designLoop";
import { findingElement, findingKey, runFindings, runMode, useDesignLoopStore } from "./designLoop";

const authorize = <T>(operation: (accessToken: string) => Promise<T>) => operation("token");

function response(evaluatorId: string): TwinEvaluationResponsePayload {
  return {
    evaluation_run_id: "run-1",
    artifact_bundle_id: "bundle-1",
    artifact_bundle_hash: "b".repeat(64),
    twin_id: "twin-1",
    twin_version: 1,
    evaluator: {
      evaluator_id: evaluatorId,
      evaluator_version: "1",
      model_config_ref: "config",
      prompt_version_ref: "prompt",
    },
    findings: [],
    summary: "Clear enough.",
    evidence_gaps: [],
    is_simulated_feedback: true,
    completed_at: "2026-09-25T20:00:00Z",
    content_hash: "d".repeat(64),
    disclaimer: "Simulated feedback.",
  };
}

function run(
  id: string,
  responses: TwinEvaluationResponsePayload[] = [],
): DesignEvaluationRunPayload {
  return {
    schema_version: 1,
    id,
    project_id: "project-1",
    owner_user_id: "owner-1",
    design_version_id: "version-1",
    design_version_number: 1,
    design_content_hash: "a".repeat(64),
    alternative_id: "alternative-1",
    alternative_code: "DES-001",
    bundle: {},
    responses,
    started_at: "2026-09-25T19:59:00Z",
    completed_at: "2026-09-25T20:00:00Z",
    content_hash: "e".repeat(64),
  };
}

const application: InsightApplicationPayload = {
  id: "application-1",
  project_id: "project-1",
  owner_user_id: "owner-1",
  source_kind: "DESIGN_CRITIQUE",
  source_id: "CRQ-001:0",
  source_twin_id: "twin-1",
  text: "Keep the labels visible.",
  target: "DESIGN",
  target_field: null,
  target_version_id: "version-2",
  target_version_number: 2,
  target_code: "DRK-002",
  created_at: "2026-09-25T20:00:00Z",
  content_hash: "c".repeat(64),
};

function validation(
  decision: FindingValidationPayload["decision"],
  sequence: number,
): FindingValidationPayload {
  return {
    evaluation_run_id: "run-1",
    twin_id: "twin-1",
    finding_id: "UTF-001",
    sequence_number: sequence,
    project_id: "project-1",
    owner_user_id: "owner-1",
    decision,
    note: null,
    decided_at: "2026-09-26T10:00:00Z",
    content_hash: String(sequence).repeat(64),
  };
}

const comparison: DesignEvaluationComparisonPayload = {
  base_run_id: "run-1",
  head_run_id: "run-2",
  resolved: [],
  persisting: [],
  introduced: [],
  counts: { base: 1, head: 0, resolved: 0, persisting: 0, introduced: 0, dismissed: 1 },
};

function discussion(
  id: string,
  status: DesignDiscussionPayload["status"] = "OPEN",
  rounds = 1,
): DesignDiscussionPayload {
  return {
    id,
    project_id: "project-1",
    owner_user_id: "owner-1",
    design_version_id: "version-1",
    design_version_number: 1,
    design_content_hash: "a".repeat(64),
    alternative_id: "alternative-1",
    alternative_code: "DES-001",
    status,
    created_at: "2026-09-26T10:00:00Z",
    decided_at: status === "OPEN" ? null : "2026-09-26T11:00:00Z",
    max_rounds: 3,
    rounds: Array.from({ length: rounds }, (_item, index) => ({
      ordinal: index + 1,
      owner_note: null,
      created_at: "2026-09-26T10:00:00Z",
      content_hash: "f".repeat(64),
      statements: [],
      synthesis: {
        agreements: [],
        conflicts: [],
        proposals: [],
        questions_for_owner: [],
        model_generation_id: "generation-1",
      },
    })),
  };
}

function fakeApi(): DesignLoopApi {
  return {
    evaluate: vi.fn(async () => run("run-2")),
    runs: vi.fn(async () => [run("run-1")]),
    comparison: vi.fn(async () => null),
    regenerate: vi.fn(async () => ({ status: "CREATED", issue: null }) as never),
    applyInsight: vi.fn(async () => application),
    applications: vi.fn(async () => [application]),
    validations: vi.fn(async () => [validation("OWNER_CONFIRMED", 1)]),
    validate: vi.fn(async () => validation("OWNER_DISMISSED", 2)),
    discussions: vi.fn(async () => [discussion("discussion-1", "CLOSED")]),
    startDiscussion: vi.fn(async () => discussion("discussion-2")),
    nextDiscussionRound: vi.fn(async () => discussion("discussion-2", "OPEN", 2)),
    decideDiscussion: vi.fn(async () => discussion("discussion-2", "APPROVED", 2)),
  };
}

describe("designLoop store", () => {
  beforeEach(() => {
    setActivePinia(createPinia());
  });

  it("loads runs and applications, evaluates and prepends the new run", async () => {
    const store = useDesignLoopStore();
    const api = fakeApi();
    await store.load("project-1", authorize, api);
    expect(store.loaded).toBe(true);
    expect(store.runs.map((item) => item.id)).toEqual(["run-1"]);
    expect(store.applications).toEqual([application]);
    expect(store.validations).toEqual([validation("OWNER_CONFIRMED", 1)]);
    const created = await store.evaluate("project-1", "version-1", "a".repeat(64), authorize, api);
    expect(created.id).toBe("run-2");
    expect(store.runs.map((item) => item.id)).toEqual(["run-2", "run-1"]);
    expect(store.latestRun?.id).toBe("run-2");
    expect(runFindings(created)).toEqual([]);
    expect(vi.mocked(api.comparison)).toHaveBeenCalledTimes(2);
    expect(vi.mocked(api.evaluate).mock.calls[0]?.[1]).toEqual({
      design_version_id: "version-1",
      design_content_hash: "a".repeat(64),
      mode: "TWIN_REVIEW",
    });
  });

  it("records the evaluator availability and applied insights", async () => {
    const store = useDesignLoopStore();
    const api = fakeApi();
    vi.mocked(api.evaluate).mockRejectedValueOnce(
      new DesignLoopApiError("failed", {
        status: 503,
        code: "DESIGN_EVALUATOR_NOT_CONFIGURED",
        payload: null,
      }),
    );
    await expect(
      store.evaluate("project-1", "version-1", "a".repeat(64), authorize, api),
    ).rejects.toBeInstanceOf(DesignLoopApiError);
    expect(store.evaluatorUnavailable).toBe(true);
    expect(store.error).toBe("DESIGN_EVALUATOR_NOT_CONFIGURED");
    const applied = await store.apply(
      "project-1",
      {
        source_kind: "DESIGN_CRITIQUE",
        source_id: "CRQ-001:0",
        text: "Keep the labels visible.",
        target: "DESIGN",
      },
      authorize,
      api,
    );
    expect(applied).toEqual(application);
    expect(store.lastApplication).toEqual(application);
    expect(store.applications).toEqual([application]);
    expect(store.busy).toBeNull();
    const result = await store.regenerate("project-1", authorize, api);
    expect(result.status).toBe("CREATED");
    expect(store.lastApplication).toBeNull();
    store.reset("project-2");
    expect(store.runs).toEqual([]);
    expect(store.projectId).toBe("project-2");
  });

  it("tracks the reviewer availability per evaluation mode", async () => {
    const store = useDesignLoopStore();
    const api = fakeApi();
    await store.load("project-1", authorize, api);
    vi.mocked(api.evaluate).mockRejectedValueOnce(
      new DesignLoopApiError("failed", {
        status: 503,
        code: "DESIGN_REVIEWER_NOT_CONFIGURED",
        payload: null,
      }),
    );
    await expect(
      store.evaluate("project-1", "version-1", "a".repeat(64), authorize, api),
    ).rejects.toBeInstanceOf(DesignLoopApiError);
    expect(store.reviewerUnavailable).toBe(true);
    expect(store.evaluatorUnavailable).toBe(false);
    await store.evaluate("project-1", "version-1", "a".repeat(64), authorize, api, "STATIC_CHECK");
    expect(vi.mocked(api.evaluate).mock.calls[1]?.[1]).toMatchObject({ mode: "STATIC_CHECK" });
    expect(store.reviewerUnavailable).toBe(true);
    await store.evaluate(
      "project-1",
      "version-1",
      "a".repeat(64),
      authorize,
      api,
      "TWIN_REVIEW",
      "en-US",
    );
    expect(vi.mocked(api.evaluate).mock.calls[2]?.[1]).toEqual({
      design_version_id: "version-1",
      design_content_hash: "a".repeat(64),
      mode: "TWIN_REVIEW",
      locale: "en-US",
    });
    expect(store.reviewerUnavailable).toBe(false);
  });

  it("does not let an insight application clear a running evaluation", async () => {
    const store = useDesignLoopStore();
    const api = fakeApi();
    await store.load("project-1", authorize, api);
    let finish!: (value: DesignEvaluationRunPayload) => void;
    vi.mocked(api.evaluate).mockImplementationOnce(
      () =>
        new Promise<DesignEvaluationRunPayload>((resolve) => {
          finish = resolve;
        }),
    );
    const pending = store.evaluate("project-1", "version-1", "a".repeat(64), authorize, api);
    expect(store.busy).toBe("evaluate");
    await store.apply(
      "project-1",
      { source_kind: "SYNTHETIC_FINDING", source_id: "run:1", text: "Hint.", target: "DESIGN" },
      authorize,
      api,
    );
    expect(store.busy).toBe("evaluate");
    finish(run("run-3"));
    await pending;
    expect(store.busy).toBeNull();
  });

  it("names the kind of each run from its evaluator", () => {
    expect(runMode(run("run-1", [response("proposer-design-twin-review")]))).toBe("TWIN_REVIEW");
    expect(runMode(run("run-1", [response("s67-final-user-twin-evaluator")]))).toBe("STATIC_CHECK");
  });

  it("asks the twins about a changed element only when the scope is given", async () => {
    const store = useDesignLoopStore();
    const api = fakeApi();
    await store.load("project-1", authorize, api);
    const scope = { screen_code: "SCR-002", element_code: "ELM-012" };
    const created = await store.evaluate(
      "project-1",
      "version-1",
      "a".repeat(64),
      authorize,
      api,
      "TWIN_REVIEW",
      "it-IT",
      scope,
    );
    expect(vi.mocked(api.evaluate).mock.calls[0]?.[1]).toEqual({
      design_version_id: "version-1",
      design_content_hash: "a".repeat(64),
      mode: "TWIN_REVIEW",
      locale: "it-IT",
      scope,
    });
    expect(store.runs.map((item) => item.id)).toEqual([created.id, "run-1"]);
    await store.evaluate("project-1", "version-1", "a".repeat(64), authorize, api);
    expect(Object.keys(vi.mocked(api.evaluate).mock.calls[1]?.[1] ?? {})).toEqual([
      "design_version_id",
      "design_content_hash",
      "mode",
    ]);
    expect(store.busy).toBeNull();
  });

  it("reads the element that a twin gives to a finding", () => {
    const finding: SyntheticFindingPayload = {
      finding_id: "UTF-001",
      twin_id: "twin-1",
      twin_version: 1,
      artifact_id: "artifact-1",
      artifact_version: 1,
      location: "SCR-002 Riepilogo · ELM-012 Prenota",
      summary: "Il pulsante ora si vede bene.",
      rationale: "Al banco cerco subito l'azione.",
      criterion: "actionability",
      severity: "observation",
      epistemic_status: "MODEL_INFERRED",
      evidence_refs: [],
      confidence: 0.6,
      confidence_semantics: "MODEL_SELF_ASSESSMENT_UNLESS_CALIBRATED",
      recommended_action: "Prova con un blu più scuro.",
      requires_human_validation: true,
      model_config_ref: "config",
      prompt_version_ref: "prompt",
      is_simulated_feedback: true,
      content_hash: "f".repeat(64),
    };
    expect(findingElement({ ...finding, element_code: "ELM-012" })).toBe("ELM-012");
    expect(findingElement(finding)).toBeNull();
    expect(findingElement({ ...finding, element_code: 12 })).toBeNull();
  });

  it("records the owner's decision on a finding and reloads the comparison", async () => {
    const store = useDesignLoopStore();
    const api = fakeApi();
    await store.load("project-1", authorize, api);
    const key = findingKey("run-1", "twin-1", "UTF-001");
    expect(store.validationByKey[key]?.decision).toBe("OWNER_CONFIRMED");
    vi.mocked(api.comparison).mockResolvedValueOnce(comparison);
    const decided = await store.validate(
      "project-1",
      "run-1",
      { twin_id: "twin-1", finding_id: "UTF-001", decision: "OWNER_DISMISSED", note: "Not ours" },
      authorize,
      api,
    );
    expect(decided.decision).toBe("OWNER_DISMISSED");
    expect(vi.mocked(api.validate).mock.calls[0]?.slice(0, 3)).toEqual([
      "project-1",
      "run-1",
      { twin_id: "twin-1", finding_id: "UTF-001", decision: "OWNER_DISMISSED", note: "Not ours" },
    ]);
    expect(store.validations).toHaveLength(1);
    expect(store.validationByKey[key]?.decision).toBe("OWNER_DISMISSED");
    expect(store.comparison?.counts.dismissed).toBe(1);
    expect(store.validating).toBeNull();
    store.validations = [validation("OWNER_DISMISSED", 3), validation("OWNER_CONFIRMED", 4)];
    expect(store.validationByKey[key]?.decision).toBe("OWNER_CONFIRMED");
    vi.mocked(api.validate).mockRejectedValueOnce(
      new DesignLoopApiError("failed", {
        status: 404,
        code: "DESIGN_FINDING_NOT_FOUND",
        payload: null,
      }),
    );
    await expect(
      store.validate(
        "project-1",
        "run-1",
        { twin_id: "twin-1", finding_id: "UTF-009", decision: "OWNER_CONFIRMED", note: null },
        authorize,
        api,
      ),
    ).rejects.toBeInstanceOf(DesignLoopApiError);
    expect(store.validationError).toBe("DESIGN_FINDING_NOT_FOUND");
  });

  it("loads, starts, continues and decides the twin discussions", async () => {
    const store = useDesignLoopStore();
    const api = fakeApi();
    await store.loadDiscussions("project-1", authorize, api);
    expect(store.projectId).toBe("project-1");
    expect(store.latestDiscussion?.id).toBe("discussion-1");
    const started = await store.startDiscussion(
      "project-1",
      { design_version_id: "version-1", design_content_hash: "a".repeat(64), locale: "it-IT" },
      authorize,
      api,
    );
    expect(started.id).toBe("discussion-2");
    expect(store.discussions.map((item) => item.id)).toEqual(["discussion-2", "discussion-1"]);
    await store.nextDiscussionRound(
      "project-1",
      "discussion-2",
      { expected_round_count: 1, owner_note: "Focus on speed" },
      authorize,
      api,
    );
    expect(store.latestDiscussion?.rounds).toHaveLength(2);
    await store.decideDiscussion("project-1", "discussion-2", "APPROVE", authorize, api);
    expect(vi.mocked(api.decideDiscussion).mock.calls[0]?.slice(0, 3)).toEqual([
      "project-1",
      "discussion-2",
      { action: "APPROVE" },
    ]);
    expect(store.discussions.map((item) => [item.id, item.status])).toEqual([
      ["discussion-2", "APPROVED"],
      ["discussion-1", "CLOSED"],
    ]);
    expect(store.discussionBusy).toBeNull();
    expect(store.isBusy).toBe(false);
  });

  it("marks the store busy while the twins discuss and records the failure code", async () => {
    const store = useDesignLoopStore();
    const api = fakeApi();
    await store.loadDiscussions("project-1", authorize, api);
    let fail!: (error: unknown) => void;
    vi.mocked(api.startDiscussion).mockImplementationOnce(
      () =>
        new Promise<DesignDiscussionPayload>((_resolve, reject) => {
          fail = reject;
        }),
    );
    const pending = store.startDiscussion(
      "project-1",
      { design_version_id: "version-1", design_content_hash: "a".repeat(64) },
      authorize,
      api,
    );
    expect(store.discussionBusy).toBe("start");
    expect(store.isBusy).toBe(true);
    fail(
      new DesignLoopApiError("failed", {
        status: 503,
        code: "DESIGN_DISCUSSION_NOT_CONFIGURED",
        payload: null,
      }),
    );
    await expect(pending).rejects.toBeInstanceOf(DesignLoopApiError);
    expect(store.discussionError).toBe("DESIGN_DISCUSSION_NOT_CONFIGURED");
    expect(store.error).toBeNull();
    expect(store.isBusy).toBe(false);
  });
});
