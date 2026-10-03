import { createPinia } from "pinia";
import { flushPromises, mount } from "@vue/test-utils";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { ApiError } from "@/api/client";
import type { WorkflowInputsApi } from "@/api/workflowInputs";
import { createAppI18n } from "@/i18n";
import type { HumanGatePayload } from "@/types/design";
import type { ProvidedPrototype, WorkflowInputsPayload } from "@/types/workflowInputs";
import ProjectWorkflowInputsPanel from "./ProjectWorkflowInputsPanel.vue";

const reference = { artifact_id: "definition-id", version_number: 2, content_hash: "d".repeat(64) };
const provided: ProvidedPrototype = {
  id: "prototype-id",
  code: "PRT-001",
  project_id: "project",
  version_number: 1,
  based_on_version_number: null,
  definition_reference: reference,
  title: "Owner prototype",
  declared_origin: "Penpot",
  visual_choices: {},
  created_at: "2026-10-03T00:00:00Z",
  content_hash: "e".repeat(64),
  mockup: {
    mockup: {
      contract_version: 1,
      design_alternative_id: "prototype-id",
      title: "Owner prototype",
      styles: "",
      screens: [
        { code: "SCR-001", title: "Input", state: "DEFAULT", markup: "<main>Input</main>" },
        { code: "SCR-002", title: "Result", state: "SUCCESS", markup: "<main>Result</main>" },
      ],
    },
    requirement_ids_by_code: {},
  },
};
const prototypeGate: HumanGatePayload = {
  id: "gate-id",
  project_id: "project",
  owner_user_id: "owner",
  gate_type: "DESIGN",
  artifact: {
    project_id: "project",
    gate_type: "DESIGN",
    artifact_id: provided.id,
    version: 1,
    content_hash: provided.content_hash,
  },
  iteration: 1,
  max_iterations: 3,
  status: "PENDING_APPROVAL",
  created_at: provided.created_at,
  updated_at: provided.created_at,
  event_sequence: 1,
  resume_status: null,
};

function envelope(prototypes: ProvidedPrototype[] = []): WorkflowInputsPayload {
  return {
    kind: "orchestwin.workflow-inputs",
    schema_version: 1,
    project_id: "project",
    decisions: [],
    prototypes,
    limits: [],
  };
}

function fakeApi(): WorkflowInputsApi {
  return {
    read: vi.fn().mockResolvedValue(envelope()),
    decide: vi.fn().mockResolvedValue({}),
    team: vi.fn().mockResolvedValue({ status: "CREATED" }),
    profiles: vi.fn().mockResolvedValue({ status: "CREATED" }),
    definition: vi.fn().mockResolvedValue({ status: "CREATED" }),
    prototypes: vi.fn().mockResolvedValue([]),
    currentPrototype: vi.fn().mockRejectedValue(new ApiError(404, "PROVIDED_PROTOTYPE_NOT_FOUND")),
    savePrototype: vi.fn().mockResolvedValue(provided),
    prototypeGate: vi.fn().mockRejectedValue(new ApiError(404, "HUMAN_GATE_NOT_FOUND")),
    submitPrototype: vi.fn().mockResolvedValue({ outcome: "APPLIED", gate: prototypeGate }),
    decidePrototype: vi
      .fn()
      .mockResolvedValue({ outcome: "APPLIED", gate: { ...prototypeGate, status: "APPROVED" } }),
    prototypeDocument: vi.fn().mockResolvedValue({
      html: "<!doctype html><html><head><meta http-equiv='Content-Security-Policy' content=\"default-src 'none'\"></head><body>Validated document</body></html>",
      title: "Validated prototype",
    }),
  };
}

function render(api = fakeApi(), extra: Record<string, unknown> = {}) {
  const wrapper = mount(ProjectWorkflowInputsPanel, {
    props: {
      projectId: "project",
      stage: 1,
      expert: true,
      locale: "en",
      authorize: async (operation) => operation("token"),
      baseContext: { REQUIREMENTS: reference },
      api,
      ...extra,
    },
    global: {
      plugins: [createPinia(), createAppI18n("en")],
      stubs: { UiButton: false, UiStateBlock: true },
    },
  });
  return { wrapper, api };
}

