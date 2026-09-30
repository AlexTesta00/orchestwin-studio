import { createPinia, setActivePinia } from "pinia";

import { flushPromises, mount } from "@vue/test-utils";

import { beforeEach, describe, expect, it, vi } from "vitest";

import ProjectAcceptanceTestsPanel from "./ProjectAcceptanceTestsPanel.vue";
import { createAppI18n } from "@/i18n";
import { expectAccessible } from "@/test/axe";
import { SELECTED_DESIGN_VERSION } from "@/test/designFixtures";

import { AcceptanceTestsApiError, type AcceptanceTestsApi } from "../api/acceptanceTests";
import { useDesignStore } from "../stores/design";
import { useRequirementsStore } from "../stores/requirements";
import type {
  AcceptanceTestsOverviewPayload,
  TestResultPayload,
  TestRunPayload,
} from "../types/acceptanceTests";
import type { RequirementsSpecificationVersionPayload } from "../types/requirements";

type Locale = "en" | "it";

const PROJECT_ID = SELECTED_DESIGN_VERSION.project_id;
const SECOND_PROJECT_ID = "22222222-2222-4222-8222-222222222222";
const TOKEN = "test-token-not-real";
const RUN_ID = "33333333-3333-4333-8333-333333333333";

function result(code: string, browser: "chrome" | "firefox"): TestResultPayload {
  return {
    path: {
      code,
      heading: `Path ${code}`,
      criteria: ["AC-001"],
      steps: [{ action: "OPEN", target: null, value: "/", expect: null }],
    },
    browser,
    status: "PASSED",
    seconds: 3.5,
    steps: [
      {
        index: 1,
        status: "DONE",
        detail: null,
        url: "http://127.0.0.1:50123/",
        title: "Guests",
        screenshot: `${code}/${browser}/01.png`,
      },
    ],
    page_text: "Guests of the day",
  };
}

const RUN: TestRunPayload = {
  id: RUN_ID,
  started_at: "2026-09-29T10:00:00+00:00",
  finished_at: "2026-09-29T10:04:00+00:00",
  recorded_at: "2026-09-29T10:04:05+00:00",
  application: { kind: "STATIC", address: "dist" },
  browsers: [
    { name: "chrome", version: "151.0.7922.76" },
    { name: "firefox", version: "156.0.1" },
  ],
  reference: {
    requirements_version_number: 2,
    design_version_number: 2,
    alternative_code: "DES-001",
  },
  summary: { passed: 2, failed: 1, blocked: 1, not_covered: 1, not_run: 1 },
  criteria: [
    { code: "AC-001", status: "PASSED", paths: ["TP-001"] },
    { code: "AC-002", status: "FAILED", paths: ["TP-002"] },
    { code: "AC-003", status: "BLOCKED", paths: ["TP-003", "TP-004"] },
    { code: "AC-004", status: "NOT_COVERED", paths: [] },
    { code: "AC-005", status: "PASSED", paths: ["TP-005"] },
    { code: "AC-006", status: "NOT_RUN", paths: [] },
  ],
  not_covered: [
    { criterion: "AC-004", reason: "The criterion asks for a manual check of the printed list." },
  ],
  results: [result("TP-001", "chrome"), result("TP-001", "firefox")],
  critiques: [
    {
      twin_id: "55555555-5555-4555-8555-555555555555",
      twin_name: "Reception staff",
      verdict: "CONCERN",
      summary: "Most of the list works, but a new guest does not show where I look for it.",
      findings: [
        {
          severity: "HIGH",
          text: "A new guest did not appear at the top of the list, so I would add the same person twice.",
          about: { criterion: "AC-002", requirement: "REQ-003", screen: "SCR-001" },
          action: "Show the new guest at the top of the list.",
        },
        {
          severity: "LOW",
          text: "The search worked in both browsers.",
          about: { criterion: "AC-005", requirement: null, screen: null },
          action: null,
        },
      ],
    },
    {
      twin_id: "66666666-6666-4666-8666-666666666666",
      twin_name: "Restaurant manager",
      verdict: "FINE",
      summary: "The list of the day is what I need.",
      findings: [],
    },
  ],
  reviewed_at: "2026-09-29T10:06:00+00:00",
  cost_microusd: 500000,
};

