import { createPinia, setActivePinia } from "pinia";
import { flushPromises, mount } from "@vue/test-utils";
import { describe, expect, it, vi } from "vitest";
import type { ExecutionLaunchApi, ExecutionOperation } from "@/api/executionLaunch";
import type { JvmSourceRevisionPayload } from "@/types/jvmExecution";
import { useJvmExecutionStore } from "@/stores/jvmExecution";
import ProjectExecutionLaunch from "./ProjectExecutionLaunch.vue";

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
  const store = useJvmExecutionStore();
  store.$patch({
    activeProjectId: "project",
    sourceRevisions: [
      {
        id: "source",
        version_number: 1,
        content_hash: "a".repeat(64),
        target_selection: { target: "JVM_JAVA" },
      } as JvmSourceRevisionPayload,
    ],
  });
  vi.spyOn(store, "loadProject").mockResolvedValue();
  vi.spyOn(store, "loadExecution").mockResolvedValue();
  const api: ExecutionLaunchApi = {
    history: vi.fn().mockResolvedValue(existing),
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
      platform: "jvm",
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
      "jvm",
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
    expect(api.decide).toHaveBeenCalledWith("project", "jvm", expect.anything(), "CANCEL", "token");
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
      "jvm",
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
