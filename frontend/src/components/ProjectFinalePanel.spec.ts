import { createPinia, setActivePinia } from "pinia";
import { flushPromises, mount } from "@vue/test-utils";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import type { FinalizationApi } from "@/api/finalization";
import { createAppI18n } from "@/i18n";
import { expectAccessible } from "@/test/axe";
import type {
  FinalApprovalPayload,
  FinalExportPayload,
  FinalReviewPayload,
} from "@/types/finalization";
import ProjectFinalePanel, { type FinaleRecapRow } from "./ProjectFinalePanel.vue";

function review(readyForGate8 = true): FinalReviewPayload {
  return {
    review_id: "review-1",
    project_id: "project-1",
    workflow_run_id: "run-1",
    owner_user_id: "owner-1",
    version_number: 2,
    parent_review_id: null,
    parent_content_hash: null,
    workflow_state_version: 8,
    checks: [
      {
        check_id: "check-dod",
        kind: "DEFINITION_OF_DONE",
        status: readyForGate8 ? "SATISFIED" : "NOT_SATISFIED",
        summary: "La definizione di fatto è completa.",
        evidence_refs: ["dod:1"],
        blocking: true,
        blocks_gate8: !readyForGate8,
      },
    ],
    unresolved_issues: [],
    accepted_limitations: [],
    latest_execution_attempt_id: "execution-1",
    latest_evaluation_run_id: null,
    evaluation_aggregation_hash: null,
    capability_status: "VALIDATED_LEVEL_D",
    human_validation_status: "NOT_RECORDED",
    created_at: "2026-09-22T10:00:00Z",
    content_hash: "c".repeat(64),
    ready_for_gate8: readyForGate8,
    blocking_check_ids: readyForGate8 ? [] : ["check-dod"],
    blocking_issue_ids: [],
    owner_approval_is_empirical_validation: false,
  };
}

function approval(status: FinalApprovalPayload["status"]): FinalApprovalPayload {
  return {
    gate_id: "gate-8",
    review_id: "review-1",
    review_version: 2,
    review_hash: "c".repeat(64),
    status,
    updated_at: "2026-09-22T10:05:00Z",
  };
}

const bundle: FinalExportPayload = {
  id: "export-1",
  project_id: "project-1",
  workflow_run_id: "run-1",
  owner_user_id: "owner-1",
  manifest_id: "manifest-1",
  manifest_hash: "d".repeat(64),
  archive_hash: "e".repeat(64),
  archive_size_bytes: 20480,
  created_at: "2026-09-22T10:10:00Z",
};

const recap: FinaleRecapRow[] = [
  { key: "brief", label: "Brief", outcome: "approved", decisions: 1, max: 4 },
  { key: "team", label: "Squadra", outcome: "approved", decisions: 2, max: 4 },
  { key: "sources", label: "Sorgenti", outcome: "generated", decisions: null, max: null },
  { key: "execution", label: "Esecuzione", outcome: "approved", decisions: null, max: null },
];

function fakeApi(current: FinalReviewPayload): FinalizationApi {
  return {
    evaluationRun: vi.fn(),
    findings: vi.fn(),
    aggregation: vi.fn(),
    finalReviews: vi.fn().mockResolvedValue([current]),
    submitFinalReview: vi.fn().mockResolvedValue(approval("PENDING_APPROVAL")),
    decideFinalApproval: vi.fn().mockResolvedValue(approval("APPROVED")),
    createExport: vi.fn().mockResolvedValue(bundle),
    exportBundle: vi.fn().mockResolvedValue(bundle),
    downloadExport: vi
      .fn()
      .mockResolvedValue({ blob: new Blob(["zip"]), filename: "project.zip", etag: null }),
  } as unknown as FinalizationApi;
}

