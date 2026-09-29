import { createPinia, setActivePinia } from "pinia";

import { flushPromises, mount } from "@vue/test-utils";

import { beforeEach, describe, expect, it, vi } from "vitest";

import ProjectDevelopmentPanel from "./ProjectDevelopmentPanel.vue";
import { createAppI18n } from "@/i18n";
import { expectAccessible } from "@/test/axe";
import { SELECTED_DESIGN_VERSION } from "@/test/designFixtures";

import { CodeChangesApiError, type CodeChangesApi } from "../api/codeChanges";
import { useDesignStore } from "../stores/design";
import { useRequirementsStore } from "../stores/requirements";
import type {
  AlignmentPayload,
  ChangeReviewListPayload,
  ChangeReviewRunPayload,
  CodeChangeListPayload,
  CodeChangePayload,
} from "../types/codeChanges";
import type { RequirementsSpecificationVersionPayload } from "../types/requirements";

type Locale = "en" | "it";

const PROJECT_ID = SELECTED_DESIGN_VERSION.project_id;
const SECOND_PROJECT_ID = "22222222-2222-4222-8222-222222222222";
const TOKEN = "test-token-not-real";
const NEWEST_COMMIT = "c0ffee1234567890abcdef1234567890abcdef12";
const SECOND_COMMIT = "b0b0b0b1b0b0b0b0b0b0b0b0b0b0b0b0b0b0b0b0";
const ALIGNED_COMMIT = "a1a1a1a2a1a1a1a1a1a1a1a1a1a1a1a1a1a1a1a1";
const RUN_ID = "33333333-3333-4333-8333-333333333333";

const NEWEST: CodeChangePayload = {
  commit: NEWEST_COMMIT,
  parent: SECOND_COMMIT,
  committed_at: "2026-09-29T08:00:00+00:00",
  author: "Alex",
  message: "Show the reservations of the day\n\nThe list drops the empty state.",
  files: [
    { path: "src/reservations.js", kind: "MODIFIED", added: 30, removed: 4 },
    { path: "src/reservations.css", kind: "ADDED", added: 12, removed: 0 },
  ],
  recorded_at: "2026-09-29T08:01:00+00:00",
  review: {
    run_id: RUN_ID,
    reviewed_at: "2026-09-29T08:05:00+00:00",
    verdict: "CODE_DRIFT",
    summary: "The empty state of the list was removed.",
  },
  decision: { kind: "CODE_TASKS", decided_at: "2026-09-29T08:10:00+00:00", note: null },
};

const SECOND: CodeChangePayload = {
  commit: SECOND_COMMIT,
  parent: ALIGNED_COMMIT,
  committed_at: "2026-09-28T18:00:00+00:00",
  author: null,
  message: "Add the availability screen",
  files: [{ path: "src/availability.js", kind: "ADDED", added: 50, removed: 0 }],
  recorded_at: "2026-09-28T18:01:00+00:00",
  review: null,
  decision: null,
};

const ALIGNED: CodeChangePayload = {
  commit: ALIGNED_COMMIT,
  parent: null,
  committed_at: "2026-09-28T16:00:00+00:00",
  author: "Alex",
  message: "First screens",
  files: [],
  recorded_at: "2026-09-28T16:01:00+00:00",
  review: {
    run_id: "44444444-4444-4444-8444-444444444444",
    reviewed_at: "2026-09-28T16:05:00+00:00",
    verdict: "ALIGNED",
    summary: "The code follows the design.",
  },
  decision: { kind: "ALIGNED", decided_at: "2026-09-28T17:00:00+00:00", note: null },
};

const ALIGNMENT: AlignmentPayload = {
  project_id: PROJECT_ID,
  reference: {
    requirements: { version_id: "requirements", version_number: 2, content_hash: "a".repeat(64) },
    design: {
      version_id: SELECTED_DESIGN_VERSION.id,
      version_number: 2,
      content_hash: SELECTED_DESIGN_VERSION.content_hash,
      alternative_code: "DES-001",
    },
  },
  aligned: {
    commit: ALIGNED_COMMIT,
    decided_at: "2026-09-28T17:00:00+00:00",
    requirements_version_number: 2,
    design_version_number: 2,
  },
  pending_changes: 2,
  latest_change: NEWEST,
  tasks: [
    {
      code: "TSK-001",
      text: "Show again the message of an empty day.",
      about: { requirements: ["REQ-003"], screens: ["SCR-001"] },
      from_commit: NEWEST_COMMIT,
      created_at: "2026-09-29T08:10:00+00:00",
      status: "OPEN",
    },
  ],
  review_available: true,
};