function overview(
  latest: TestRunPayload | null = RUN,
  planAvailable = true,
): AcceptanceTestsOverviewPayload {
  return {
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
    plan_available: planAvailable,
    plans: latest === null ? 0 : 1,
    runs: latest === null ? 0 : 1,
    latest_run: latest,
  };
}

function requirementsVersion(): RequirementsSpecificationVersionPayload {
  return {
    id: "requirements",
    project_id: PROJECT_ID,
    version_number: 2,
    specification: {
      requirements: [{ code: "REQ-003", title: "Guests are checked in quickly" }],
      acceptance_criteria: [
        { code: "AC-001", statement: "The owner sees the guests of the day in one list." },
        { code: "AC-002", statement: "A new guest appears at the top of the list." },
        { code: "AC-003", statement: "A guest can be marked as arrived from the list." },
        { code: "AC-004", statement: "The printed list matches the screen." },
        { code: "AC-005", statement: "The list can be searched by name." },
        { code: "AC-006", statement: "The list opens in less than two seconds." },
      ],
    },
  } as unknown as RequirementsSpecificationVersionPayload;
}

function testsApi(read: AcceptanceTestsApi["overview"] = async () => overview()) {
  return { overview: vi.fn<AcceptanceTestsApi["overview"]>(read) };
}