function mountPanel(api: FinalizationApi) {
  return mount(ProjectFinalePanel, {
    props: {
      projectId: "project-1",
      recap,
      api,
      authorize: <T>(operation: (token: string) => Promise<T>) => operation("token"),
    },
    global: { plugins: [createAppI18n("it")] },
  });
}

describe("project finale panel", () => {
  beforeEach(() => {
    setActivePinia(createPinia());
  });

  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it("walks from the final review to the downloadable archive", async () => {
    const api = fakeApi(review());
    const wrapper = mountPanel(api);
    await flushPromises();

    expect(wrapper.get("h2").text()).toBe("Progetto completato");
    expect(wrapper.findAll("[data-testid='finale-recap-row']")).toHaveLength(4);
    expect(wrapper.text()).toContain("1 di 4");
    expect(wrapper.text()).toContain("Generato");

    await wrapper.get("[data-testid='finale-submit']").trigger("click");
    await flushPromises();
    expect(vi.mocked(api.submitFinalReview).mock.calls[0]?.[1]).toMatchObject({
      expected_version: 2,
      expected_content_hash: "c".repeat(64),
    });

    await wrapper.get("[data-testid='finale-approve']").trigger("click");
    await flushPromises();
    const decision = vi.mocked(api.decideFinalApproval).mock.calls[0];
    expect(decision?.[0]).toBe("gate-8");
    expect(decision?.[1]).toMatchObject({ action: "APPROVE", expected_review_id: "review-1" });

    await wrapper.get("[data-testid='finale-export']").trigger("click");
    await flushPromises();
    expect(vi.mocked(api.createExport).mock.calls[0]?.[1]).toMatchObject({
      final_review_id: "review-1",
      final_approval_gate_id: "gate-8",
      final_approval_event_id: decision?.[1].event_id,
    });

    const createObjectURL = vi.fn().mockReturnValue("blob:archive");
    vi.stubGlobal("URL", { ...URL, createObjectURL, revokeObjectURL: vi.fn() });
    const click = vi.spyOn(HTMLAnchorElement.prototype, "click").mockImplementation(() => {});
    await wrapper.get("[data-testid='finale-download']").trigger("click");
    await flushPromises();
    expect(api.downloadExport).toHaveBeenCalledWith("export-1", "token");
    expect(click).toHaveBeenCalledTimes(1);
    await wrapper.get("[data-testid='evidence-toggle']").trigger("click");
    expect(wrapper.text()).toContain("20 KB");
  });

  it("lists the blocking checks and requires a reason for a revision request", async () => {
    const api = fakeApi(review(false));
    const wrapper = mountPanel(api);
    await flushPromises();

    expect(wrapper.text()).toContain("La definizione di fatto è completa.");
    expect(wrapper.find("[data-testid='finale-submit']").exists()).toBe(false);
    expect(wrapper.get("[data-testid='finale-reload']").text()).toBe("Aggiorna");

    vi.mocked(api.finalReviews).mockResolvedValue([review()]);
    await wrapper.get("[data-testid='finale-reload']").trigger("click");
    await flushPromises();
    await wrapper.get("[data-testid='finale-submit']").trigger("click");
    await flushPromises();
    await wrapper.get("[data-testid='finale-revise']").trigger("click");
    await wrapper.get("form").trigger("submit");
    expect(wrapper.get("[role='alert']").text()).toBe("Scrivi un motivo prima di inviare.");
    expect(api.decideFinalApproval).not.toHaveBeenCalled();

    await wrapper.get("[data-testid='finale-reason']").setValue("Manca il riepilogo dei costi.");
    await wrapper.get("form").trigger("submit");
    await flushPromises();
    expect(vi.mocked(api.decideFinalApproval).mock.calls[0]?.[1]).toMatchObject({
      action: "REQUEST_REVISION",
      reason: "Manca il riepilogo dei costi.",
    });
  });

  it("has no axe violations", async () => {
    const wrapper = mountPanel(fakeApi(review()));
    await flushPromises();
    await expectAccessible(wrapper.element);
  });
});