const RUN: ChangeReviewRunPayload = {
  id: RUN_ID,
  commit: NEWEST_COMMIT,
  reviewed_at: "2026-09-29T08:05:00+00:00",
  locale: "en-US",
  reference: {
    requirements_version_number: 2,
    design_version_number: 2,
    alternative_code: "DES-001",
  },
  critiques: [
    {
      twin_id: "55555555-5555-4555-8555-555555555555",
      twin_name: "Reception staff",
      verdict: "CONCERN",
      summary: "I can see the reservations, but an empty day now shows a blank page.",
      findings: [
        {
          severity: "HIGH",
          text: "An empty day shows nothing, so I think that the list failed.",
          about: { requirement: "REQ-003", screen: "SCR-001", file: "src/reservations.js" },
          action: "Show a sentence when there is no reservation.",
        },
        {
          severity: "LOW",
          text: "The dates use a long format.",
          about: { requirement: null, screen: "SCR-002", file: null },
          action: null,
        },
      ],
    },
    {
      twin_id: "66666666-6666-4666-8666-666666666666",
      twin_name: "Restaurant manager",
      verdict: "FINE",
      summary: "The list of the day is what I need.",
      findings: [
        {
          severity: "MEDIUM",
          text: "I would like the total of the guests.",
          about: { requirement: "REQ-009", screen: null, file: null },
          action: "Add the total of the guests under the list.",
        },
      ],
    },
  ],
  alignment: {
    status: "CODE_DRIFT",
    summary: "The empty state of the list was removed.",
    affected: { requirements: ["REQ-003"], screens: ["SCR-001"] },
    design_request: null,
    requirements_request: null,
    code_tasks: ["Show again the message of an empty day.", "Keep the short format of the dates."],
  },
  cost_microusd: 650000,
};

const EMPTY: AlignmentPayload = {
  ...ALIGNMENT,
  aligned: null,
  pending_changes: 0,
  latest_change: null,
  tasks: [],
};

function requirementsVersion(): RequirementsSpecificationVersionPayload {
  return {
    id: "requirements",
    project_id: PROJECT_ID,
    version_number: 2,
    specification: {
      requirements: [
        { code: "REQ-003", title: "Guests are checked in quickly" },
        { code: "REQ-004", title: "The manager sees the day" },
      ],
    },
  } as unknown as RequirementsSpecificationVersionPayload;
}

function changes(...items: CodeChangePayload[]): CodeChangeListPayload {
  return { items };
}

function developmentApi(overrides: Partial<CodeChangesApi> = {}) {
  return {
    alignment: vi.fn<CodeChangesApi["alignment"]>(async () => ALIGNMENT),
    changes: vi.fn<CodeChangesApi["changes"]>(async () => changes(NEWEST, SECOND, ALIGNED)),
    reviews: vi.fn<CodeChangesApi["reviews"]>(async () => ({ items: [RUN] })),
    ...overrides,
  };
}

function mountPanel(api: CodeChangesApi, locale: Locale = "en") {
  return mount(ProjectDevelopmentPanel, {
    global: { plugins: [createAppI18n(locale)] },
    props: {
      projectId: PROJECT_ID,
      locale,
      authorize: (operation) => operation(TOKEN),
      api,
    },
    attachTo: document.body,
  });
}

function words(value: string): string {
  return value.replace(/\s+/g, " ").trim();
}

function spoken(element: { text(): string }): string {
  return words(element.text());
}

function dated(value: string, locale: Locale): string {
  return new Intl.DateTimeFormat(locale === "it" ? "it-IT" : "en-GB", {
    dateStyle: "medium",
    timeStyle: "short",
  }).format(Date.parse(value));
}

