import { flushPromises, mount } from "@vue/test-utils";
import { createPinia } from "pinia";
import { afterEach, describe, expect, it, vi } from "vitest";
import ProjectResearchEvidencePanel from "./ProjectResearchEvidencePanel.vue";
import { ResearchEvidenceApiError, type ResearchEvidenceApi } from "../api/researchEvidence";
import type { TwinLearningApi } from "../api/twinLearning";
import type {
  ApprovedEvidenceCitationPayload,
  ResearchEvidencePayload,
} from "../types/researchEvidence";
import type { TwinUpdatePayload } from "../types/twinLearning";
import { expectAccessible } from "../test/axe";

const PROJECT = "11111111-1111-4111-8111-111111111111";
const TWIN = "22222222-2222-4222-8222-222222222222";
const SOURCE = "33333333-3333-4333-8333-333333333333";
const QUOTE = "  Synthetic calculator observation.\nSecond line.";

function source(overrides: Partial<ResearchEvidencePayload> = {}): ResearchEvidencePayload {
  return {
    id: SOURCE,
    code: "EVD-001",
    version: 1,
    title: "Synthetic calculator note",
    source_kind: "OWNER_INPUT",
    source_ref: "Anonymised test document",
    context: "Synthetic calculator scenario",
    method: "Handwritten test text",
    collected_at: null,
    limitations: "Not empirical; no participants",
    empirical: false,
    content_hash: "a".repeat(64),
    character_count: 55,
    byte_count: 55,
    created_at: "2026-10-02T10:00:00Z",
    status: "ACTIVE",
    retired_at: null,
    retired_reason: null,
    text_available: true,
    ...overrides,
  };
}

function update(overrides: Partial<TwinUpdatePayload> = {}): TwinUpdatePayload {
  return {
    id: "44444444-4444-4444-8444-444444444444",
    twin_id: TWIN,
    twin_name: "Calculator user",
    created_at: "2026-10-02T10:00:00Z",
    locale: "it-IT",
    status: "PROPOSED",
    base: { profile_version_number: 1, development_version_number: 0 },
    comment: "Synthetic suggestions to review",
    material: { changes: 0, tests: 0 },
    decision: null,
    cost_microusd: 0,
    evidence: {
      source_id: SOURCE,
      source_version: 1,
      content_hash: "a".repeat(64),
      rejected_changes: 2,
    },
    observations: (["SUPPORTS", "CONTRADICTS", "ADDS"] as const).map((effect, index) => ({
      index,
      statement: `Synthetic statement ${index}`,
      basis: "Synthetic source",
      about: { requirement: null, screen: null },
      contradicts_profile: null,
      evidence: {
        effect,
        field: "context_of_use",
        value: { kind: "TEXT", text: "Synthetic value", items: [], reason: null },
        citation: {
          source_id: SOURCE,
          source_version: 1,
          content_hash: "a".repeat(64),
          quote: QUOTE,
          start: 0,
          end: QUOTE.length,
          start_line: 1,
          end_line: 2,
        },
      },
    })),
    ...overrides,
  };
}

function api(initial = source(), approved: ApprovedEvidenceCitationPayload[] = []) {
  let current = initial;
  return {
    list: vi.fn<ResearchEvidenceApi["list"]>(async () => ({
      project_id: PROJECT,
      evidence: [current],
      citations: approved,
    })),
    show: vi.fn<ResearchEvidenceApi["show"]>(async () => ({ ...current, text: QUOTE })),
    add: vi.fn<ResearchEvidenceApi["add"]>(async () => ({
      status: "EVIDENCE_ADDED",
      evidence: current,
    })),
    revise: vi.fn<ResearchEvidenceApi["revise"]>(async () => ({
      status: "EVIDENCE_REVISED",
      evidence: current,
    })),
    retire: vi.fn<ResearchEvidenceApi["retire"]>(async () => {
      current = source({ status: "RETIRED" });
      return { status: "EVIDENCE_RETIRED", evidence: current, affected_twins: [TWIN] };
    }),
    deleteText: vi.fn<ResearchEvidenceApi["deleteText"]>(async () => {
      current = source({ status: "RETIRED", text_available: false });
      return { status: "EVIDENCE_TEXT_DELETED", evidence: current };
    }),
    propose: vi.fn<ResearchEvidenceApi["propose"]>(async () => ({
      status: "TWIN_UPDATE_PROPOSED",
      update: update(),
    })),
    decide: vi.fn<ResearchEvidenceApi["decide"]>(async (_project, _id, input) => ({
      status: "TWIN_UPDATE_DECIDED",
      update: update({ status: input.decision === "APPROVE" ? "APPROVED" : "REJECTED" }),
    })),
  };
}