function mountPanel(api: AcceptanceTestsApi, locale: Locale = "en") {
  return mount(ProjectAcceptanceTestsPanel, {
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

describe("ProjectAcceptanceTestsPanel", () => {
  beforeEach(() => {
    setActivePinia(createPinia());
    document.body.innerHTML = "";
    useDesignStore().$patch({ projectId: PROJECT_ID, current: SELECTED_DESIGN_VERSION });
    useRequirementsStore().$patch({ projectId: PROJECT_ID, current: requirementsVersion() });
  });

  it.each([
    [
      "en",
      "Acceptance tests",
      "No test run is recorded yet. The tests run from the terminal: launch ut test in the folder of your project.",
    ],
    [
      "it",
      "Verifica dei criteri",
      "Non è ancora registrata nessuna verifica. I test partono dal terminale: lancia ut test nella cartella del tuo progetto.",
    ],
  ] as const)(
    "says in %s that no run is recorded yet and that the tests run with ut test",
    async (locale, title, sentence) => {
      const api = testsApi(async () => overview(null));
      const wrapper = mountPanel(api, locale);
      await flushPromises();

      expect(api.overview).toHaveBeenCalledWith(PROJECT_ID, TOKEN);
      const section = wrapper.get('[data-testid="acceptance-panel"]');
      expect(section.element.tagName).toBe("SECTION");
      expect(section.attributes("aria-labelledby")).toBe("acceptance-tests-title");
      expect(wrapper.get("#acceptance-tests-title").text()).toBe(title);
      const empty = wrapper.get('[data-testid="acceptance-empty"]');
      expect(spoken(empty)).toBe(sentence);
      expect(empty.findAll("code").map((item) => item.text())).toEqual(["ut test"]);
      expect(wrapper.find('[data-testid="acceptance-run"]').exists()).toBe(false);
      expect(wrapper.find('[data-testid="acceptance-terminal"]').exists()).toBe(false);
      expect(wrapper.find('[data-testid="acceptance-no-model"]').exists()).toBe(false);
      expect(wrapper.find('[data-testid="acceptance-loading"]').exists()).toBe(false);
      wrapper.unmount();
    },
  );

  it.each([
    ["en", "Loading the acceptance tests…"],
    ["it", "Carico la verifica dei criteri…"],
  ] as const)("says in %s that it is loading until the Studio answers", async (locale, text) => {
    const wrapper = mountPanel(
      testsApi(() => new Promise<never>(() => undefined)),
      locale,
    );
    await flushPromises();

    expect(wrapper.get('[data-testid="acceptance-loading"]').text()).toBe(text);
    expect(wrapper.get('[data-testid="acceptance-state"]').attributes("aria-busy")).toBe("true");
    expect(wrapper.get('[data-testid="acceptance-state"]').attributes("aria-live")).toBe("polite");
    expect(wrapper.find('[data-testid="acceptance-empty"]').exists()).toBe(false);
    wrapper.unmount();
  });

  it.each([
    ["en", "The acceptance tests could not be loaded (PROJECT_NOT_FOUND)."],
    ["it", "Non è stato possibile caricare la verifica dei criteri (PROJECT_NOT_FOUND)."],
  ] as const)("explains in %s a failed read with the code in brackets", async (locale, text) => {
    const wrapper = mountPanel(
      testsApi(async () => {
        throw new AcceptanceTestsApiError("The acceptance tests request failed", {
          status: 404,
          code: "PROJECT_NOT_FOUND",
          payload: null,
        });
      }),
      locale,
    );
    await flushPromises();

    const error = wrapper.get('[data-testid="acceptance-error"]');
    expect(error.attributes("role")).toBe("alert");
    expect(spoken(error)).toBe(text);
    expect(wrapper.find('[data-testid="acceptance-loading"]').exists()).toBe(false);
    expect(wrapper.find('[data-testid="acceptance-empty"]').exists()).toBe(false);
    expect(wrapper.get('[data-testid="acceptance-state"]').attributes("aria-busy")).toBeUndefined();
    wrapper.unmount();
  });

  it("explains a failed read without a code of the Studio", async () => {
    const wrapper = mountPanel(
      testsApi(async () => {
        throw new TypeError("Failed to fetch");
      }),
    );
    await flushPromises();

    expect(spoken(wrapper.get('[data-testid="acceptance-error"]'))).toBe(
      "The acceptance tests could not be loaded.",
    );
    wrapper.unmount();
  });

  it("shows when, where and on what the latest run happened", async () => {
    const wrapper = mountPanel(testsApi());
    await flushPromises();

    const run = wrapper.get('[data-testid="acceptance-run"]');
    expect(run.get("h3").text()).toBe("Latest run");
    expect(run.findAll("dt").map((item) => item.text())).toEqual([
      "When",
      "Browsers",
      "Application",
      "Checked against",
    ]);
    expect(run.get('[data-testid="acceptance-run-date"]').text()).toBe(
      dated(RUN.finished_at, "en"),
    );
    expect(spoken(run.get('[data-testid="acceptance-run-browsers"]'))).toBe(
      "Chrome 151.0.7922.76 and Firefox 156.0.1",
    );
    const application = run.get('[data-testid="acceptance-run-application"]');
    expect(spoken(application)).toBe("Static folder dist");
    expect(application.get("code").text()).toBe("dist");
    expect(run.get('[data-testid="acceptance-run-reference"]').text()).toBe(
      "requirements version 2, design version 2 (DES-001)",
    );
    wrapper.unmount();
  });

  it("shows the five numbers of the run as chips with words", async () => {
    const wrapper = mountPanel(testsApi());
    await flushPromises();

    const summary = wrapper.get('[data-testid="acceptance-summary"]');
    expect(summary.element.tagName).toBe("UL");
    expect(summary.attributes("aria-label")).toBe("Criteria by outcome");
    const chips = summary.findAll('[data-testid="acceptance-count"]');
    expect(chips.map((chip) => chip.text())).toEqual([
      "2 passed",
      "1 failed",
      "1 blocked",
      "1 not covered",
      "1 not run",
    ]);
    expect(chips.map((chip) => chip.attributes("data-count"))).toEqual([
      "passed",
      "failed",
      "blocked",
      "not_covered",
      "not_run",
    ]);
    expect(chips.map((chip) => chip.attributes("data-status"))).toEqual([
      "approved",
      "failed",
      "blocked",
      "pending",
      "pending",
    ]);
    expect(spoken(wrapper.get('[data-testid="acceptance-run"]'))).toContain(
      "Blocked: the test could not reach what it had to check.",
    );
    wrapper.unmount();
  });

  it("lists every criterion with its statement, its outcome in words and its paths", async () => {
    const wrapper = mountPanel(testsApi());
    await flushPromises();

    const region = wrapper.get('[data-testid="acceptance-criteria"]');
    expect(region.attributes("role")).toBe("region");
    expect(region.attributes("aria-labelledby")).toBe("acceptance-criteria-title");
    expect(wrapper.get("#acceptance-criteria-title").text()).toBe("Criteria (6)");
    expect(region.get("caption").text()).toBe(
      "Outcome of each acceptance criterion in the latest run",
    );
    const headers = region.findAll("thead th");
    expect(headers.map((item) => item.text())).toEqual([
      "Criterion",
      "What it asks",
      "Outcome",
      "Paths tried",
    ]);
    expect(headers.map((item) => item.attributes("scope"))).toEqual(["col", "col", "col", "col"]);

    const rows = region.findAll('[data-testid="acceptance-criterion"]');
    expect(rows).toHaveLength(6);
    expect(
      rows.map((row) => [
        row.get('[data-testid="acceptance-criterion-code"]').text(),
        row.get('[data-testid="acceptance-criterion-status"]').text(),
        row.get('[data-testid="acceptance-criterion-paths"]').text(),
      ]),
    ).toEqual([
      ["AC-001", "Passed", "TP-001"],
      ["AC-002", "Failed", "TP-002"],
      ["AC-003", "Blocked", "TP-003, TP-004"],
      ["AC-004", "Not covered", "—"],
      ["AC-005", "Passed", "TP-005"],
      ["AC-006", "Not run", "—"],
    ]);
    expect(
      rows.map((row) =>
        row.get('[data-testid="acceptance-criterion-status"]').attributes("data-status"),
      ),
    ).toEqual(["approved", "failed", "blocked", "pending", "approved", "pending"]);
    expect(rows[0]!.get("th").attributes("scope")).toBe("row");
    expect(rows[0]!.get('[data-testid="acceptance-criterion-statement"]').text()).toBe(
      "The owner sees the guests of the day in one list.",
    );
    const uncovered = rows[3]!;
    expect(uncovered.get('[data-testid="acceptance-criterion-statement"]').text()).toContain(
      "The printed list matches the screen.",
    );
    expect(spoken(uncovered.get('[data-testid="acceptance-criterion-reason"]'))).toBe(
      "Why: The criterion asks for a manual check of the printed list.",
    );
    expect(
      uncovered
        .get('[data-testid="acceptance-criterion-paths"] [role="img"]')
        .attributes("aria-label"),
    ).toBe("no path");
    expect(rows[5]!.find('[data-testid="acceptance-criterion-reason"]').exists()).toBe(false);
    wrapper.unmount();
  });

  it("shows the critiques of the twins with their verdict, summary and findings", async () => {
    const wrapper = mountPanel(testsApi());
    await flushPromises();

    const critiques = wrapper.get('[data-testid="acceptance-critiques"]');
    expect(critiques.get("h3").text()).toBe("What the twins say");
    expect(critiques.get('[data-testid="acceptance-reviewed"]').text()).toBe(
      `Comments from ${dated("2026-09-29T10:06:00+00:00", "en")}`,
    );
    const blocks = critiques.findAll('[data-testid="acceptance-critique"]');
    expect(blocks.map((block) => block.get("h4").text())).toEqual([
      "Reception staff",
      "Restaurant manager",
    ]);

    const concern = blocks[0]!.get('[data-testid="acceptance-critique-verdict"]');
    expect(concern.text()).toBe("Some concerns");
    expect(concern.attributes("data-status")).toBe("blocked");
    expect(blocks[0]!.text()).toContain(
      "Most of the list works, but a new guest does not show where I look for it.",
    );
    expect(blocks[0]!.text()).toContain("AI proposal, not validated");
    const findings = blocks[0]!.findAll('[data-testid="acceptance-finding"]');
    expect(findings).toHaveLength(2);
    const major = findings[0]!.get('[data-testid="acceptance-finding-severity"]');
    expect(major.text()).toBe("Major");
    expect(major.classes()).toContain("text-warn-on-night");
    expect(spoken(findings[0]!)).toContain(
      "Major A new guest did not appear at the top of the list, so I would add the same person twice.",
    );
    expect(findings[0]!.findAll('[data-testid="acceptance-subject"]').map(spoken)).toEqual([
      "AC-002",
      "REQ-003 · Guests are checked in quickly",
      "SCR-001 · Availability",
    ]);
    expect(spoken(findings[0]!)).toContain(
      "Suggested action: Show the new guest at the top of the list.",
    );
    const minor = findings[1]!.get('[data-testid="acceptance-finding-severity"]');
    expect(minor.text()).toBe("Minor");
    expect(minor.classes()).toContain("text-on-night-2");
    expect(findings[1]!.findAll('[data-testid="acceptance-subject"]').map(spoken)).toEqual([
      "AC-005",
    ]);
    expect(findings[1]!.text()).not.toContain("Suggested action");

    const fine = blocks[1]!.get('[data-testid="acceptance-critique-verdict"]');
    expect(fine.text()).toBe("No concerns");
    expect(fine.attributes("data-status")).toBe("approved");
    expect(blocks[1]!.findAll('[data-testid="acceptance-finding"]')).toHaveLength(0);
    expect(blocks[1]!.text()).toContain("No remarks.");
    wrapper.unmount();
  });

  it("closes with the two commands of the terminal and offers no button", async () => {
    const wrapper = mountPanel(testsApi());
    await flushPromises();

    const sentence = wrapper.get('[data-testid="acceptance-terminal"]');
    expect(spoken(sentence)).toBe(
      "The tests run from the terminal: ut test repeats them with the saved paths, ut test --plan new first has the model write new paths.",
    );
    expect(sentence.findAll("code").map((item) => item.text())).toEqual([
      "ut test",
      "ut test --plan new",
    ]);
    expect(wrapper.findAll("button")).toHaveLength(0);
    expect(wrapper.findAll("a")).toHaveLength(0);
    expect(wrapper.findAll("input, select, textarea")).toHaveLength(0);
    wrapper.unmount();
  });

  it("speaks Italian", async () => {
    const wrapper = mountPanel(testsApi(), "it");
    await flushPromises();

    expect(wrapper.get("h2").text()).toBe("Verifica dei criteri");
    const run = wrapper.get('[data-testid="acceptance-run"]');
    expect(run.get("h3").text()).toBe("Ultima verifica");
    expect(run.findAll("dt").map((item) => item.text())).toEqual([
      "Quando",
      "Browser",
      "Applicazione",
      "Confrontata con",
    ]);
    expect(run.get('[data-testid="acceptance-run-date"]').text()).toBe(
      dated(RUN.finished_at, "it"),
    );
    expect(spoken(run.get('[data-testid="acceptance-run-browsers"]'))).toBe(
      "Chrome 151.0.7922.76 e Firefox 156.0.1",
    );
    expect(spoken(run.get('[data-testid="acceptance-run-application"]'))).toBe(
      "Cartella statica dist",
    );
    expect(run.get('[data-testid="acceptance-run-reference"]').text()).toBe(
      "requisiti versione 2, design versione 2 (DES-001)",
    );
    expect(wrapper.findAll('[data-testid="acceptance-count"]').map((chip) => chip.text())).toEqual([
      "2 superati",
      "1 non superato",
      "1 bloccato",
      "1 non coperto",
      "1 non eseguito",
    ]);
    expect(wrapper.get("#acceptance-criteria-title").text()).toBe("Criteri (6)");
    expect(wrapper.findAll('[data-testid="acceptance-criteria"] thead th').map(spoken)).toEqual([
      "Criterio",
      "Che cosa chiede",
      "Esito",
      "Percorsi provati",
    ]);
    expect(
      wrapper.findAll('[data-testid="acceptance-criterion-status"]').map((chip) => chip.text()),
    ).toEqual(["Superato", "Non superato", "Bloccato", "Non coperto", "Superato", "Non eseguito"]);
    expect(spoken(wrapper.get('[data-testid="acceptance-criterion-reason"]'))).toBe(
      "Perché: The criterion asks for a manual check of the printed list.",
    );
    const critiques = wrapper.get('[data-testid="acceptance-critiques"]');
    expect(critiques.get("h3").text()).toBe("Che cosa dicono i twin");
    expect(critiques.get('[data-testid="acceptance-reviewed"]').text()).toBe(
      `Commenti del ${dated("2026-09-29T10:06:00+00:00", "it")}`,
    );
    expect(
      critiques.findAll('[data-testid="acceptance-critique-verdict"]').map((chip) => chip.text()),
    ).toEqual(["Qualche dubbio", "Nessun dubbio"]);
    expect(critiques.get('[data-testid="acceptance-finding-severity"]').text()).toBe("Importante");
    const finding = critiques.get('[data-testid="acceptance-finding"]');
    expect(finding.text()).toContain("Riguarda:");
    expect(finding.findAll('[data-testid="acceptance-subject"]').map(spoken)).toEqual([
      "AC-002",
      "REQ-003 · Guests are checked in quickly",
      "SCR-001 · Availability",
    ]);
    expect(spoken(finding)).toContain(
      "Azione suggerita: Show the new guest at the top of the list.",
    );
    expect(critiques.text()).toContain("Nessuna osservazione.");
    expect(spoken(wrapper.get('[data-testid="acceptance-terminal"]'))).toBe(
      "I test partono dal terminale: ut test li ripete con i percorsi salvati, ut test --plan new fa prima scrivere al modello percorsi nuovi.",
    );
    wrapper.unmount();
  });

  it.each([
    ["en", "0 failed", "Web address"],
    ["it", "0 non superati", "Indirizzo web"],
  ] as const)(
    "keeps a count of zero neutral and names a web address in %s",
    async (locale, failed, kind) => {
      const run: TestRunPayload = {
        ...RUN,
        application: { kind: "URL", address: "https://guests.example.test/today" },
        summary: { passed: 5, failed: 0, blocked: 0, not_covered: 1, not_run: 0 },
      };
      const wrapper = mountPanel(
        testsApi(async () => overview(run)),
        locale,
      );
      await flushPromises();

      const chips = wrapper.findAll('[data-testid="acceptance-count"]');
      expect(chips[1]!.text()).toBe(failed);
      expect(chips.map((chip) => chip.attributes("data-status"))).toEqual([
        "approved",
        "pending",
        "pending",
        "pending",
        "pending",
      ]);
      expect(spoken(wrapper.get('[data-testid="acceptance-run-application"]'))).toBe(
        `${kind} https://guests.example.test/today`,
      );
      wrapper.unmount();
    },
  );

  it.each([
    [
      "en",
      "No twin has commented on this run yet: at the end of a run ut test asks for their comments, once you confirm the cost.",
    ],
    [
      "it",
      "Nessun twin ha ancora commentato questa verifica: alla fine di una verifica ut test chiede il loro commento, dopo che hai confermato la spesa.",
    ],
  ] as const)(
    "says in %s that the twins have not commented on the run yet",
    async (locale, sentence) => {
      const wrapper = mountPanel(
        testsApi(async () => overview({ ...RUN, critiques: [], reviewed_at: null })),
        locale,
      );
      await flushPromises();

      const critiques = wrapper.get('[data-testid="acceptance-critiques"]');
      const empty = critiques.get('[data-testid="acceptance-no-review"]');
      expect(spoken(empty)).toBe(sentence);
      expect(empty.findAll("code").map((item) => item.text())).toEqual(["ut test"]);
      expect(critiques.find('[data-testid="acceptance-reviewed"]').exists()).toBe(false);
      expect(critiques.findAll('[data-testid="acceptance-critique"]')).toHaveLength(0);
      wrapper.unmount();
    },
  );

  it.each([
    [
      "en",
      "On this Studio the model cannot write the paths or ask the twins: connect a model. Paths already saved in your project still run.",
    ],
    [
      "it",
      "In questo Studio il modello non può scrivere i percorsi né interpellare i twin: collega un modello. I percorsi già salvati nel tuo progetto funzionano ancora.",
    ],
  ] as const)("says in %s when the Studio has no model for the tests", async (locale, text) => {
    const wrapper = mountPanel(
      testsApi(async () => overview(RUN, false)),
      locale,
    );
    await flushPromises();

    expect(wrapper.get('[data-testid="acceptance-no-model"]').text()).toBe(text);
    expect(wrapper.findAll('[data-testid="acceptance-criterion"]')).toHaveLength(6);
    wrapper.unmount();
  });

  it("shows the codes alone when the page holds the specification of another project", async () => {
    useRequirementsStore().$patch({ projectId: SECOND_PROJECT_ID });
    useDesignStore().$patch({ projectId: SECOND_PROJECT_ID });
    const wrapper = mountPanel(testsApi());
    await flushPromises();

    const statement = wrapper.get('[data-testid="acceptance-criterion-statement"]');
    expect(statement.get('[role="img"]').attributes("aria-label")).toBe("text not available");
    expect(statement.text()).toBe("—");
    expect(
      wrapper
        .get('[data-testid="acceptance-finding"]')
        .findAll('[data-testid="acceptance-subject"]')
        .map(spoken),
    ).toEqual(["AC-002", "REQ-003", "SCR-001"]);
    wrapper.unmount();
  });

  it("reads the overview once per project and again for another project", async () => {
    const api = testsApi(async (projectId) => ({ ...overview(), project_id: projectId }));
    const first = mountPanel(api);
    await flushPromises();
    first.unmount();

    const second = mountPanel(api);
    await flushPromises();

    expect(api.overview).toHaveBeenCalledTimes(1);
    expect(second.findAll('[data-testid="acceptance-criterion"]')).toHaveLength(6);

    await second.setProps({ projectId: SECOND_PROJECT_ID });
    await flushPromises();

    expect(api.overview).toHaveBeenCalledTimes(2);
    expect(api.overview).toHaveBeenLastCalledWith(SECOND_PROJECT_ID, TOKEN);
    expect(spoken(second.get('[data-testid="acceptance-criterion-statement"]'))).toBe("—");
    second.unmount();
  });

  it("has no axe violations with a full run", async () => {
    const wrapper = mountPanel(testsApi(), "it");
    await flushPromises();

    await expectAccessible(wrapper.element);
    wrapper.unmount();
  });

  it("has no axe violations without runs and without a model", async () => {
    const wrapper = mountPanel(testsApi(async () => overview(null, false)));
    await flushPromises();

    await expectAccessible(wrapper.element);
    wrapper.unmount();
  });

  it("has no axe violations when the read fails", async () => {
    const wrapper = mountPanel(
      testsApi(async () => {
        throw new TypeError("Failed to fetch");
      }),
    );
    await flushPromises();

    await expectAccessible(wrapper.element);
    wrapper.unmount();
  });
});