describe("ProjectDevelopmentPanel", () => {
  beforeEach(() => {
    setActivePinia(createPinia());
    document.body.innerHTML = "";
    useDesignStore().$patch({ projectId: PROJECT_ID, current: SELECTED_DESIGN_VERSION });
    useRequirementsStore().$patch({ projectId: PROJECT_ID, current: requirementsVersion() });
  });

  it("reads the alignment, every recorded change and the latest run of the newest reviewed commit", async () => {
    const api = developmentApi();
    const wrapper = mountPanel(api);
    await flushPromises();

    expect(api.alignment).toHaveBeenCalledWith(PROJECT_ID, TOKEN);
    expect(api.changes).toHaveBeenCalledWith(PROJECT_ID, TOKEN);
    expect(api.reviews).toHaveBeenCalledWith(PROJECT_ID, NEWEST_COMMIT, TOKEN);
    expect(wrapper.get("h2").text()).toBe("Development outside the Studio");
    expect(spoken(wrapper.get('[data-testid="development-terminal"]'))).toBe(
      "Reviews and decisions are made from the terminal with ut align: this page only shows their result.",
    );
    expect(wrapper.get('[data-testid="development-terminal"] code').text()).toBe("ut align");
    wrapper.unmount();
  });

  it("shows the approved reference with the title of the chosen alternative and the aligned point", async () => {
    const wrapper = mountPanel(developmentApi());
    await flushPromises();

    expect(wrapper.get('[data-testid="development-reference-requirements"]').text()).toBe(
      "version 2",
    );
    expect(spoken(wrapper.get('[data-testid="development-reference-design"]'))).toBe(
      "version 2 · DES-001 · Guided reservation flow",
    );
    expect(spoken(wrapper.get('[data-testid="development-aligned"]'))).toBe(
      words(`commit a1a1a1a · ${dated("2026-09-28T17:00:00+00:00", "en")}`),
    );
    expect(wrapper.find('[data-testid="development-no-model"]').exists()).toBe(false);
    expect(wrapper.find('[data-testid="development-empty"]').exists()).toBe(false);
    wrapper.unmount();
  });

  it("lists the commits after the aligned point with their verdict and decision in words", async () => {
    const wrapper = mountPanel(developmentApi());
    await flushPromises();

    expect(wrapper.get('[data-testid="development-pending"] h3').text()).toBe(
      "Pending commits (2)",
    );
    const rows = wrapper.findAll('[data-testid="development-change"]');
    expect(rows).toHaveLength(2);
    expect(spoken(rows[0]!.get("p"))).toBe(
      words(`c0ffee1 · ${dated(NEWEST.committed_at, "en")} · 2 files`),
    );
    expect(rows[0]!.get('[data-testid="development-change-title"]').text()).toBe(
      "Show the reservations of the day",
    );
    const verdict = rows[0]!.get('[data-testid="development-change-verdict"]');
    expect(verdict.text()).toBe("Review: the code should change");
    expect(verdict.attributes("data-status")).toBe("failed");
    const decision = rows[0]!.get('[data-testid="development-change-decision"]');
    expect(decision.text()).toBe("Decision: tasks for the code");
    expect(decision.attributes("data-status")).toBe("blocked");
    expect(spoken(rows[1]!.get("p"))).toBe(
      words(`b0b0b0b · ${dated(SECOND.committed_at, "en")} · 1 file`),
    );
    expect(rows[1]!.get('[data-testid="development-change-verdict"]').text()).toBe(
      "Not reviewed yet",
    );
    expect(rows[1]!.get('[data-testid="development-change-decision"]').text()).toBe(
      "No decision yet",
    );
    expect(wrapper.text()).not.toContain("First screens");
    wrapper.unmount();
  });

  it("lists the open tasks with the codes they name next to their titles", async () => {
    const wrapper = mountPanel(developmentApi());
    await flushPromises();

    expect(wrapper.get('[data-testid="development-tasks"] h3').text()).toBe(
      "Open tasks for the code (1)",
    );
    const task = wrapper.get('[data-testid="development-task"]');
    expect(task.get('[data-testid="development-task-code"]').text()).toBe("TSK-001");
    expect(spoken(task.get("p"))).toBe("TSK-001 · Show again the message of an empty day.");
    expect(task.findAll('[data-testid="development-subject"]').map(spoken)).toEqual([
      "REQ-003 · Guests are checked in quickly",
      "SCR-001 · Availability",
    ]);
    wrapper.unmount();
  });

  it("shows the latest run: one block per twin with the findings, then the verdict of the model", async () => {
    const wrapper = mountPanel(developmentApi());
    await flushPromises();

    const run = wrapper.get('[data-testid="development-run"]');
    expect(run.get("h3").text()).toBe("Latest review, commit c0ffee1");
    expect(spoken(run.get('[data-testid="development-run-meta"]'))).toBe(
      words(
        `${dated(RUN.reviewed_at, "en")} · checked against requirements version 2 and design version 2 (DES-001)`,
      ),
    );

    const critiques = run.findAll('[data-testid="development-critique"]');
    expect(critiques).toHaveLength(2);
    expect(critiques.map((critique) => critique.get("h4").text())).toEqual([
      "Reception staff",
      "Restaurant manager",
    ]);
    const concern = critiques[0]!.get('[data-testid="development-critique-verdict"]');
    expect(concern.text()).toBe("Some concerns");
    expect(concern.attributes("data-status")).toBe("blocked");
    expect(critiques[0]!.text()).toContain(
      "I can see the reservations, but an empty day now shows a blank page.",
    );
    expect(critiques[0]!.text()).toContain("AI proposal, not validated");
    const findings = critiques[0]!.findAll('[data-testid="development-finding"]');
    expect(findings).toHaveLength(2);
    expect(findings[0]!.get('[data-testid="development-finding-severity"]').text()).toBe("Major");
    expect(spoken(findings[0]!)).toContain(
      "Major An empty day shows nothing, so I think that the list failed.",
    );
    expect(findings[0]!.findAll('[data-testid="development-subject"]').map(spoken)).toEqual([
      "REQ-003 · Guests are checked in quickly",
      "SCR-001 · Availability",
      "src/reservations.js",
    ]);
    expect(findings[0]!.findAll('[data-testid="development-subject"]')[2]!.get("code").text()).toBe(
      "src/reservations.js",
    );
    expect(spoken(findings[0]!)).toContain(
      "Suggested action: Show a sentence when there is no reservation.",
    );
    expect(findings[1]!.get('[data-testid="development-finding-severity"]').text()).toBe("Minor");
    expect(findings[1]!.findAll('[data-testid="development-subject"]').map(spoken)).toEqual([
      "SCR-002 · Reservation",
    ]);
    expect(findings[1]!.text()).not.toContain("Suggested action");

    const fine = critiques[1]!.get('[data-testid="development-critique-verdict"]');
    expect(fine.text()).toBe("No concerns");
    expect(fine.attributes("data-status")).toBe("approved");
    const moderate = critiques[1]!.get('[data-testid="development-finding"]');
    expect(moderate.get('[data-testid="development-finding-severity"]').text()).toBe("Moderate");
    expect(moderate.findAll('[data-testid="development-subject"]').map(spoken)).toEqual([
      "REQ-009",
    ]);

    const verdict = run.get('[data-testid="development-verdict"]');
    expect(verdict.get("h4").text()).toBe("The model's verdict");
    expect(verdict.get('[data-testid="development-verdict-status"]').text()).toBe(
      "Review: the code should change",
    );
    expect(verdict.text()).toContain(
      "The code moves away from the approved requirements or design: the code should change.",
    );
    expect(verdict.text()).toContain("The empty state of the list was removed.");
    expect(verdict.findAll('[data-testid="development-subject"]').map(spoken)).toEqual([
      "REQ-003 · Guests are checked in quickly",
      "SCR-001 · Availability",
    ]);
    expect(verdict.findAll('[data-testid="development-code-task"]').map(spoken)).toEqual([
      "Show again the message of an empty day.",
      "Keep the short format of the dates.",
    ]);
    expect(spoken(verdict.get('[data-testid="development-code-tasks"]'))).toContain(
      "They become open tasks only when you decide so with ut align.",
    );
    expect(verdict.find('[data-testid="development-design-request"]').exists()).toBe(false);
    expect(verdict.find('[data-testid="development-requirements-request"]').exists()).toBe(false);
    wrapper.unmount();
  });

  it("never offers a button that starts a review or a decision", async () => {
    const wrapper = mountPanel(developmentApi());
    await flushPromises();

    expect(wrapper.findAll("button").map((button) => button.attributes("data-testid"))).toEqual([
      "development-refresh",
      "step-technical-details-toggle",
    ]);
    expect(wrapper.get('[data-testid="development-refresh"]').attributes("aria-label")).toBe(
      "Refresh the development state",
    );
    wrapper.unmount();
  });

  it.each([
    [
      "DESIGN_OUTDATED",
      "development-design-request",
      "Design change to request",
      "The change is a sound evolution: the design should get a new version.",
    ],
    [
      "REQUIREMENTS_OUTDATED",
      "development-requirements-request",
      "Requirements change to request",
      "The change is a sound evolution: the requirements should get a new version.",
    ],
  ] as const)("quotes the request of a %s verdict", async (status, testId, label, sentence) => {
    const request = "Add a screen that shows the guests waiting for a table.";
    const run: ChangeReviewRunPayload = {
      ...RUN,
      alignment: {
        ...RUN.alignment,
        status,
        design_request: status === "DESIGN_OUTDATED" ? request : null,
        requirements_request: status === "REQUIREMENTS_OUTDATED" ? request : null,
        code_tasks: [],
      },
    };
    const wrapper = mountPanel(developmentApi({ reviews: async () => ({ items: [run] }) }));
    await flushPromises();

    const verdict = wrapper.get('[data-testid="development-verdict"]');
    const quoted = verdict.get(`[data-testid="${testId}"]`);
    expect(quoted.get("p").text()).toBe(label);
    expect(quoted.get("blockquote").text()).toBe(request);
    expect(verdict.text()).toContain(sentence);
    expect(
      verdict.get('[data-testid="development-verdict-status"]').attributes("data-status"),
    ).toBe("blocked");
    expect(verdict.find('[data-testid="development-code-tasks"]').exists()).toBe(false);
    wrapper.unmount();
  });

  it("speaks Italian", async () => {
    const wrapper = mountPanel(developmentApi(), "it");
    await flushPromises();

    expect(wrapper.get("h2").text()).toBe("Sviluppo fuori dallo Studio");
    expect(spoken(wrapper.get('[data-testid="development-terminal"]'))).toBe(
      "Revisioni e decisioni si fanno dal terminale con ut align: questa pagina ne mostra solo il risultato.",
    );
    expect(wrapper.get('[data-testid="development-reference-requirements"]').text()).toBe(
      "versione 2",
    );
    expect(wrapper.get('[data-testid="development-pending"] h3').text()).toBe(
      "Commit in attesa (2)",
    );
    const rows = wrapper.findAll('[data-testid="development-change"]');
    expect(spoken(rows[0]!.get("p"))).toBe(
      words(`c0ffee1 · ${dated(NEWEST.committed_at, "it")} · 2 file`),
    );
    expect(rows[0]!.get('[data-testid="development-change-verdict"]').text()).toBe(
      "Revisione: va cambiato il codice",
    );
    expect(rows[0]!.get('[data-testid="development-change-decision"]').text()).toBe(
      "Decisione: compiti per il codice",
    );
    expect(rows[1]!.get('[data-testid="development-change-verdict"]').text()).toBe(
      "Non ancora rivisto",
    );
    expect(wrapper.get('[data-testid="development-tasks"] h3').text()).toBe(
      "Compiti aperti per il codice (1)",
    );
    const run = wrapper.get('[data-testid="development-run"]');
    expect(run.get("h3").text()).toBe("Ultima revisione, commit c0ffee1");
    expect(spoken(run.get('[data-testid="development-run-meta"]'))).toBe(
      words(
        `${dated(RUN.reviewed_at, "it")} · confrontata con i requisiti versione 2 e il design versione 2 (DES-001)`,
      ),
    );
    expect(run.get('[data-testid="development-critique-verdict"]').text()).toBe("Qualche dubbio");
    expect(run.get('[data-testid="development-finding-severity"]').text()).toBe("Importante");
    expect(spoken(run.get('[data-testid="development-finding"]'))).toContain(
      "Azione suggerita: Show a sentence when there is no reservation.",
    );
    const verdict = run.get('[data-testid="development-verdict"]');
    expect(verdict.get("h4").text()).toBe("Il verdetto del modello");
    expect(verdict.text()).toContain(
      "Il codice si allontana dai requisiti o dal design approvati: va cambiato il codice.",
    );
    expect(spoken(verdict.get('[data-testid="development-code-tasks"]'))).toContain(
      "Compiti proposti per il codice",
    );
    expect(wrapper.get('[data-testid="development-refresh"]').text()).toBe("Aggiorna");
    wrapper.unmount();
  });

  it.each([
    [
      "en",
      "No commit recorded yet. Record the first one with ut align or ut watch.",
      "No commit aligned yet",
    ],
    [
      "it",
      "Nessun commit registrato. Registra il primo con ut align o ut watch.",
      "Nessun commit ancora allineato",
    ],
  ] as const)("says in %s that no commit is recorded yet", async (locale, empty, aligned) => {
    const api = developmentApi({
      alignment: vi.fn<CodeChangesApi["alignment"]>(async () => EMPTY),
      changes: vi.fn<CodeChangesApi["changes"]>(async () => changes()),
    });
    const wrapper = mountPanel(api, locale);
    await flushPromises();

    const sentence = wrapper.get('[data-testid="development-empty"]');
    expect(spoken(sentence)).toBe(empty);
    expect(sentence.findAll("code").map((item) => item.text())).toEqual(["ut align", "ut watch"]);
    expect(wrapper.get('[data-testid="development-aligned"]').text()).toBe(aligned);
    expect(wrapper.find('[data-testid="development-pending"]').exists()).toBe(false);
    expect(wrapper.find('[data-testid="development-tasks"]').exists()).toBe(false);
    expect(wrapper.find('[data-testid="development-run"]').exists()).toBe(false);
    expect(api.reviews).not.toHaveBeenCalled();
    wrapper.unmount();
  });

  it.each([
    ["en", "On this Studio the twins cannot review the code: connect a model."],
    ["it", "In questo Studio i twin non possono rivedere il codice: collega un modello."],
  ] as const)(
    "says in %s when the Studio has no model to review the code",
    async (locale, text) => {
      const wrapper = mountPanel(
        developmentApi({ alignment: async () => ({ ...ALIGNMENT, review_available: false }) }),
        locale,
      );
      await flushPromises();

      expect(wrapper.get('[data-testid="development-no-model"]').text()).toBe(text);
      expect(wrapper.findAll('[data-testid="development-change"]')).toHaveLength(2);
      wrapper.unmount();
    },
  );

  it("says when the requirements or the design are not approved", async () => {
    const api = developmentApi({
      alignment: async () => ({ ...EMPTY, reference: { requirements: null, design: null } }),
      changes: async () => changes(),
    });
    const english = mountPanel(api);
    await flushPromises();
    expect(english.get('[data-testid="development-reference-requirements"]').text()).toBe(
      "not approved yet",
    );
    expect(english.get('[data-testid="development-reference-design"]').text()).toBe(
      "not approved yet",
    );
    english.unmount();

    setActivePinia(createPinia());
    const italian = mountPanel(api, "it");
    await flushPromises();
    expect(italian.get('[data-testid="development-reference-requirements"]').text()).toBe(
      "non ancora approvati",
    );
    expect(italian.get('[data-testid="development-reference-design"]').text()).toBe(
      "non ancora approvato",
    );
    italian.unmount();
  });

  it("shows the code of the alternative alone when the design of the page is not loaded", async () => {
    useDesignStore().$patch({ projectId: "another-project" });
    const wrapper = mountPanel(developmentApi());
    await flushPromises();

    expect(spoken(wrapper.get('[data-testid="development-reference-design"]'))).toBe(
      "version 2 · DES-001",
    );
    expect(
      wrapper
        .get('[data-testid="development-task"]')
        .findAll('[data-testid="development-subject"]')
        .map(spoken),
    ).toEqual(["REQ-003 · Guests are checked in quickly", "SCR-001"]);
    wrapper.unmount();
  });

  it("says that no commit has been reviewed yet without asking for a run", async () => {
    const api = developmentApi({
      changes: vi.fn(async () => changes(SECOND, { ...ALIGNED, review: null })),
    });
    const wrapper = mountPanel(api);
    await flushPromises();

    const run = wrapper.get('[data-testid="development-run"]');
    expect(run.get("h3").text()).toBe("Latest review");
    expect(run.get('[data-testid="development-no-run"]').text()).toBe(
      "No commit has been reviewed yet.",
    );
    expect(wrapper.findAll('[data-testid="development-change"]')).toHaveLength(1);
    expect(api.reviews).not.toHaveBeenCalled();
    wrapper.unmount();
  });

  it("reloads the state with the refresh button and announces the region politely", async () => {
    const newer: CodeChangePayload = {
      ...SECOND,
      commit: "d0d0d0d1d0d0d0d0d0d0d0d0d0d0d0d0d0d0d0d0",
      message: "Add the waiting list",
      review: null,
      decision: null,
    };
    let release: (value: AlignmentPayload) => void = () => undefined;
    const later = new Promise<AlignmentPayload>((resolve) => {
      release = resolve;
    });
    const alignment = vi
      .fn<CodeChangesApi["alignment"]>()
      .mockResolvedValueOnce(ALIGNMENT)
      .mockImplementationOnce(() => later);
    const reads = vi
      .fn<CodeChangesApi["changes"]>()
      .mockResolvedValueOnce(changes(NEWEST, SECOND, ALIGNED))
      .mockResolvedValueOnce(changes(newer, NEWEST, SECOND, ALIGNED));
    const api = developmentApi({ alignment, changes: reads });
    const wrapper = mountPanel(api);
    await flushPromises();

    const region = wrapper.get('[data-testid="development-state"]');
    expect(region.attributes("aria-live")).toBe("polite");
    expect(region.attributes("aria-busy")).toBeUndefined();
    expect(wrapper.findAll('[data-testid="development-change"]')).toHaveLength(2);

    await wrapper.get('[data-testid="development-refresh"]').trigger("click");

    expect(wrapper.get('[data-testid="development-refresh"]').attributes("disabled")).toBeDefined();
    expect(wrapper.get('[data-testid="development-state"]').attributes("aria-busy")).toBe("true");
    expect(wrapper.findAll('[data-testid="development-change"]')).toHaveLength(2);

    release({ ...ALIGNMENT, pending_changes: 3, latest_change: newer });
    await flushPromises();

    expect(alignment).toHaveBeenCalledTimes(2);
    expect(reads).toHaveBeenCalledTimes(2);
    expect(api.reviews).toHaveBeenCalledTimes(2);
    expect(wrapper.get('[data-testid="development-pending"] h3').text()).toBe(
      "Pending commits (3)",
    );
    expect(wrapper.get('[data-testid="development-change-title"]').text()).toBe(
      "Add the waiting list",
    );
    expect(
      wrapper.get('[data-testid="development-refresh"]').attributes("disabled"),
    ).toBeUndefined();
    wrapper.unmount();
  });

  it("says that it is loading until the Studio answers", async () => {
    const wrapper = mountPanel(
      developmentApi({ alignment: vi.fn(() => new Promise<never>(() => undefined)) }),
      "it",
    );
    await flushPromises();

    expect(wrapper.get('[data-testid="development-loading"]').text()).toBe(
      "Carico lo stato dello sviluppo…",
    );
    expect(wrapper.get('[data-testid="development-state"]').attributes("aria-busy")).toBe("true");
    expect(wrapper.get('[data-testid="development-refresh"]').attributes("disabled")).toBeDefined();
    expect(wrapper.find('[data-testid="development-technical-details"]').exists()).toBe(false);
    wrapper.unmount();
  });

  it("says that the latest run is loading while the Studio reads it", async () => {
    const wrapper = mountPanel(
      developmentApi({
        reviews: vi.fn(() => new Promise<ChangeReviewListPayload>(() => undefined)),
      }),
    );
    await flushPromises();

    expect(wrapper.get('[data-testid="development-run-loading"]').text()).toBe(
      "Loading the latest review…",
    );
    expect(wrapper.findAll('[data-testid="development-change"]')).toHaveLength(2);
    wrapper.unmount();
  });

  it("says when the Studio lists no run for a reviewed commit", async () => {
    const wrapper = mountPanel(developmentApi({ reviews: async () => ({ items: [] }) }));
    await flushPromises();

    expect(wrapper.get('[data-testid="development-run-loading"]').text()).toBe(
      "The latest review is not available.",
    );
    wrapper.unmount();
  });

  it("explains a failed read and recovers with the refresh button", async () => {
    let fail = true;
    const api = developmentApi({
      alignment: vi.fn(async () => {
        if (fail) {
          throw new CodeChangesApiError("The code change request failed", {
            status: 404,
            code: "PROJECT_NOT_FOUND",
            payload: null,
          });
        }
        return ALIGNMENT;
      }),
    });
    const wrapper = mountPanel(api);
    await flushPromises();

    const error = wrapper.get('[data-testid="development-error"]');
    expect(error.attributes("role")).toBe("alert");
    expect(error.get("p").text()).toBe("The development state could not be loaded.");
    expect(error.get("code").text()).toBe("PROJECT_NOT_FOUND");
    expect(wrapper.find('[data-testid="development-loading"]').exists()).toBe(false);
    expect(wrapper.find('[data-testid="development-reference"]').exists()).toBe(false);

    fail = false;
    await wrapper.get('[data-testid="development-refresh"]').trigger("click");
    await flushPromises();

    expect(wrapper.find('[data-testid="development-error"]').exists()).toBe(false);
    expect(wrapper.findAll('[data-testid="development-change"]')).toHaveLength(2);
    wrapper.unmount();
  });

  it("explains a latest run that cannot be read and keeps the rest of the state", async () => {
    const wrapper = mountPanel(
      developmentApi({
        reviews: async () => {
          throw new CodeChangesApiError("The code change request failed", {
            status: 409,
            code: "CODE_CHANGE_AMBIGUOUS",
            payload: null,
          });
        },
      }),
      "it",
    );
    await flushPromises();

    const error = wrapper.get('[data-testid="development-run-error"]');
    expect(error.attributes("role")).toBe("alert");
    expect(error.get("p").text()).toBe("Non è stato possibile caricare l'ultima revisione.");
    expect(error.get("code").text()).toBe("CODE_CHANGE_AMBIGUOUS");
    expect(wrapper.findAll('[data-testid="development-change"]')).toHaveLength(2);
    expect(wrapper.findAll('[data-testid="development-task"]')).toHaveLength(1);
    wrapper.unmount();
  });

  it("puts the counts and the latest run in its own row of technical details", async () => {
    const wrapper = mountPanel(developmentApi());
    await flushPromises();

    const details = wrapper.get('[data-testid="development-technical-details"]');
    expect(wrapper.find('[data-testid="step-technical-details"]').exists()).toBe(false);
    await details.get('[data-testid="step-technical-details-toggle"]').trigger("click");

    const content = details.get('[data-testid="step-technical-details-content"]');
    expect(content.findAll("dt").map((item) => item.text())).toEqual([
      "Recorded commits",
      "Pending commits",
      "Open tasks",
      "Latest review",
    ]);
    expect(content.findAll("dd").map((item) => item.text())).toEqual(["3", "2", "1", RUN_ID]);
    wrapper.unmount();
  });

  it("reads the state of the new project when the project changes", async () => {
    const api = developmentApi();
    const wrapper = mountPanel(api);
    await flushPromises();

    await wrapper.setProps({ projectId: SECOND_PROJECT_ID });
    await flushPromises();

    expect(api.alignment).toHaveBeenLastCalledWith(SECOND_PROJECT_ID, TOKEN);
    expect(api.changes).toHaveBeenLastCalledWith(SECOND_PROJECT_ID, TOKEN);
    expect(api.reviews).toHaveBeenLastCalledWith(SECOND_PROJECT_ID, NEWEST_COMMIT, TOKEN);
    expect(spoken(wrapper.get('[data-testid="development-reference-design"]'))).toBe(
      "version 2 · DES-001",
    );
    wrapper.unmount();
  });

  it("has no axe violations with a full development state", async () => {
    const wrapper = mountPanel(developmentApi(), "it");
    await flushPromises();

    await expectAccessible(wrapper.element);
    wrapper.unmount();
  });

  it("has no axe violations without commits and without a model", async () => {
    const wrapper = mountPanel(
      developmentApi({
        alignment: async () => ({ ...EMPTY, review_available: false }),
        changes: async () => changes(),
      }),
    );
    await flushPromises();

    await expectAccessible(wrapper.element);
    wrapper.unmount();
  });
});
