import { createPinia, setActivePinia } from "pinia";
import { flushPromises, mount } from "@vue/test-utils";
import { beforeEach, describe, expect, it, vi } from "vitest";

import type { FinalizationApi } from "@/api/finalization";
import { createAppI18n } from "@/i18n";
import { useUserModelingStore } from "@/stores/userModeling";
import { expectAccessible } from "@/test/axe";
import type {
  EvaluationAggregationPayload,
  SyntheticEvaluationRunPayload,
  SyntheticFindingPayload,
} from "@/types/finalization";
import type { UserTwinVersionPayload } from "@/types/userModeling";
import ProjectSyntheticEvaluation from "./ProjectSyntheticEvaluation.vue";

const run: SyntheticEvaluationRunPayload = {
  id: "run-1",
  project_id: "project-1",
  workflow_run_id: "workflow-1",
  owner_user_id: "owner-1",
  artifact_bundle_id: "bundle-1",
  artifact_bundle_hash: "a".repeat(64),
  status: "COMPLETED",
  response_count: 2,
  finding_count: 2,
  started_at: "2026-09-23T10:00:00Z",
  completed_at: "2026-09-23T10:02:00Z",
  content_hash: "b".repeat(64),
  simulated_feedback: true,
};

function finding(id: string, twinId: string, severity: SyntheticFindingPayload["severity"]) {
  return {
    finding_id: id,
    twin_id: twinId,
    twin_version: 1,
    artifact_id: "artifact-1",
    artifact_version: 1,
    location: "SCR-001, campo importo",
    summary: `Spunto ${id}`,
    rationale: "Nel mio ruolo devo fare in fretta.",
    criterion: "comprehensibility",
    severity,
    epistemic_status: "MODEL_INFERRED",
    evidence_refs: ["artifact:artifact-1:v1"],
    confidence: 0.7,
    recommended_action: "Aggiungere un esempio accanto al campo.",
    requires_human_validation: true,
    model_config_ref: "c".repeat(64),
    prompt_version_ref: "s18-proposer-twin-evaluation-v1",
    origin: "MODEL_GENERATED",
  } satisfies SyntheticFindingPayload;
}

const first = finding("UTF-001", "twin-1", "moderate");
const second = finding("UTF-001", "twin-2", "major");
const findings = [first, second];

const aggregation: EvaluationAggregationPayload = {
  evaluation_run_id: "run-1",
  evaluation_run_hash: "b".repeat(64),
  shared_findings: [
    { group_id: "group-1", comparison_key: ["artifact-1"], findings: [first, second] },
  ],
  role_specific_findings: [],
  direct_conflicts: [
    {
      declaration: {
        conflict_id: "conflict-1",
        finding_ids: ["twin:twin-1:v1:UTF-001", "twin:twin-2:v1:UTF-001"],
        summary: "I twin chiedono azioni diverse sullo stesso campo.",
        owner_decision_question: "Quale formato preferisci mostrare?",
      },
      findings: [first, second],
    },
  ],
  unresolved_trade_offs: [],
  evidence_gaps: [
    { twin_id: "twin-2", twin_version: 1, gap: "Non vedo la schermata del risultato." },
  ],
  human_validation_questions: [
    { question_id: "q-1", related_finding_ids: [], question: "Il formato dell'importo è chiaro?" },
  ],
  aggregation_policy: "EXACT_MATCH_PLUS_EXPLICIT_CONFLICT_DECLARATIONS",
  independent_human_sample_count: 0,
  content_hash: "d".repeat(64),
  disclaimer: "Simulated feedback.",
  is_empirical_evidence: false,
};