const learningApi: TwinLearningApi = {
  overview: async () => ({ project_id: PROJECT, update_available: true, twins: [] }),
};
const wrappers: { unmount: () => void }[] = [];
function panel(
  client: ResearchEvidenceApi,
  locale: "it" | "en" = "it",
  extras: Record<string, unknown> = {},
) {
  const wrapper = mount(ProjectResearchEvidencePanel, {
    attachTo: document.body,
    global: { plugins: [createPinia()] },
    props: {
      projectId: PROJECT,
      authorize: (operation) => operation("test-token-not-real"),
      twins: [{ id: TWIN, name: "Calculator user" }],
      ready: true,
      locale,
      api: client,
      learningApi,
      generationApi: {
        list: async () => [],
        job: async () => {
          throw new Error("No synthetic job");
        },
      },
      ...extras,
    },
  });
  wrappers.push(wrapper);
  return wrapper;
}

afterEach(() => {
  for (const wrapper of wrappers.splice(0)) wrapper.unmount();
});

describe("ProjectResearchEvidencePanel", () => {
  it.each(["it", "en"] as const)(
    "warns before text entry, sends original text and never implies real user validation in %s",
    async (locale) => {
      const client = api();
      const wrapper = panel(client, locale);
      await flushPromises();
      await wrapper.get('[data-testid="evidence-add"]').trigger("click");
      expect(wrapper.get('[data-testid="evidence-privacy-warning"]').text()).toContain(
        locale === "it" ? "rimuovi nomi e dati personali" : "Remove names and personal details",
      );
      expect(wrapper.find('[data-testid="evidence-text"]').exists()).toBe(false);
      expect(client.add).not.toHaveBeenCalled();
      await wrapper.get('[data-testid="evidence-acknowledge"]').setValue(true);
      for (const field of ["title", "source_ref", "context", "method", "limitations"])
        await wrapper.get(`[data-testid="evidence-${field}"]`).setValue("Synthetic test text");
      await wrapper.get('[data-testid="evidence-text"]').setValue("  Synthetic text\nSecond line");
      await wrapper.get('[data-testid="evidence-form"]').trigger("submit");
      await flushPromises();
      expect(client.add).toHaveBeenCalledWith(
        PROJECT,
        expect.objectContaining({
          text: "  Synthetic text\nSecond line",
          source_kind: "OWNER_INPUT",
          empirical: false,
          acknowledged: true,
        }),
        "test-token-not-real",
      );
      expect(wrapper.find('[data-testid="evidence-text"]').exists()).toBe(false);
      expect(client.show).not.toHaveBeenCalled();
      await expectAccessible(wrapper.element);
    },
  );

  it("preserves exact quotes, shows per-change refusals, corrects and selects in a single owner decision", async () => {
    const client = api();
    const wrapper = panel(client);
    await flushPromises();
    await wrapper.get('[data-testid="evidence-propose"]').trigger("click");
    await flushPromises();
    expect(client.propose).toHaveBeenCalledWith(
      PROJECT,
      TWIN,
      source(),
      "it-IT",
      "test-token-not-real",
    );
    expect(wrapper.get('[data-testid="evidence-rejected-count"]').text()).toContain("2");
    const changes = wrapper.findAll('[data-testid="evidence-change"]');
    expect(changes.map((change) => change.text())).toEqual([
      expect.stringContaining("Sostiene"),
      expect.stringContaining("Contraddice"),
      expect.stringContaining("Aggiunge informazioni"),
    ]);
    expect(wrapper.get('[data-testid="evidence-quote"]').element.textContent).toBe(QUOTE);
    await changes[0]
      ?.get('[data-testid="evidence-correct"]')
      .setValue("Owner corrected synthetic value");
    await changes[1]?.get('[data-testid="evidence-keep"]').setValue(false);
    await wrapper.get('[data-testid="evidence-approve"]').trigger("click");
    await flushPromises();
    expect(client.decide).toHaveBeenCalledWith(
      PROJECT,
      update().id,
      {
        decision: "APPROVE",
        kept: [{ index: 0, statement: "Owner corrected synthetic value" }, { index: 2 }],
      },
      "test-token-not-real",
    );
    expect(wrapper.emitted("changed")).toHaveLength(1);
    expect(client.propose).toHaveBeenCalledTimes(1);
  });

  it("discards the whole proposal without keeping changes and reports an empty result's refusals", async () => {
    const client = api();
    const wrapper = panel(client);
    await flushPromises();
    await wrapper.get('[data-testid="evidence-propose"]').trigger("click");
    await flushPromises();
    await wrapper.get('[data-testid="evidence-discard"]').trigger("click");
    await flushPromises();
    expect(client.decide).toHaveBeenCalledWith(
      PROJECT,
      update().id,
      { decision: "REJECT", kept: [] },
      "test-token-not-real",
    );
    client.propose.mockResolvedValue({
      status: "TWIN_UPDATE_PROPOSED",
      update: update({
        status: "EMPTY",
        observations: [],
        evidence: {
          source_id: SOURCE,
          source_version: 1,
          content_hash: "a".repeat(64),
          rejected_changes: 6,
        },
      }),
    });
    await wrapper.get('[data-testid="evidence-propose"]').trigger("click");
    await flushPromises();
    expect(wrapper.get('[data-testid="evidence-rejected-count"]').text()).toContain("6");
    expect(wrapper.find('[data-testid="evidence-empty-proposal"]').exists()).toBe(true);
    expect(wrapper.find('[data-testid="evidence-approve"]').exists()).toBe(false);
  });

  it("withdraws before deleting text, warns about surviving copies and clears previously displayed text", async () => {
    const client = api();
    const wrapper = panel(client);
    await flushPromises();
    await wrapper.get('[data-testid="evidence-read-original"]').trigger("click");
    await flushPromises();
    expect(wrapper.get('[data-testid="evidence-original"]').element.textContent).toBe(QUOTE);
    expect(wrapper.find('[data-testid="evidence-delete-text"]').exists()).toBe(false);
    await wrapper.get('[data-testid="evidence-retire"]').trigger("click");
    expect(wrapper.get('[data-testid="evidence-retire-form"]').text()).toContain("tornano ipotesi");
    await wrapper
      .get('[data-testid="evidence-retire-reason"]')
      .setValue("Synthetic document withdrawn");
    await wrapper.get('[data-testid="evidence-retire-form"]').trigger("submit");
    await flushPromises();
    expect(client.retire).toHaveBeenCalledWith(
      PROJECT,
      SOURCE,
      "Synthetic document withdrawn",
      "test-token-not-real",
    );
    expect(wrapper.emitted("changed")).toHaveLength(1);
    await wrapper.get('[data-testid="evidence-delete-text"]').trigger("click");
    expect(wrapper.get('[data-testid="evidence-delete-form"]').text()).toContain(
      "citazioni storiche",
    );
    expect(wrapper.get('[data-testid="evidence-delete-form"]').text()).toContain("backup");
    await wrapper.get('[data-testid="evidence-delete-form"]').trigger("submit");
    expect(client.deleteText).not.toHaveBeenCalled();
    await wrapper.get('[data-testid="evidence-delete-acknowledge"]').setValue(true);
    await wrapper.get('[data-testid="evidence-delete-form"]').trigger("submit");
    await flushPromises();
    expect(client.deleteText).toHaveBeenCalledWith(PROJECT, SOURCE, "test-token-not-real");
    expect(wrapper.find('[data-testid="evidence-original"]').exists()).toBe(false);
  });

  it("shows approved citations and source context after reload without requesting the full document", async () => {
    const citation = update().observations[0]?.evidence?.citation;
    if (citation === undefined) throw new Error("Synthetic citation missing");
    const client = api(source(), [
      {
        twin_id: TWIN,
        twin_version: 2,
        field: "context_of_use",
        effect: "SUPPORTS",
        citation,
        status: "ACTIVE",
      },
    ]);
    const wrapper = panel(client);
    await flushPromises();
    expect(wrapper.get('[data-testid="evidence-approved-citation"]').text()).toContain(
      "Calculator user",
    );
    expect(wrapper.get('[data-testid="evidence-quote"]').element.textContent).toBe(QUOTE);
    expect(wrapper.text()).toContain("Not empirical; no participants");
    expect(wrapper.text()).toContain("a".repeat(64));
    expect(client.show).not.toHaveBeenCalled();
  });

  it("keeps an imported source's metadata and quotes readable while its original text is unavailable", async () => {
    const client = api(source({ text_available: false }));
    const wrapper = panel(client);
    await flushPromises();
    expect(wrapper.text()).toContain("Il testo originale non è più disponibile");
    expect(wrapper.text()).toContain("Versione più recente");
    expect(wrapper.find('[data-testid="evidence-propose"]').exists()).toBe(false);
    expect(wrapper.find('[data-testid="evidence-read-original"]').exists()).toBe(false);
    expect(wrapper.text()).toContain("a".repeat(64));
    expect(client.propose).not.toHaveBeenCalled();
  });

  it("states that withdrawal did not approve an existing draft", async () => {
    const client = api();
    client.retire.mockResolvedValue({
      status: "EVIDENCE_RETIRED",
      evidence: source({ status: "RETIRED" }),
      affected_twins: [TWIN],
      review_required: true,
    });
    const wrapper = panel(client);
    await flushPromises();
    await wrapper.get('[data-testid="evidence-retire"]').trigger("click");
    await wrapper
      .get('[data-testid="evidence-retire-reason"]')
      .setValue("Synthetic source withdrawn");
    await wrapper.get('[data-testid="evidence-retire-form"]').trigger("submit");
    await flushPromises();
    expect(wrapper.get('[data-testid="evidence-notice"]').text()).toContain(
      "la bozza in attesa non è stata approvata",
    );
    expect(client.propose).not.toHaveBeenCalled();
  });

  it("refuses excessive text locally with a split instruction and displays safe source errors", async () => {
    const client = api();
    const wrapper = panel(client);
    await flushPromises();
    await wrapper.get('[data-testid="evidence-add"]').trigger("click");
    await wrapper.get('[data-testid="evidence-acknowledge"]').setValue(true);
    await wrapper.get('[data-testid="evidence-text"]').setValue("x".repeat(24001));
    await wrapper.get('[data-testid="evidence-form"]').trigger("submit");
    expect(wrapper.get('[data-testid="evidence-error"]').text()).toContain(
      "Dividi il testo in parti",
    );
    expect(client.add).not.toHaveBeenCalled();
    client.propose.mockRejectedValue(
      new ResearchEvidenceApiError("synthetic raw provider error", {
        status: 409,
        code: "EVIDENCE_CONTEXT_CHANGED",
        payload: null,
      }),
    );
    await wrapper.get('[data-testid="evidence-propose"]').trigger("click");
    await flushPromises();
    expect(wrapper.get('[data-testid="evidence-error"]').text()).toContain(
      "La fonte o il twin sono cambiati",
    );
    expect(wrapper.text()).not.toContain("raw provider");
  });

  it("does not request a proposal until the twins are approved and never waits for design", async () => {
    const client = api();
    const wrapper = panel(client, "it", { ready: false });
    await flushPromises();
    expect(wrapper.text()).toContain("Il design non serve");
    expect(wrapper.get('[data-testid="evidence-propose"]').attributes("disabled")).toBeDefined();
    expect(client.propose).not.toHaveBeenCalled();
    await wrapper.setProps({ ready: true });
    expect(wrapper.get('[data-testid="evidence-propose"]').attributes("disabled")).toBeUndefined();
  });

  it("requires an explicit empirical declaration and re-acknowledgement for every new version", async () => {
    const client = api();
    const wrapper = panel(client);
    await flushPromises();
    await wrapper.get('[data-testid="evidence-revise"]').trigger("click");
    expect(wrapper.find('[data-testid="evidence-text"]').exists()).toBe(false);
    await wrapper.get('[data-testid="evidence-acknowledge"]').setValue(true);
    await wrapper.get('[data-testid="evidence-kind"]').setValue("EMPIRICAL_RESEARCH");
    await wrapper
      .get('[data-testid="evidence-text"]')
      .setValue("Synthetic method example; not a real study.");
    expect(wrapper.get('[data-testid="evidence-save"]').attributes("disabled")).toBeDefined();
    await wrapper.get('[data-testid="evidence-empirical"]').setValue(true);
    await wrapper.get('[data-testid="evidence-form"]').trigger("submit");
    await flushPromises();
    expect(client.revise).toHaveBeenCalledWith(
      PROJECT,
      SOURCE,
      expect.objectContaining({
        acknowledged: true,
        source_kind: "EMPIRICAL_RESEARCH",
        empirical: true,
      }),
      "test-token-not-real",
    );
    expect(client.add).not.toHaveBeenCalled();
  });

  it("reads only UTF-8 text files and keeps original whitespace and line endings for the server", async () => {
    const client = api();
    const wrapper = panel(client);
    await flushPromises();
    await wrapper.get('[data-testid="evidence-add"]').trigger("click");
    await wrapper.get('[data-testid="evidence-acknowledge"]').setValue(true);
    const input = wrapper.get<HTMLInputElement>('[data-testid="evidence-file"]');
    const content = "  Synthetic é text\r\nnext\rline";
    const bytes = new TextEncoder().encode(content);
    Object.defineProperty(input.element, "files", {
      configurable: true,
      value: [{ name: "synthetic.md", size: bytes.length, arrayBuffer: async () => bytes.buffer }],
    });
    await input.trigger("change");
    await flushPromises();
    expect(wrapper.get<HTMLTextAreaElement>('[data-testid="evidence-text"]').element.value).toBe(
      content.replace(/\r\n?/g, "\n"),
    );
    Object.defineProperty(input.element, "files", {
      configurable: true,
      value: [
        {
          name: "synthetic.txt",
          size: 2,
          arrayBuffer: async () => new Uint8Array([0xc3, 0x28]).buffer,
        },
      ],
    });
    await input.trigger("change");
    await flushPromises();
    expect(wrapper.get('[data-testid="evidence-error"]').text()).toContain("UTF-8 valido");
    const read = vi.fn(async () => bytes.buffer);
    Object.defineProperty(input.element, "files", {
      configurable: true,
      value: [{ name: "synthetic.pdf", size: bytes.length, arrayBuffer: read }],
    });
    await input.trigger("change");
    expect(read).not.toHaveBeenCalled();
    expect(client.add).not.toHaveBeenCalled();
  });

  it("does not expose a former project's delayed original text in the newly selected project", async () => {
    const client = api();
    let finish: ((value: ResearchEvidencePayload) => void) | undefined;
    client.show.mockImplementation(
      () =>
        new Promise((resolve) => {
          finish = resolve;
        }),
    );
    const wrapper = panel(client);
    await flushPromises();
    await wrapper.get('[data-testid="evidence-read-original"]').trigger("click");
    client.list.mockResolvedValue({ project_id: "new-project", evidence: [] });
    await wrapper.setProps({ projectId: "new-project", twins: [] });
    await flushPromises();
    finish?.({ ...source(), text: "Synthetic former project private text" });
    await flushPromises();
    expect(wrapper.text()).not.toContain("former project private text");
    expect(wrapper.find('[data-testid="evidence-original"]').exists()).toBe(false);
  });
});
