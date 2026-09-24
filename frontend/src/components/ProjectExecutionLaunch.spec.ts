import { createPinia, setActivePinia } from "pinia";
import { flushPromises, mount } from "@vue/test-utils";
import { describe, expect, it, vi } from "vitest";
import type {
  BrowserExecutionChecks,
  ExecutionLaunchApi,
  ExecutionOperation,
} from "@/api/executionLaunch";
import { useWebExecutionStore } from "@/stores/webExecution";
import type { WebSourceRevisionPayload } from "@/types/webExecution";
import ProjectExecutionLaunch from "./ProjectExecutionLaunch.vue";
import { expectAccessible } from "@/test/axe";

function operation(): ExecutionOperation {
  return {
    id: "operation",
    source_revision_id: "source",
    kind: "EXECUTION",
    content_hash: "b".repeat(64),
    state: "PENDING",
    gate_current: true,
    gate: { id: "gate", status: "PENDING_APPROVAL", event_sequence: 1 },
    payload: {
      command: { source_revision_id: "source" },
      effective_phases: ["BUILD", "TEST"],
      source_revision: { content_hash: "a".repeat(64) },
    },
  };
}
function setup(existing: ExecutionOperation[] = []) {
  const pinia = createPinia();
  setActivePinia(pinia);
  const store = useWebExecutionStore();
  store.$patch({
    activeProjectId: "project",
    sourceRevisions: [
      {
        id: "source",
        version_number: 1,
        content_hash: "a".repeat(64),
        target_selection: { target: "WEB_NODE_EXPRESS" },
      } as WebSourceRevisionPayload,
    ],
  });
  vi.spyOn(store, "loadProject").mockResolvedValue();
  vi.spyOn(store, "loadExecution").mockResolvedValue();
  const api: ExecutionLaunchApi = {
    history: vi.fn().mockResolvedValue(existing),
    journey: vi.fn().mockResolvedValue({
      status: "NOT_DERIVABLE",
      reason: "APPROVED_PROTOTYPE_UNAVAILABLE",
      source_revision_id: "source",
    }),
    prepare: vi.fn().mockResolvedValue(operation()),
    decide: vi.fn().mockImplementation(async (_p, _f, current, action) => ({
      ...current,
      gate: {
        ...current.gate,
        status: action === "APPROVE" ? "APPROVED" : "CANCELLED",
        event_sequence: 2,
      },
    })),
    start: vi.fn().mockResolvedValue({ id: "attempt", report: { status: "FAILED" } }),
    applyRepair: vi.fn().mockResolvedValue({ id: "repaired-source" }),
  };
  const wrapper = mount(ProjectExecutionLaunch, {
    props: {
      projectId: "project",
      platform: "web",
      api,
      authorize: <T>(fn: (token: string) => Promise<T>) => fn("token"),
    },
    global: { plugins: [pinia] },
  });
  const button = (label: string) => wrapper.findAll("button").find((b) => b.text() === label)!;
  return { wrapper, api, store, button };
}

describe("configured execution launch", () => {
  it("requires separate owner actions for preparation, approval and execution", async () => {
    const { wrapper, api, button } = setup();
    await flushPromises();
    expect(api.prepare).not.toHaveBeenCalled();
    expect(api.start).not.toHaveBeenCalled();
    await button("Prepare plan").trigger("click");
    await flushPromises();
    expect(wrapper.text()).toContain("BUILD → TEST");
    expect(button("Start approved execution").attributes("disabled")).toBeDefined();
    expect(api.decide).not.toHaveBeenCalled();
    await button("Approve this plan").trigger("click");
    await flushPromises();
    expect(api.decide).toHaveBeenCalledWith(
      "project",
      "web",
      expect.objectContaining({ content_hash: "b".repeat(64) }),
      "APPROVE",
      "token",
    );
    expect(api.start).not.toHaveBeenCalled();
    await button("Start approved execution").trigger("click");
    await flushPromises();
    expect(api.start).toHaveBeenCalledOnce();
    expect(wrapper.text()).toContain("Recorded outcome: FAILED");
    expect(button("Start approved execution").attributes("disabled")).toBeDefined();
  });

  it("recovers a pending operation on reload without proposing a duplicate", async () => {
    const { api, button } = setup([operation()]);
    await flushPromises();
    expect(button("Prepare plan").attributes("disabled")).toBeDefined();
    expect(button("Approve this plan").attributes("disabled")).toBeUndefined();
    expect(api.prepare).not.toHaveBeenCalled();
  });

  it("can cancel an old source plan but cannot approve or execute it", async () => {
    const { api, button } = setup([{ ...operation(), source_revision_id: "old-source" }]);
    await flushPromises();
    expect(button("Approve this plan").attributes("disabled")).toBeDefined();
    expect(button("Start approved execution").attributes("disabled")).toBeDefined();
    await button("Cancel plan").trigger("click");
    await flushPromises();
    expect(api.decide).toHaveBeenCalledWith("project", "web", expect.anything(), "CANCEL", "token");
  });

  it("allows exact repair approval without offering execution of a repair payload", async () => {
    const repair: ExecutionOperation = {
      ...operation(),
      kind: "REPAIR",
      payload: { proposal: { base_revision: { content_hash: "a".repeat(64) } } },
    };
    const { wrapper, api, button } = setup([repair]);
    await flushPromises();
    expect(wrapper.text()).not.toContain("Start approved execution");
    await button("Approve this plan").trigger("click");
    await flushPromises();
    expect(api.decide).toHaveBeenCalledOnce();
    expect(api.start).not.toHaveBeenCalled();
    expect(api.applyRepair).not.toHaveBeenCalled();
    await button("Apply approved repair").trigger("click");
    await flushPromises();
    expect(api.applyRepair).toHaveBeenCalledWith(
      "web",
      expect.objectContaining({ id: "operation" }),
      "token",
    );
    expect(wrapper.text()).toContain("Repair applied");
  });

  it("retains the completed outcome when refreshing the same source object", async () => {
    const current = operation();
    current.gate.status = "APPROVED";
    const { api, store, wrapper, button } = setup([current]);
    vi.mocked(store.loadProject).mockImplementation(async () => {
      store.sourceRevisions = store.sourceRevisions.map((revision) => ({ ...revision }));
    });
    await flushPromises();
    await button("Start approved execution").trigger("click");
    await flushPromises();
    expect(wrapper.text()).toContain("Recorded outcome: FAILED");
    expect(api.history).toHaveBeenCalledOnce();
    expect(store.loadExecution).toHaveBeenCalledOnce();
  });
});