describe("owner workflow inputs in sprint 36", () => {
  beforeEach(() => vi.restoreAllMocks());

  it("only reads on mount and on changing guidance", async () => {
    const { wrapper, api } = render();
    await flushPromises();
    await wrapper.setProps({ expert: false });
    await wrapper.setProps({ expert: true });
    expect(api.read).toHaveBeenCalledTimes(1);
    for (const operation of [
      api.decide,
      api.team,
      api.profiles,
      api.definition,
      api.savePrototype,
      api.submitPrototype,
      api.decidePrototype,
    ])
      expect(operation).not.toHaveBeenCalled();
  });

  it("preserves each form when switching sections and guidance", async () => {
    const { wrapper } = render();
    await flushPromises();
    const teamJson = JSON.stringify({
      selected_agent_ids: ["QA_TEST_ENGINEER"],
      owner_rationales: [{ agent_id: "QA_TEST_ENGINEER", statement: "Check safety" }],
    });
    await wrapper.get('[data-testid="owner-input-json"]').setValue(teamJson);
    await wrapper.setProps({ stage: 3 });
    await wrapper.get('[data-testid="owner-input-json"]').setValue("definition draft");
    await wrapper.setProps({ expert: false });
    await wrapper.setProps({ expert: true, stage: 1 });
    expect(
      (wrapper.get('[data-testid="owner-input-json"]').element as HTMLTextAreaElement).value,
    ).toBe(teamJson);
    await wrapper.setProps({ stage: 3 });
    expect(
      (wrapper.get('[data-testid="owner-input-json"]').element as HTMLTextAreaElement).value,
    ).toBe("definition draft");
  });

  it("records a reason without generating or approving an artifact and rereads the result", async () => {
    const { wrapper, api } = render();
    await flushPromises();
    await wrapper
      .get('[data-testid="workflow-gap-reason"]')
      .setValue("Research is not available yet");
    await wrapper.get('[data-testid="declare-workflow-gap"]').trigger("click");
    await flushPromises();
    expect(api.decide).toHaveBeenCalledWith(
      "project",
      {
        target: "TEAM",
        action: "DECLARE_MISSING",
        reason: "Research is not available yet",
        base_context: { REQUIREMENTS: reference },
      },
      "token",
    );
    expect(api.read).toHaveBeenCalledTimes(2);
    expect(api.team).not.toHaveBeenCalled();
    expect(api.submitPrototype).not.toHaveBeenCalled();
  });

  it("saves exactly the owner-selected perspectives with no generation or gate request", async () => {
    const { wrapper, api } = render();
    await flushPromises();
    const input = {
      selected_agent_ids: ["QA_TEST_ENGINEER"],
      owner_rationales: [{ agent_id: "QA_TEST_ENGINEER", statement: "Check safety" }],
    };
    await wrapper.get('[data-testid="owner-input-json"]').setValue(JSON.stringify(input));
    await wrapper.get("form").trigger("submit");
    await flushPromises();
    expect(api.team).toHaveBeenCalledWith("project", input, "token");
    expect(api.read).toHaveBeenCalledTimes(2);
    expect(api.submitPrototype).not.toHaveBeenCalled();
  });

  it("refuses a legacy incomplete Definition instead of using schema one", async () => {
    const { wrapper, api } = render(fakeApi(), { stage: 3 });
    await flushPromises();
    await wrapper
      .get('[data-testid="owner-input-json"]')
      .setValue(JSON.stringify({ specification: { schema_version: 1, requirements: [] } }));
    await wrapper.get("form").trigger("submit");
    await flushPromises();
    expect(api.definition).not.toHaveBeenCalled();
    expect(wrapper.find('[data-testid="workflow-inputs-error"]').attributes("text")).toBe(
      "OWNER_DEFINITION_SCHEMA_2_REQUIRED",
    );
  });

  it("sends the declared origin and exact Definition reference without approving the prototype", async () => {
    const { wrapper, api } = render(fakeApi(), { stage: 4 });
    await flushPromises();
    const input = {
      title: provided.title,
      visual_choices: provided.visual_choices,
      mockup: { styles: "", screens: provided.mockup.mockup.screens },
    };
    await wrapper.get('[data-testid="owner-input-json"]').setValue(JSON.stringify(input));
    await wrapper.get('[data-testid="provided-prototype-origin"]').setValue("Penpot");
    await wrapper.get("form").trigger("submit");
    await flushPromises();
    expect(api.savePrototype).toHaveBeenCalledWith(
      "project",
      {
        ...input,
        declared_origin: "Penpot",
        expected_definition_reference: reference,
        expected_version_number: 0,
      },
      "token",
    );
    expect(api.submitPrototype).not.toHaveBeenCalled();
    expect(api.decidePrototype).not.toHaveBeenCalled();
  });

  it.each(["en", "it"] as const)(
    "declares the evaluation limit in %s and previews only the server document in a sandbox",
    async (locale) => {
      const api = fakeApi();
      vi.mocked(api.read).mockResolvedValue(envelope([provided]));
      vi.mocked(api.currentPrototype).mockResolvedValue(provided);
      vi.mocked(api.prototypeGate).mockResolvedValue(prototypeGate);
      const { wrapper } = render(api, { stage: 4, expert: false, locale });
      await flushPromises();
      expect(wrapper.get('[data-testid="provided-prototype-evaluation-limit"]').text()).toBe(
        locale === "it"
          ? "La valutazione dei twin sul prototipo fornito non è disponibile nello sprint 36."
          : "Twin evaluation of the supplied prototype is unavailable in sprint 36.",
      );
      await wrapper.findAll("button")[0]!.trigger("click");
      await flushPromises();
      expect(api.prototypeDocument).toHaveBeenCalledWith(
        "project",
        provided.id,
        "token",
        "SCR-001",
      );
      const iframe = wrapper.get("iframe");
      expect(iframe.attributes("sandbox")).toBe("");
      expect(iframe.attributes("srcdoc")).toContain("Validated document");
      expect(api.savePrototype).not.toHaveBeenCalled();
      expect(api.decidePrototype).not.toHaveBeenCalled();
    },
  );

  it("requires a separate approval click and refuses to approve a stale Definition", async () => {
    const api = fakeApi();
    vi.mocked(api.currentPrototype).mockResolvedValue(provided);
    vi.mocked(api.prototypeGate).mockResolvedValue(prototypeGate);
    const { wrapper } = render(api, { stage: 4 });
    await flushPromises();
    expect(api.decidePrototype).not.toHaveBeenCalled();
    await wrapper.get('[data-testid="approve-provided-prototype"]').trigger("click");
    await flushPromises();
    expect(api.decidePrototype).toHaveBeenCalledWith("project", { action: "APPROVE" }, "token");
    await wrapper.setProps({ baseContext: { REQUIREMENTS: { ...reference, version_number: 3 } } });
    expect(wrapper.text()).toContain("Needs updating");
    expect(wrapper.find('[data-testid="approve-provided-prototype"]').exists()).toBe(false);
  });
});