function fakeApi(existing: SyntheticEvaluationRunPayload[]): FinalizationApi {
  return {
    evaluationRun: vi.fn().mockResolvedValue(run),
    findings: vi.fn().mockResolvedValue(findings),
    aggregation: vi.fn().mockResolvedValue(aggregation),
    evaluationRuns: vi.fn().mockResolvedValue(existing),
    createEvaluationRun: vi.fn().mockResolvedValue({
      status: "SYNTHETIC_EVALUATION_RECORDED",
      snapshot: run,
      findings,
      aggregation,
    }),
  } as unknown as FinalizationApi;
}

function twin(id: string, name: string) {
  return {
    id: `${id}-v1`,
    twin_id: id,
    version_number: 1,
    profile: { name },
  } as unknown as UserTwinVersionPayload;
}

function mountPanel(api: FinalizationApi) {
  return mount(ProjectSyntheticEvaluation, {
    props: {
      projectId: "project-1",
      executionId: "execution-1",
      api,
      authorize: <T>(operation: (token: string) => Promise<T>) => operation("token"),
    },
    global: { plugins: [createAppI18n("it")] },
  });
}

describe("project synthetic evaluation", () => {
  beforeEach(() => {
    setActivePinia(createPinia());
    const modeling = useUserModelingStore();
    modeling.twinVersions = [twin("twin-1", "Marta Rinaldi"), twin("twin-2", "Luca Neri")];
  });

  it("asks the twins to try the prototype and groups the findings per twin", async () => {
    const api = fakeApi([]);
    const wrapper = mountPanel(api);
    await flushPromises();

    expect(wrapper.get("[data-testid='evaluation-empty']").text()).toBe(
      "Nessuna valutazione ancora.",
    );
    await wrapper.get("[data-testid='evaluation-ask']").trigger("click");
    await flushPromises();

    expect(api.createEvaluationRun).toHaveBeenCalledWith(
      "project-1",
      { execution_id: "execution-1" },
      "token",
    );
    const groups = wrapper.findAll("[data-testid='evaluation-twin']");
    expect(groups).toHaveLength(2);
    expect(groups[0]?.text()).toContain("Marta Rinaldi");
    expect(groups[1]?.text()).toContain("Luca Neri");
    expect(wrapper.findAll("[data-testid='evaluation-finding']")).toHaveLength(2);
    expect(wrapper.text()).toContain("Moderato");
    expect(wrapper.text()).toContain("Importante");
    expect(wrapper.text()).toContain("Comprensibilità");
    expect(wrapper.text()).toContain("confidenza 70%");
    expect(wrapper.findAll("[data-testid='evaluation-conflict']")).toHaveLength(1);
    expect(wrapper.text()).toContain("Quale formato preferisci mostrare?");
    expect(wrapper.text()).toContain("Luca Neri: Non vedo la schermata del risultato.");
    expect(wrapper.get("[data-testid='evaluation-meta']").text()).toContain("2 twin, 2 spunti");
    expect(wrapper.get("[data-testid='evaluation-ask']").text()).toBe("Chiedi di nuovo ai twin");
  });

  it("loads the latest recorded run on mount", async () => {
    const api = fakeApi([run]);
    const wrapper = mountPanel(api);
    await flushPromises();

    expect(api.evaluationRun).toHaveBeenCalledWith("run-1", "token");
    expect(wrapper.findAll("[data-testid='evaluation-finding']")).toHaveLength(2);
    expect(wrapper.find("[data-testid='evaluation-empty']").exists()).toBe(false);
  });

  it("shows the failure of a request", async () => {
    const api = fakeApi([]);
    vi.mocked(api.createEvaluationRun).mockRejectedValue(new Error("NO_APPROVED_USER_TWINS"));
    const wrapper = mountPanel(api);
    await flushPromises();
    await wrapper.get("[data-testid='evaluation-ask']").trigger("click");
    await flushPromises();
    expect(wrapper.get("[role='alert']").text()).toBe("NO_APPROVED_USER_TWINS");
  });

  it("has no axe violations", async () => {
    const wrapper = mountPanel(fakeApi([run]));
    await flushPromises();
    await expectAccessible(wrapper.element);
  });
});
