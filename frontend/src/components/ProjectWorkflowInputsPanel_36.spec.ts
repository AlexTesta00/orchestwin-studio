import { createPinia } from "pinia";
import { flushPromises, mount } from "@vue/test-utils";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { ApiError } from "@/api/client";
import {
  AGENT_IDENTIFIERS,
  type AgentCatalogEntryResponse,
  type AgentCatalogResponse,
  type AgentIdentifier,
} from "@/api/team-contracts";
import { createWorkflowInputsApi, type WorkflowInputsApi } from "@/api/workflowInputs";
import { createAppI18n } from "@/i18n";
import { useTeamStore } from "@/stores/team";
import type { HumanGatePayload } from "@/types/design";
import type { ProvidedPrototype, WorkflowInputsPayload } from "@/types/workflowInputs";
import ProjectWorkflowInputsPanel from "./ProjectWorkflowInputsPanel.vue";
import teamFlowSource from "./ProjectTeamSelectionFlow.vue?raw";

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

const CATALOG_IDS = [...AGENT_IDENTIFIERS, "FUTURE_REVIEWER" as AgentIdentifier];

function catalog(): AgentCatalogResponse {
  return {
    catalog_version: 1,
    content_hash: "c".repeat(64),
    agents: CATALOG_IDS.map((agentId): AgentCatalogEntryResponse => ({
      agent_id: agentId,
      catalog_version: 1,
      kind: "SPECIALIST",
      selection_policy: "OWNER_SELECTABLE",
      capabilities: [],
      supported_project_modes: ["GREENFIELD_GENERATION"],
      name_key: `agentCatalog.roles.${agentId.toLowerCase()}.name`,
      description_key: `agentCatalog.roles.${agentId.toLowerCase()}.description`,
      is_always_present: false,
    })),
  };
}