describe("derived web journey", () => {
  function journey() {
    const steps = [
      {
        kind: "fill",
        selector: "#ELM-002",
        value: "Giulia Verdi",
        label: "Nome ospite",
        screen: "SCR-001",
      },
      { kind: "press", selector: "#ELM-003", value: "Enter", label: "Aggiungi", screen: "SCR-001" },
      {
        kind: "expect_not_text",
        selector: "#ELM-007",
        value: "Esempio: 1. Mario Rossi",
        label: "Esempio",
        screen: "SCR-002",
      },
      {
        kind: "expect_contains",
        selector: "#ELM-007",
        value: "Giulia Verdi",
        label: "Esempio",
        screen: "SCR-002",
      },
      { kind: "click", selector: "#ELM-008", value: null, label: "Torna", screen: "SCR-002" },
      {
        kind: "expect_text",
        selector: "#ELM-001",
        value: "Aggiungi un ospite",
        label: "Aggiungi un ospite",
        screen: "SCR-001",
      },
    ].map((item) => ({
      action: { kind: item.kind, selector: item.selector, value: item.value },
      element_code: item.selector.slice(1),
      element_label: item.label,
      screen_code: item.screen,
      screen_title: item.screen,
    }));
    return {
      status: "DERIVED" as const,
      source_revision_id: "source",
      source_revision_content_hash: "a".repeat(64),
      declared_routes: [],
      browser_interactions: [{ route_id: "root", actions: steps.map((item) => item.action) }],
      steps,
    };
  }
  function setupWeb() {
    const pinia = createPinia();
    setActivePinia(pinia);
    const store = useWebExecutionStore();
    store.$patch({
      activeProjectId: "project",
      sourceRevisions: [
        {
          id: "source",
          version_number: 1,
          content_hash: "a".repeat(64),
          target_selection: { target: "WEB_STATIC" },
        } as WebSourceRevisionPayload,
      ],
    });
    vi.spyOn(store, "loadProject").mockResolvedValue();
    vi.spyOn(store, "loadExecution").mockResolvedValue();
    const api: ExecutionLaunchApi = {
      history: vi.fn().mockResolvedValue([]),
      journey: vi.fn().mockResolvedValue(journey()),
      prepare: vi.fn().mockResolvedValue({ ...operation(), payload: { command: {} } }),
      decide: vi.fn(),
      start: vi.fn(),
      applyRepair: vi.fn(),
    };
    const wrapper = mount(ProjectExecutionLaunch, {
      props: {
        projectId: "project",
        platform: "web",
        api,
        authorize: <T>(fn: (token: string) => Promise<T>) => fn("token"),
      },
      global: { plugins: [pinia] },
    });
    return { wrapper, api };
  }

  it("shows the derived steps in plain language and sends them as the browser checks", async () => {
    const { wrapper, api } = setupWeb();
    await flushPromises();
    expect(api.journey).toHaveBeenCalledWith("project", "token");
    expect(wrapper.text()).toContain("Fill “Nome ospite” with “Giulia Verdi”");
    expect(wrapper.text()).toContain(
      "Check that “Esempio” no longer shows “Esempio: 1. Mario Rossi”",
    );
    expect(wrapper.text()).not.toContain("CSS selector");
    const sample = wrapper.find("ol input");
    await sample.setValue("Anna Bianchi");
    const prepare = wrapper.findAll("button").find((b) => b.text() === "Prepare plan")!;
    await prepare.trigger("click");
    await flushPromises();
    const checks = (api.prepare as ReturnType<typeof vi.fn>).mock
      .calls[0]![4] as BrowserExecutionChecks;
    expect(checks.browser_interactions[0]!.actions[0]).toEqual({
      kind: "fill",
      selector: "#ELM-002",
      value: "Anna Bianchi",
    });
    expect(checks.browser_interactions[0]!.actions[3]).toEqual({
      kind: "expect_contains",
      selector: "#ELM-007",
      value: "Anna Bianchi",
    });
    expect(checks.browser_interactions[0]!.actions[2]!.value).toBe("Esempio: 1. Mario Rossi");
    await wrapper
      .findAll("button")
      .find((b) => b.text() === "Define the steps manually")!
      .trigger("click");
    expect(wrapper.text()).toContain("CSS selector");
  });

  it("has no axe violations", async () => {
    const { wrapper } = setup();
    await flushPromises();
    await expectAccessible(wrapper.element);
  });
});
