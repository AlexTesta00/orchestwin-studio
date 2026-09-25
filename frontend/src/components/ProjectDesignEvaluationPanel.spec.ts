import { createPinia, setActivePinia } from "pinia";
import { flushPromises, mount } from "@vue/test-utils";
import { beforeEach, describe, expect, it, vi } from "vitest";

import type { DesignLoopApi } from "@/api/designLoop";
import { DesignLoopApiError } from "@/api/designLoop";
import { expectAccessible } from "@/test/axe";
import type {
  DesignEvaluationComparisonPayload,
  DesignEvaluationRunPayload,
  SyntheticFindingPayload,
} from "@/types/designLoop";
import ProjectDesignEvaluationPanel from "./ProjectDesignEvaluationPanel.vue";

const authorize = <T>(operation: (accessToken: string) => Promise<T>) => operation("token");

function finding(id: string, summary: string): SyntheticFindingPayload {
  return {
    finding_id: id,
    twin_id: "twin-1",
    twin_version: 1,
    artifact_id: "prototype-1",
    artifact_version: 1,
    location: "SCR-001 Guest name",
    summary,
    rationale: "The receptionist types under time pressure.",
    criterion: "comprehensibility",
    severity: "major",
    epistemic_status: "MODEL_INFERRED",
    evidence_refs: ["artifact:prototype-1:v1"],
    confidence: 0.7,
    confidence_semantics: "MODEL_SELF_ASSESSMENT_UNLESS_CALIBRATED",
    recommended_action: "Add a format hint.",
    requires_human_validation: true,
    model_config_ref: "config",
    prompt_version_ref: "prompt",
    is_simulated_feedback: true,
    content_hash: id.repeat(16).slice(0, 64),
  };
}

function run(id: string, findings: SyntheticFindingPayload[]): DesignEvaluationRunPayload {
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
    responses: [
      {
        evaluation_run_id: id,
        artifact_bundle_id: "bundle-1",
        artifact_bundle_hash: "b".repeat(64),
        twin_id: "twin-1",
        twin_version: 1,
        evaluator: {
          evaluator_id: "evaluator",
          evaluator_version: "1",
          model_config_ref: "config",
          prompt_version_ref: "prompt",
        },
        findings,
        summary: "The flow is short but the date format is unclear.",
        evidence_gaps: [],
        is_simulated_feedback: true,
        completed_at: "2026-09-25T20:00:00Z",
        content_hash: "d".repeat(64),
        disclaimer: "Simulated feedback.",
      },
    ],
    started_at: "2026-09-25T19:59:00Z",
    completed_at: "2026-09-25T20:00:00Z",
    content_hash: "e".repeat(64),
  };
}

function fakeApi(
  runs: DesignEvaluationRunPayload[],
  comparison: DesignEvaluationComparisonPayload | null = null,
): DesignLoopApi {
  return {
    evaluate: vi.fn(async () => run("run-2", [finding("UTF-002", "The date fields need a hint.")])),
    runs: vi.fn(async () => runs),
    comparison: vi.fn(async () => comparison),
    regenerate: vi.fn(),
    applyInsight: vi.fn(),
    applications: vi.fn(async () => []),
  };
}

describe("ProjectDesignEvaluationPanel", () => {
  beforeEach(() => {
    setActivePinia(createPinia());
  });

  it("lists the twins' findings with apply menus and evaluates on demand", async () => {
    const api = fakeApi([
      run("run-1", [finding("UTF-001", "The guest name lacks a format hint.")]),
    ]);
    const wrapper = mount(ProjectDesignEvaluationPanel, {
      props: {
        projectId: "project-1",
        designVersionId: "version-1",
        designContentHash: "a".repeat(64),
        twinNames: { "twin-1": "Marta Rinaldi" },
        locale: "it",
        authorize,
        api,
      },
    });
    await flushPromises();
    expect(wrapper.findAll('[data-testid="design-evaluation-run"]')).toHaveLength(1);
    expect(wrapper.text()).toContain("Marta Rinaldi");
    expect(wrapper.text()).toContain("The guest name lacks a format hint.");
    expect(wrapper.text()).toContain("Importante");
    expect(wrapper.text()).toContain("Comprensibilità");
    expect(wrapper.findAll('[data-testid="insight-apply-menu"]')).toHaveLength(1);
    await wrapper.get('[data-testid="design-evaluate"]').trigger("click");
    await flushPromises();
    expect(vi.mocked(api.evaluate).mock.calls[0]?.[1]).toEqual({
      design_version_id: "version-1",
      design_content_hash: "a".repeat(64),
    });
    expect(wrapper.findAll('[data-testid="design-evaluation-run"]')).toHaveLength(2);
    expect(wrapper.emitted("evaluated")).toHaveLength(1);
    await expectAccessible(wrapper.element);
  });

  it("shows the comparison counts and the evaluator notice", async () => {
    const resolved = finding("UTF-001", "The guest name lacks a format hint.");
    const api = fakeApi([run("run-2", []), run("run-1", [resolved])], {
      base_run_id: "run-1",
      head_run_id: "run-2",
      resolved: [resolved],
      persisting: [],
      introduced: [],
      counts: { base: 1, head: 0, resolved: 1, persisting: 0, introduced: 0 },
    });
    vi.mocked(api.evaluate).mockRejectedValueOnce(
      new DesignLoopApiError("failed", {
        status: 503,
        code: "DESIGN_EVALUATOR_NOT_CONFIGURED",
        payload: null,
      }),
    );
    const wrapper = mount(ProjectDesignEvaluationPanel, {
      props: {
        projectId: "project-1",
        designVersionId: "version-1",
        designContentHash: "a".repeat(64),
        authorize,
        api,
      },
    });
    await flushPromises();
    const comparison = wrapper.get('[data-testid="design-evaluation-comparison"]');
    expect(comparison.text()).toContain("1 resolved");
    expect(comparison.text()).toContain("The guest name lacks a format hint.");
    expect(wrapper.text()).toContain("No findings: the twin had nothing to object.");
    await wrapper.get('[data-testid="design-evaluate"]').trigger("click");
    await flushPromises();
    expect(wrapper.get('[role="status"]').text()).toContain("local evaluator is not configured");
  });
});