function prototypeInput() {
  return {
    title: provided.title,
    visual_choices: provided.visual_choices,
    mockup: { styles: "", screens: provided.mockup.mockup.screens },
  };
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

  it.each([
    {
      locale: "it",
      names: [
        "Coordinatore",
        "Guida del progetto",
        "Organizzatore delle prospettive",
        "Referente delle approvazioni",
        "Custode delle versioni",
        "Responsabile delle prove",
        "Prodotto",
        "Esperienza d'uso (UX) · Ricercatore degli utenti",
        "Esperienza d'uso (UX) · Designer UX/UI",
        "Ingegneria del software · Architetto del prodotto",
        "Interfaccia web",
        "Servizi e dati",
        "Mobile",
        "Ingegneria del software · Specialista della qualità",
        "Sicurezza",
        "Accessibilità",
        "Collegamenti con altri sistemi",
        "Future reviewer",
      ],
    },
    {
      locale: "en",
      names: [
        "Coordinator",
        "Project guide",
        "Perspectives planner",
        "Approval guide",
        "Version keeper",
        "Test environment keeper",
        "Product",
        "User experience (UX) · User researcher",
        "User experience (UX) · UX/UI designer",
        "Software engineering · Product architect",
        "Web interface",
        "Services and data",
        "Mobile",
        "Software engineering · Quality specialist",
        "Security",
        "Accessibility",
        "Connections to other systems",
        "Future reviewer",
      ],
    },
  ] as const)(
    "names the catalog perspectives in $locale with the words of the Perspectives step, adds the role where two share a name, never with a key",
    async ({ locale, names }) => {
      const pinia = createPinia();
      useTeamStore(pinia).catalog = catalog();
      const wrapper = mount(ProjectWorkflowInputsPanel, {
        props: {
          projectId: "project",
          stage: 1,
          expert: true,
          locale,
          authorize: async (operation) => operation("token"),
          baseContext: {},
          api: fakeApi(),
        },
        global: {
          plugins: [pinia, createAppI18n(locale)],
          stubs: { UiButton: false, UiStateBlock: true },
        },
      });
      await flushPromises();
      const items = wrapper.findAll('[data-testid="owner-catalog-agent"]');
      const shown = items.map((item) => item.get("span").text());
      expect(shown).toEqual(names);
      expect(new Set(shown.slice(0, AGENT_IDENTIFIERS.length)).size).toBe(17);
      expect(shown.filter((name) => /[A-Z]+_[A-Z_]+|agentCatalog\./u.test(name))).toEqual([]);
      expect(items.map((item) => item.get("code").text())).toEqual(CATALOG_IDS);
      expect(items.every((item) => item.classes().includes("min-w-0"))).toBe(true);
      expect(items.every((item) => item.get("span").classes().includes("wrap-anywhere"))).toBe(
        true,
      );
      expect(wrapper.html()).not.toContain("agentCatalog.");
      const perspectives = new Set(names.slice(6, 17).map((name) => name.replace(/ · .+$/u, "")));
      for (const name of perspectives) expect(teamFlowSource).toContain(`name: "${name}"`);
    },
  );

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

  it.each([
    {
      locale: "it",
      sentence: "Lo Studio ha dato una risposta che questa pagina non riesce a leggere.",
    },
    { locale: "en", sentence: "The Studio gave an answer that this page cannot read." },
  ] as const)(
    "says in $locale that the answer could not be read without a code or the words of the API",
    async ({ locale, sentence }) => {
      const failing = createWorkflowInputsApi({
        fetchImpl: async () => new Response("<html>", { status: 200 }),
      });
      const { wrapper } = render({ ...fakeApi(), read: failing.read }, { locale });
      await flushPromises();
      const text = wrapper.get('[data-testid="workflow-inputs-error"]').attributes("text");
      expect(text).toBe(sentence);
      expect(text).not.toMatch(/[A-Z]+_[A-Z_]+/);
      expect(wrapper.html()).not.toContain("Invalid response");
      expect(
        wrapper.findAll('[data-testid="workflow-inputs-error-details"]').map((details) => ({
          open: details.attributes("open") !== undefined,
          code: details.get("code").text(),
        })),
      ).toEqual([{ open: false, code: "INVALID_API_RESPONSE" }]);
    },
  );

  it.each(
    (["it", "en"] as const).flatMap((locale) =>
      [
        {
          status: 422,
          body: JSON.stringify({
            detail: { code: "WORKFLOW_RECORDS_INVALID", message: "invalid UUID" },
          }),
          sentence: {
            it: "I dati inseriti non sono validi: controlla il contenuto e riprova.",
            en: "The data you entered is not valid: check the content and try again.",
          },
          detail: "WORKFLOW_RECORDS_INVALID · invalid UUID",
        },
        {
          status: 409,
          body: JSON.stringify({ detail: { code: "WORKFLOW_CONTEXT_CHANGED" } }),
          sentence: {
            it: "Il progetto è cambiato nel frattempo: ricarica la pagina e riprova.",
            en: "The project changed in the meantime: reload the page and try again.",
          },
          detail: "WORKFLOW_CONTEXT_CHANGED",
        },
        {
          status: 500,
          body: "",
          sentence: {
            it: "Non è stato possibile completare la richiesta. Puoi riprovare.",
            en: "The request could not be completed. You can try again.",
          },
          detail: null,
        },
        {
          status: null,
          body: "",
          sentence: {
            it: "Non è stato possibile completare la richiesta. Puoi riprovare.",
            en: "The request could not be completed. You can try again.",
          },
          detail: null,
        },
      ].map((answer) => ({ locale, ...answer })),
    ),
  )(
    "says in $locale why saving failed and keeps the code in the technical details ($status)",
    async ({ locale, status, body, sentence, detail }) => {
      const failing = createWorkflowInputsApi({
        fetchImpl: async () => {
          if (status === null) throw new TypeError("Failed to fetch");
          return new Response(body, { status });
        },
      });
      const { wrapper, api } = render({ ...fakeApi(), team: failing.team }, { locale });
      await flushPromises();
      await wrapper
        .get('[data-testid="owner-input-json"]')
        .setValue(
          JSON.stringify({ selected_agent_ids: ["QA_TEST_ENGINEER"], owner_rationales: [] }),
        );
      await wrapper.get("form").trigger("submit");
      await flushPromises();
      const text = wrapper.get('[data-testid="workflow-inputs-error"]').attributes("text");
      expect(text).toBe(sentence[locale]);
      expect(text).not.toMatch(/[A-Z]+_[A-Z_]+/);
      expect(text).not.toMatch(/\d{3}/);
      expect(
        wrapper.findAll('[data-testid="workflow-inputs-error-details"]').map((details) => ({
          open: details.attributes("open") !== undefined,
          summary: details.get("summary").text(),
          code: details.get("code").text(),
        })),
      ).toEqual(
        detail === null
          ? []
          : [
              {
                open: false,
                summary: locale === "it" ? "Dettagli tecnici" : "Technical details",
                code: detail,
              },
            ],
      );
      expect(wrapper.html()).not.toMatch(/Workflow inputs request failed|Failed to fetch/);
      expect(api.read).toHaveBeenCalledTimes(1);
    },
  );

  it.each([
    { locale: "it", sentence: "Serve prima una Definizione approvata." },
    { locale: "en", sentence: "An approved Definition is required first." },
  ] as const)(
    "says in $locale that an approved Definition is required when the Studio refuses the prototype for it",
    async ({ locale, sentence }) => {
      const failing = createWorkflowInputsApi({
        fetchImpl: async () =>
          new Response(JSON.stringify({ detail: { code: "REQUIREMENTS_APPROVAL_REQUIRED" } }), {
            status: 409,
          }),
      });
      const { wrapper } = render(
        { ...fakeApi(), savePrototype: failing.savePrototype },
        { stage: 4, locale },
      );
      await flushPromises();
      await wrapper
        .get('[data-testid="owner-input-json"]')
        .setValue(JSON.stringify(prototypeInput()));
      await wrapper.get("form").trigger("submit");
      await flushPromises();
      expect(wrapper.get('[data-testid="workflow-inputs-error"]').attributes("text")).toBe(
        sentence,
      );
      expect(
        wrapper.findAll('[data-testid="workflow-inputs-error-details"]').map((details) => ({
          open: details.attributes("open") !== undefined,
          code: details.get("code").text(),
        })),
      ).toEqual([{ open: false, code: "REQUIREMENTS_APPROVAL_REQUIRED" }]);
    },
  );

  it("says the same sentence when the page has no approved Definition to send with the prototype", async () => {
    const { wrapper, api } = render(fakeApi(), { stage: 4, locale: "it", baseContext: {} });
    await flushPromises();
    await wrapper
      .get('[data-testid="owner-input-json"]')
      .setValue(JSON.stringify(prototypeInput()));
    await wrapper.get("form").trigger("submit");
    await flushPromises();
    expect(api.savePrototype).not.toHaveBeenCalled();
    expect(wrapper.get('[data-testid="workflow-inputs-error"]').attributes("text")).toBe(
      "Serve prima una Definizione approvata.",
    );
    expect(wrapper.get('[data-testid="workflow-inputs-error-details"] code').text()).toBe(
      "REQUIREMENTS_APPROVAL_REQUIRED",
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
          ? "La valutazione dei twin sul prototipo fornito non è disponibile."
          : "Twin evaluation of the supplied prototype is unavailable.",
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

  it.each([
    [
      "en",
      "Its structure matches generated mockups. ut code and the scenario walkthrough are also unavailable for this Design.",
    ],
    [
      "it",
      "La struttura è la stessa dei mockup generati. Per questo Design non sono disponibili nemmeno ut code e il percorso dello scenario.",
    ],
  ] as const)(
    "says in %s what the supplied Design shares with generated mockups without naming sprints",
    async (locale, sentence) => {
      const api = fakeApi();
      vi.mocked(api.read).mockResolvedValue(envelope([provided]));
      vi.mocked(api.currentPrototype).mockResolvedValue(provided);
      vi.mocked(api.prototypeGate).mockResolvedValue(prototypeGate);
      const { wrapper } = render(api, { stage: 4, expert: false, locale });
      await flushPromises();
      const lines = wrapper
        .get('[data-testid="provided-prototype"]')
        .findAll("p")
        .map((line) => line.text());
      expect(lines).toContain(sentence);
      expect(lines.filter((line) => /sprint 3[58]|del 35/.test(line))).toEqual([]);
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
