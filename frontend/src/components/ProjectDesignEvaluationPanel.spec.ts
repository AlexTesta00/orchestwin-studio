import { createPinia, setActivePinia } from "pinia";
import { flushPromises, mount } from "@vue/test-utils";
import { beforeEach, describe, expect, it, vi } from "vitest";

import type { DesignLoopApi } from "@/api/designLoop";
import { DesignLoopApiError } from "@/api/designLoop";
import { expectAccessible } from "@/test/axe";
import type {
  DesignEvaluationComparisonPayload,
  DesignEvaluationRunPayload,
  FindingValidationPayload,
  InsightApplicationPayload,
  SyntheticFindingPayload,
} from "@/types/designLoop";
import ProjectDesignEvaluationPanel from "./ProjectDesignEvaluationPanel.vue";

const authorize = <T>(operation: (accessToken: string) => Promise<T>) => operation("token");
const TWIN_REVIEW = "proposer-design-twin-review";

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

function run(
  id: string,
  findings: SyntheticFindingPayload[],
  evaluatorId = TWIN_REVIEW,
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
    responses: [
      {
        evaluation_run_id: id,
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

function validation(
  decision: FindingValidationPayload["decision"],
  note: string | null = null,
  sequence = 1,
): FindingValidationPayload {
  return {
    evaluation_run_id: "run-1",
    twin_id: "twin-1",
    finding_id: "UTF-001",
    sequence_number: sequence,
    project_id: "project-1",
    owner_user_id: "owner-1",
    decision,
    note,
    decided_at: "2026-09-26T10:00:00Z",
    content_hash: "f".repeat(64),
  };
}

function comparison(
  counts: Partial<DesignEvaluationComparisonPayload["counts"]> = {},
  resolved: SyntheticFindingPayload[] = [],
): DesignEvaluationComparisonPayload {
  return {
    base_run_id: "run-1",
    head_run_id: "run-2",
    resolved,
    persisting: [],
    introduced: [],
    counts: {
      base: 1,
      head: 0,
      resolved: resolved.length,
      persisting: 0,
      introduced: 0,
      dismissed: 0,
      ...counts,
    },
  };
}

function fakeApi(
  runs: DesignEvaluationRunPayload[],
  comparisonValue: DesignEvaluationComparisonPayload | null = null,
  validations: FindingValidationPayload[] = [],
): DesignLoopApi {
  return {
    evaluate: vi.fn(async () => run("run-2", [finding("UTF-002", "The date fields need a hint.")])),
    runs: vi.fn(async () => runs),
    comparison: vi.fn(async () => comparisonValue),
    regenerate: vi.fn(),
    applyInsight: vi.fn(),
    applications: vi.fn(async () => []),
    validations: vi.fn(async () => validations),
    validate: vi.fn(async (_project, _run, body) =>
      validation(body.decision, body.note, validations.length + 2),
    ),
    discussions: vi.fn(async () => []),
    startDiscussion: vi.fn(),
    nextDiscussionRound: vi.fn(),
    decideDiscussion: vi.fn(),
  };
}

function apiError(status: number, code: string): DesignLoopApiError {
  return new DesignLoopApiError("failed", { status, code, payload: null });
}

function mountPanel(api: DesignLoopApi, locale: "en" | "it" = "en") {
  return mount(ProjectDesignEvaluationPanel, {
    props: {
      projectId: "project-1",
      designVersionId: "version-1",
      designContentHash: "a".repeat(64),
      twinNames: { "twin-1": "Marta Rinaldi" },
      locale,
      authorize,
      api,
    },
  });
}

describe("ProjectDesignEvaluationPanel", () => {
  beforeEach(() => {
    setActivePinia(createPinia());
  });

  it("lists the twins' findings with apply menus and evaluates on demand", async () => {
    const api = fakeApi([
      run("run-1", [finding("UTF-001", "The guest name lacks a format hint.")]),
    ]);
    const wrapper = mountPanel(api, "it");
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
      mode: "TWIN_REVIEW",
      locale: "it-IT",
    });
    expect(wrapper.findAll('[data-testid="design-evaluation-run"]')).toHaveLength(2);
    expect(wrapper.emitted("evaluated")).toHaveLength(1);
    await expectAccessible(wrapper.element);
  });

  it("asks for the evaluation in the language of the interface", async () => {
    const api = fakeApi([]);
    const wrapper = mountPanel(api);
    await flushPromises();
    await wrapper.get('[data-testid="design-evaluate"]').trigger("click");
    await flushPromises();
    await wrapper.get('[data-testid="design-static-check"]').trigger("click");
    await flushPromises();
    expect(vi.mocked(api.evaluate).mock.calls.map((call) => call[1])).toEqual([
      {
        design_version_id: "version-1",
        design_content_hash: "a".repeat(64),
        mode: "TWIN_REVIEW",
        locale: "en-US",
      },
      {
        design_version_id: "version-1",
        design_content_hash: "a".repeat(64),
        mode: "STATIC_CHECK",
        locale: "en-US",
      },
    ]);
  });

  it("runs the static accessibility check and labels every run with its kind", async () => {
    const api = fakeApi([run("run-1", [finding("UTF-001", "The guest name lacks a hint.")])]);
    vi.mocked(api.evaluate).mockResolvedValueOnce(run("run-2", [], "s67-static-check"));
    const wrapper = mountPanel(api, "it");
    await flushPromises();
    expect(wrapper.get('[data-testid="design-static-check"]').text()).toBe(
      "Controllo statico di accessibilità",
    );
    await wrapper.get('[data-testid="design-static-check"]').trigger("click");
    await flushPromises();
    expect(vi.mocked(api.evaluate).mock.calls[0]?.[1]).toMatchObject({
      mode: "STATIC_CHECK",
      locale: "it-IT",
    });
    const kinds = wrapper
      .findAll('[data-testid="design-evaluation-kind"]')
      .map((item) => item.text());
    expect(kinds).toEqual(["Controllo statico di accessibilità", "Revisione dei twin"]);
    expect(
      wrapper
        .findAll('[data-testid="design-evaluation-run"]')
        .map((item) => item.attributes("data-mode")),
    ).toEqual(["STATIC_CHECK", "TWIN_REVIEW"]);
  });

  it("shows the comparison counts, the dismissed findings and the evaluator notice", async () => {
    const resolved = finding("UTF-001", "The guest name lacks a format hint.");
    const api = fakeApi(
      [run("run-2", []), run("run-1", [resolved])],
      comparison({ resolved: 1, dismissed: 2 }, [resolved]),
    );
    vi.mocked(api.evaluate).mockRejectedValueOnce(apiError(503, "DESIGN_EVALUATOR_NOT_CONFIGURED"));
    const wrapper = mountPanel(api);
    await flushPromises();
    const panel = wrapper.get('[data-testid="design-evaluation-comparison"]');
    expect(panel.text()).toContain("Compared with the previous twin review");
    expect(panel.text()).toContain("1 resolved");
    expect(panel.text()).toContain("2 marked not relevant by you");
    expect(panel.text()).toContain("The guest name lacks a format hint.");
    expect(wrapper.text()).toContain("No findings: the twin had nothing to object.");
    await wrapper.get('[data-testid="design-static-check"]').trigger("click");
    await flushPromises();
    expect(wrapper.get('[data-testid="design-evaluator-unavailable"]').text()).toContain(
      "local evaluator is not configured",
    );
    expect(wrapper.find('[data-testid="design-evaluation-error"]').exists()).toBe(false);
  });

  it("hides the dismissed count when no finding was set aside", async () => {
    const api = fakeApi([run("run-2", []), run("run-1", [])], comparison());
    const wrapper = mountPanel(api);
    await flushPromises();
    expect(wrapper.get('[data-testid="design-evaluation-comparison"]').text()).not.toContain(
      "not relevant",
    );
  });

  it("explains the reviewer, the evaluator and the static check failures in plain words", async () => {
    const api = fakeApi([]);
    vi.mocked(api.evaluate)
      .mockRejectedValueOnce(apiError(503, "DESIGN_REVIEWER_NOT_CONFIGURED"))
      .mockRejectedValueOnce(apiError(409, "STATIC_CHECK_NOT_APPLICABLE"))
      .mockRejectedValueOnce(apiError(502, "DESIGN_EVALUATION_FAILED"));
    const wrapper = mountPanel(api, "it");
    await flushPromises();
    await wrapper.get('[data-testid="design-evaluate"]').trigger("click");
    await flushPromises();
    expect(wrapper.get('[data-testid="design-reviewer-unavailable"]').text()).toContain(
      "Il modello linguistico che interpreta i twin non è collegato",
    );
    await wrapper.get('[data-testid="design-static-check"]').trigger("click");
    await flushPromises();
    expect(wrapper.get('[data-testid="design-static-not-applicable"]').text()).toContain(
      "almeno una schermata con un campo e un pulsante",
    );
    expect(wrapper.text()).not.toContain("STATIC_CHECK_NOT_APPLICABLE");
    await wrapper.get('[data-testid="design-evaluate"]').trigger("click");
    await flushPromises();
    const error = wrapper.get('[data-testid="design-evaluation-error"]');
    expect(error.text()).toContain("La valutazione non è stata completata.");
    expect(error.get("details code").text()).toBe("DESIGN_EVALUATION_FAILED");
    await expectAccessible(wrapper.element);
  });

  it("records the owner's decision on a finding with a note and reloads the comparison", async () => {
    const api = fakeApi([run("run-1", [finding("UTF-001", "The guest name lacks a hint.")])]);
    const wrapper = mountPanel(api, "it");
    await flushPromises();
    const card = () => wrapper.get('[data-testid="design-finding"]');
    expect(card().attributes("data-decision")).toBe("NONE");
    expect(card().get('[data-testid="finding-confirm"]').text()).toBe("Confermo");
    expect(card().get('[data-testid="finding-dismiss"]').text()).toBe("Non pertinente");
    await card().get('[data-testid="finding-note"]').setValue("  Fuori   dal perimetro ");
    await card().get('[data-testid="finding-dismiss"]').trigger("click");
    await flushPromises();
    expect(vi.mocked(api.validate).mock.calls[0]?.slice(1, 3)).toEqual([
      "run-1",
      {
        twin_id: "twin-1",
        finding_id: "UTF-001",
        decision: "OWNER_DISMISSED",
        note: "Fuori dal perimetro",
      },
    ]);
    expect(vi.mocked(api.comparison)).toHaveBeenCalledTimes(2);
    expect(card().attributes("data-decision")).toBe("OWNER_DISMISSED");
    expect(card().get('[data-testid="finding-decision-chip"]').text()).toBe(
      "Segnata come non pertinente",
    );
    expect(card().classes()).toContain("border-dashed");
    expect(card().find('[data-testid="insight-apply-menu"]').exists()).toBe(false);
    expect(card().get('[data-testid="finding-dismissed-hint"]').text()).toContain(
      "non viene portata nel progetto",
    );
    expect(card().text()).toContain("La tua nota: Fuori dal perimetro");
    expect((card().get('[data-testid="finding-note"]').element as HTMLInputElement).value).toBe("");
    expect(card().get('[data-testid="finding-dismiss"]').attributes("aria-pressed")).toBe("true");
    expect(wrapper.text()).not.toMatch(/validat/i);
    await card().get('[data-testid="finding-confirm"]').trigger("click");
    await flushPromises();
    expect(vi.mocked(api.validate).mock.calls[1]?.[2]).toMatchObject({
      decision: "OWNER_CONFIRMED",
      note: null,
    });
    expect(card().get('[data-testid="finding-decision-chip"]').text()).toBe("Confermata da te");
    expect(card().find('[data-testid="insight-apply-menu"]').exists()).toBe(true);
    await expectAccessible(wrapper.element);
  });

  it("shows the stored decisions and explains a finding that no longer exists", async () => {
    const api = fakeApi(
      [run("run-1", [finding("UTF-001", "The guest name lacks a hint.")])],
      null,
      [validation("OWNER_CONFIRMED", "Seen in the interviews")],
    );
    vi.mocked(api.validate).mockRejectedValueOnce(apiError(404, "DESIGN_FINDING_NOT_FOUND"));
    const wrapper = mountPanel(api);
    await flushPromises();
    const card = wrapper.get('[data-testid="design-finding"]');
    expect(card.get('[data-testid="finding-decision-chip"]').text()).toBe("Confirmed by you");
    expect(card.text()).toContain("Your note: Seen in the interviews");
    await card.get('[data-testid="finding-dismiss"]').trigger("click");
    await flushPromises();
    const error = wrapper.get('[data-testid="finding-decision-error"]');
    expect(error.text()).toContain("This finding is no longer available. Reload the page.");
    expect(error.get("details code").text()).toBe("DESIGN_FINDING_NOT_FOUND");
    expect(card.attributes("data-decision")).toBe("OWNER_CONFIRMED");
  });

  it("re-emits the insights brought into the project", async () => {
    const api = fakeApi([run("run-1", [finding("UTF-001", "The guest name lacks a hint.")])]);
    const application: InsightApplicationPayload = {
      id: "application-1",
      project_id: "project-1",
      owner_user_id: "owner-1",
      source_kind: "SYNTHETIC_FINDING",
      source_id: "run:run-1:twin-1:UTF-001",
      source_twin_id: "twin-1",
      text: "The guest name lacks a hint.",
      target: "REQUIREMENTS",
      target_field: null,
      target_version_id: "requirements-2",
      target_version_number: 2,
      target_code: "REQ-004",
      created_at: "2026-09-26T10:00:00Z",
      content_hash: "c".repeat(64),
    };
    vi.mocked(api.applyInsight).mockResolvedValueOnce(application);
    const wrapper = mountPanel(api);
    await flushPromises();
    await wrapper.get('[data-testid="insight-apply-requirements"]').trigger("click");
    await flushPromises();
    expect(vi.mocked(api.applyInsight).mock.calls[0]?.[1]).toMatchObject({
      source_kind: "SYNTHETIC_FINDING",
      source_id: "run:run-1:twin-1:UTF-001",
    });
    expect(wrapper.emitted("applied")).toEqual([[application]]);
  });
});
