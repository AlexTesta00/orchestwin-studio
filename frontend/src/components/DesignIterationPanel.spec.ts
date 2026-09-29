import { flushPromises, mount } from "@vue/test-utils";
import { afterEach, describe, expect, it, vi } from "vitest";

import { createAppI18n } from "@/i18n";
import { expectAccessible } from "@/test/axe";
import DesignIterationPanel, {
  generationFailureText,
  generationReasonText,
  generationRetryable,
  type IterationItem,
  type IterationJob,
} from "./DesignIterationPanel.vue";
import type { MockupDocument } from "./GeneratedMockupDialog.vue";
import source from "./DesignIterationPanel.vue?raw";

const REVIEW_CODES = {
  "generated_mockup_review.py": [
    "UNKNOWN_REQUIREMENT",
    "SELF_LINK",
    "UNTRACED_CONTROL",
    "UNLABELLED_CONTROL",
    "UNNAMED_ACTION",
    "TABLE_WITHOUT_HEADERS",
    "TABLE_TOO_SHORT",
    "EMPTY_CELL",
    "SELECT_TOO_SHORT",
    "HEADING_LEVEL_SKIPPED",
    "LIST_TOO_SHORT",
    "EMPTY_CONTAINER",
    "DECORATIVE_ICON_EXPOSED",
    "HEADING_COUNT",
    "SCREEN_TOO_EMPTY",
    "UNTRACED_SCREEN",
    "PLACEHOLDER_TEXT",
    "DATED_BACKGROUND",
    "LOW_CONTRAST",
    "UNREADABLE_TEXT_COLOUR",
    "BACKGROUND_WITHOUT_TEXT_COLOUR",
    "NO_RESPONSIVE_RULE",
    "WEAK_CONTROL_BORDER",
    "NO_TRANSITION",
    "UNREACHABLE_SCREEN",
    "SINGLE_STATE",
  ],
  "generated_mockups.py": [
    "MARKUP_CONTROL_CHARACTER",
    "MARKUP_CHARACTER_REFERENCE",
    "MARKUP_COMMENT",
    "MARKUP_SYNTAX",
    "MARKUP_DECLARATION",
    "MARKUP_DOCTYPE",
    "MARKUP_PROCESSING_INSTRUCTION",
    "MARKUP_CDATA",
    "ELEMENT_FORBIDDEN",
    "ATTRIBUTE_DUPLICATED",
    "ATTRIBUTE_FORBIDDEN",
    "SELF_CLOSING",
    "ATTRIBUTE_VALUE",
    "ID_INVALID",
    "ID_DUPLICATED",
    "CLASS_INVALID",
    "DATA_REQ_INVALID",
    "LINK_TARGET",
    "ID_REFERENCE",
    "CONTENT_RULE",
    "MARKUP_TOO_DEEP",
    "TOO_MANY_ELEMENTS",
    "UNEXPECTED_END_TAG",
    "MISNESTED_ELEMENT",
    "UNCLOSED_ELEMENT",
    "TOKEN_NAMES",
    "SCREEN_INVALID",
    "MARKUP_TOO_LONG",
    "TITLE_INVALID",
    "SCREEN_CODE",
    "SCREEN_STATE",
    "SCREEN_COUNT",
    "CONTRACT_VERSION",
    "ALTERNATIVE_ID",
    "STYLES_SYNTAX",
    "STYLES_TOO_LONG",
    "MOCKUP_TOO_LONG",
    "NOT_CANONICAL",
    "SNAPSHOT_INVALID",
    "SNAPSHOT_NOT_CANONICAL",
  ],
  "generated_mockup_styles.py": [
    "STYLES_SYNTAX",
    "STYLES_FORBIDDEN",
    "STYLES_TOO_LONG",
    "STYLES_CONTROL_CHARACTER",
    "STYLES_COMMENT",
    "STYLES_AT_RULE",
    "STYLES_SELECTOR",
    "STYLES_COLOUR",
    "STYLES_FUNCTION",
    "STYLES_CUSTOM_PROPERTY",
    "STYLES_FONT",
    "STYLES_Z_INDEX",
    "STYLES_PROPERTY",
  ],
  "bound_mockups.py": [
    "MOCKUP_INVALID",
    "REQUIREMENT_MAPPING",
    "REQUIREMENT_ID_DUPLICATED",
    "REQUIREMENT_CODE_UNMAPPED",
    "REQUIREMENT_CODE_UNUSED",
    "SNAPSHOT_INVALID",
    "SNAPSHOT_NOT_CANONICAL",
  ],
  "generated_mockup_drafts.py": ["SCREEN_LANGUAGE", "SCREEN_COUNT", "REQUIREMENTS_NOT_COVERED"],
  "generation_jobs.py": ["UNEXPECTED_ERROR"],
  "generated_mockup_repair.py": [
    "ELEMENT_REMOVED",
    "ELEMENT_UNWRAPPED",
    "ATTRIBUTE_REMOVED",
    "LINK_REMOVED",
    "REQUIREMENT_CODE_REMOVED",
    "REQUIREMENT_INHERITED",
    "STYLE_DECLARATION_REMOVED",
    "STYLE_RULE_REMOVED",
    "STYLE_REST_REMOVED",
  ],
};

const CONTRACT_FAILURES = [
  "MOCKUP_QUALITY_REJECTED",
  "UNSAFE_MOCKUP_OUTPUT",
  "MOCKUP_LANGUAGE_MISMATCH",
  "MOCKUP_SCREEN_COUNT",
  "MOCKUP_COVERAGE_TOO_LOW",
  "DESIGN_CONTEXT_CHANGED",
  "DESIGN_ALTERNATIVE_NOT_FOUND",
  "GENERATED_MOCKUP_REQUIRES_VISUAL_LANGUAGE",
  "TOO_MANY_GENERATIONS",
  "GENERATION_BUDGET_EXCEEDED",
  "GENERATION_BUDGET_UNAVAILABLE",
  "REAL_MOCKUP_MODEL_NOT_CONFIGURED",
  "GENERATION_JOB_NOT_FOUND",
  "GENERATED_MOCKUP_NOT_FOUND",
  "GENERATED_MOCKUP_REQUIRED",
  "ITERATION_REQUEST_INVALID",
  "GENERATION_POLL_TIMEOUT",
  "GENERATION_STATUS_UNAVAILABLE",
  "GENERATION_START_FAILED",
  "MOCKUP_STATUS_UNAVAILABLE",
  "PROVIDER_UNAVAILABLE",
  "TIMEOUT",
  "RATE_LIMITED",
  "INCOMPLETE_OUTPUT",
  "PROVIDER_REFUSED",
  "RESPONSE_SCHEMA_ERROR",
  "AUTHENTICATION_FAILED",
  "CONTEXT_BUDGET_EXCEEDED",
  "IDENTITY_MISMATCH",
  "PROVIDER_ERROR",
  "INVALID_REQUEST",
  "INVALID_PROVIDER_OUTPUT",
  "GENERATED_MOCKUP_PATH_INACTIVE",
  "REQUIREMENTS_QUERY_UNAVAILABLE",
  "GENERATION_JOBS_UNAVAILABLE",
  "MOCKUP_ENTRY_SCREEN_INVALID",
  "GENERATION_JOB_CANCELLED",
  "GENERATION_JOB_FAILED",
];

const STARTED = "2026-09-29T09:12:03+00:00";

const SCREENS = [
  { code: "SCR-001", title: "Registro dei prestiti", state: "DEFAULT" },
  { code: "SCR-002", title: "Nuovo prestito", state: "DEFAULT" },
];

function documentOf(kind: "before" | "after", entry = "SCR-001"): MockupDocument {
  return {
    html: `<!doctype html><html><body><h1 class="${kind}-marker">${kind} ${entry}</h1></body></html>`,
    content_hash: (kind === "before" ? "b" : "c").repeat(64),
    source: kind === "before" ? "applied" : "latest",
    alternative_id: "alt-1",
    title: "Prestiti Biblio",
    entry_screen: entry,
    screens: SCREENS,
  };
}

function job(overrides: Partial<IterationJob> = {}): IterationJob {
  return {
    job_id: "job-1",
    kind: "ITERATION",
    status: "RUNNING",
    stage: "GENERATING",
    attempt: 1,
    started_at: STARTED,
    finished_at: null,
    alternative_id: "alt-1",
    result: null,
    failure: null,
    ...overrides,
  };
}

const ready = job({
  status: "SUCCEEDED",
  stage: null,
  finished_at: "2026-09-29T09:15:03+00:00",
  result: {
    status: "MOCKUP_GENERATED",
    generation_id: "gen-7",
    design_version_id: "ver-2",
    design_content_hash: "d".repeat(64),
    package: {},
    approach: "Registro con ricerca",
    changes: ["Aggiunta la ricerca per titolo", "Le date sono ora in ordine di ritardo"],
    warnings: [
      { code: "LIST_TOO_SHORT", screen_code: "SCR-002", detail: "ul has 1 item" },
      { code: "LIST_TOO_SHORT", screen_code: "SCR-002", detail: "ol has 1 item" },
      { code: "NO_RESPONSIVE_RULE", screen_code: null, detail: "no media query" },
    ],
    cost_microusd: 412000,
  },
});

const items: IterationItem[] = [
  {
    generation_id: "gen-7",
    requested_at: "2026-09-29T09:12:03+00:00",
    request: "Aggiungi la ricerca per titolo",
    assertions: ["Il tono resta gentile"],
    changes: ["Aggiunta la ricerca per titolo"],
    status: "PROPOSED",
    base_design_version_number: 2,
    applied_design_version_number: null,
    cost_microusd: 412000,
  },
  {
    generation_id: "gen-5",
    requested_at: "2026-09-28T18:40:00+00:00",
    request: "Metti le date in evidenza",
    assertions: [],
    changes: [],
    status: "REJECTED",
    base_design_version_number: 1,
    applied_design_version_number: null,
    cost_microusd: 300000,
  },
];

function mountPanel(props: Partial<InstanceType<typeof DesignIterationPanel>["$props"]> = {}) {
  return mount(DesignIterationPanel, {
    props: { request: "Aggiungi la ricerca per titolo", ...props },
    global: { plugins: [createAppI18n("it")] },
  });
}

afterEach(() => {
  vi.useRealTimers();
});

describe("design iteration panel", () => {
  it("shows nothing while there is no request, no rule and no history", () => {
    const wrapper = mountPanel({ job: null });
    expect(wrapper.find("[data-testid='design-iteration-panel']").exists()).toBe(false);
  });

  it("shows the request and the time elapsed while the designer draws", async () => {
    vi.useFakeTimers();
    vi.setSystemTime(new Date("2026-09-29T09:13:23+00:00"));
    const wrapper = mountPanel({ job: job() });
    const panel = wrapper.get("[data-testid='design-iteration-panel']");
    expect(panel.attributes("data-phase")).toBe("drawing");
    expect(panel.get("h2").text()).toBe("Modifiche su tua richiesta");
    expect(wrapper.get("[data-testid='agent-message']").text()).toContain(
      "Sto disegnando la nuova versione con le tue indicazioni.",
    );
    const request = wrapper.get("[data-testid='design-iteration-request']");
    expect(request.element.tagName).toBe("BLOCKQUOTE");
    expect(request.text()).toBe("Aggiungi la ricerca per titolo");
    expect(request.classes()).toContain("border-l-2");
    expect(wrapper.get("[data-testid='design-iteration-stage']").text()).toBe(
      "Il designer sta disegnando le schermate.",
    );
    expect(wrapper.get("[data-testid='design-iteration-duration']").text()).toBe(
      "Di solito servono da 5 a 10 minuti. Puoi continuare a lavorare: il disegno prosegue anche se chiudi la pagina.",
    );
    expect(wrapper.get("[data-testid='design-iteration-stage']").attributes("role")).toBe("status");
    expect(wrapper.get("[data-testid='design-iteration-elapsed']").text()).toBe(
      "In corso da 1 min 20 s",
    );
    vi.advanceTimersByTime(5000);
    await flushPromises();
    expect(wrapper.get("[data-testid='design-iteration-elapsed']").text()).toBe(
      "In corso da 1 min 25 s",
    );
    await wrapper.setProps({ job: job({ stage: "VALIDATING" }) });
    expect(wrapper.get("[data-testid='design-iteration-stage']").text()).toBe(
      "Lo Studio controlla la nuova versione.",
    );
    await wrapper.setProps({ job: job({ stage: "RETRYING", attempt: 2 }) });
    expect(wrapper.get("[data-testid='design-iteration-stage']").text()).toBe(
      "Il primo tentativo non andava bene: il designer lo sta rifacendo.",
    );
    expect(vi.getTimerCount()).toBe(1);
    await wrapper.setProps({
      job: ready,
      before: documentOf("before"),
      after: documentOf("after"),
    });
    expect(vi.getTimerCount()).toBe(0);
    await wrapper.setProps({ job: job() });
    expect(vi.getTimerCount()).toBe(1);
    wrapper.unmount();
    expect(vi.getTimerCount()).toBe(0);
  });

  it("shows the changes and the two versions side by side when the new version is ready", () => {
    const wrapper = mountPanel({
      job: ready,
      before: documentOf("before"),
      after: documentOf("after"),
    });
    expect(wrapper.get("[data-testid='design-iteration-panel']").attributes("data-phase")).toBe(
      "ready",
    );
    expect(wrapper.get("[data-testid='agent-message']").text()).toContain(
      "Ecco la nuova versione.",
    );
    expect(
      wrapper.findAll("[data-testid='design-iteration-changes'] li").map((item) => item.text()),
    ).toEqual(["Aggiunta la ricerca per titolo", "Le date sono ora in ordine di ritardo"]);
    const sides = wrapper.findAll("[data-testid='design-iteration-side']");
    expect(sides.map((side) => side.attributes("data-side"))).toEqual(["before", "after"]);
    expect(sides.map((side) => side.attributes("data-claim-status"))).toEqual([
      "confirmed",
      "hypothesis",
    ]);
    expect(sides[0]?.text()).toContain("Versione attuale");
    expect(sides[0]?.text()).toContain("Applicata da te");
    expect(sides[1]?.text()).toContain("Nuova versione");
    expect(sides[1]?.text()).toContain("Proposta, non ancora applicata");
    const frames = wrapper.findAll("iframe");
    expect(frames).toHaveLength(2);
    expect(frames.map((frame) => frame.attributes("sandbox"))).toEqual(["", ""]);
    expect(frames[0]?.attributes("srcdoc")).toBe(documentOf("before").html);
    expect(frames[1]?.attributes("srcdoc")).toBe(documentOf("after").html);
    expect(frames[1]?.attributes("title")).toBe("Nuova versione: Registro dei prestiti");
    expect(wrapper.find(".after-marker").exists()).toBe(false);
    expect(source).not.toMatch(/v-html|innerHTML|allow-/);
  });

  it("opens either version in the large window on the screen that is shown", async () => {
    const wrapper = mountPanel({
      job: ready,
      before: documentOf("before", "SCR-002"),
      after: documentOf("after", "SCR-002"),
    });
    const buttons = wrapper.findAll("[data-testid='design-iteration-open']");
    expect(buttons.map((button) => button.text())).toEqual(["Apri in grande", "Apri in grande"]);
    expect(buttons[1]?.attributes("aria-label")).toBe("Apri in grande: Nuova versione");
    await buttons[1]?.trigger("click");
    await buttons[0]?.trigger("click");
    expect(wrapper.emitted("open")).toEqual([
      ["after", "SCR-002"],
      ["before", "SCR-002"],
    ]);
  });

  it("asks for the same screen in both versions and moves between tabs with the keyboard", async () => {
    const wrapper = mount(DesignIterationPanel, {
      props: {
        request: "Aggiungi la ricerca",
        job: ready,
        before: documentOf("before"),
        after: documentOf("after"),
      },
      global: { plugins: [createAppI18n("it")] },
      attachTo: document.body,
    });
    const tabs = () => wrapper.findAll("[data-testid='design-iteration-screen']");
    expect(wrapper.get("[role='tablist']").attributes("aria-label")).toBe(
      "Schermate da confrontare",
    );
    expect(tabs().map((tab) => tab.attributes("aria-selected"))).toEqual(["true", "false"]);
    await tabs()[0]?.trigger("click");
    expect(wrapper.emitted("screen")).toBeUndefined();
    (tabs()[0]?.element as HTMLElement).focus();
    await wrapper.get("[role='tablist']").trigger("keydown", { key: "ArrowRight" });
    expect(document.activeElement).toBe(tabs()[1]?.element);
    expect(wrapper.emitted("screen")).toBeUndefined();
    await tabs()[1]?.trigger("click");
    expect(wrapper.emitted("screen")).toEqual([["SCR-002"]]);
    expect(tabs().map((tab) => tab.attributes("aria-selected"))).toEqual(["false", "true"]);
    expect(wrapper.get("[data-testid='design-iteration-opening']").text()).toBe(
      "Apro la schermata in tutte e due le versioni…",
    );
    expect(wrapper.get("[role='tabpanel']").attributes("aria-busy")).toBe("true");
    await wrapper.setProps({ after: documentOf("after", "SCR-002") });
    await wrapper.setProps({ before: documentOf("before", "SCR-002") });
    expect(wrapper.find("[data-testid='design-iteration-opening']").exists()).toBe(false);
    expect(tabs().map((tab) => tab.attributes("aria-selected"))).toEqual(["false", "true"]);
    expect(wrapper.findAll("iframe").map((frame) => frame.attributes("srcdoc"))).toEqual([
      documentOf("before", "SCR-002").html,
      documentOf("after", "SCR-002").html,
    ]);
    wrapper.unmount();
  });

  it("waits for a document before showing it", () => {
    const wrapper = mountPanel({ job: ready, before: documentOf("before"), after: null });
    const after = wrapper.findAll("[data-testid='design-iteration-side']")[1];
    expect(after?.text()).toContain("Preparo l'anteprima…");
    expect(after?.find("iframe").exists()).toBe(false);
    expect(
      wrapper.findAll("[data-testid='design-iteration-open']")[1]?.attributes("disabled"),
    ).toBeDefined();
  });

  it("explains the warnings of the review in plain words, once each", () => {
    const wrapper = mountPanel({
      job: ready,
      before: documentOf("before"),
      after: documentOf("after"),
    });
    const lines = wrapper
      .findAll("[data-testid='design-iteration-warnings'] li")
      .map((item) => item.text());
    expect(lines).toEqual([
      "Nella schermata «Nuovo prestito»: Un elenco aveva un solo elemento",
      "Le schermate non si adattavano ai telefoni",
    ]);
    expect(wrapper.get("[data-testid='design-iteration-warnings']").text()).not.toMatch(
      /LIST_TOO_SHORT|SCR-002|ul has/,
    );
  });

  it("applies or discards the new version, one decision at a time", async () => {
    const wrapper = mountPanel({
      job: ready,
      before: documentOf("before"),
      after: documentOf("after"),
    });
    await wrapper.get("[data-testid='design-iteration-apply']").trigger("click");
    await wrapper.get("[data-testid='design-iteration-discard']").trigger("click");
    expect(wrapper.emitted("apply")).toEqual([["gen-7"]]);
    expect(wrapper.emitted("discard")).toEqual([["gen-7"]]);
    expect(wrapper.get("[data-testid='design-iteration-apply']").text()).toBe(
      "Applica la nuova versione",
    );
    await wrapper.setProps({ busy: true });
    expect(
      wrapper.get("[data-testid='design-iteration-apply']").attributes("disabled"),
    ).toBeDefined();
    expect(
      wrapper.get("[data-testid='design-iteration-discard']").attributes("disabled"),
    ).toBeDefined();
  });

  it("says when the designer listed no change", () => {
    const quiet = job({ ...ready, result: { ...ready.result!, changes: [], warnings: [] } });
    const wrapper = mountPanel({
      job: quiet,
      before: documentOf("before"),
      after: documentOf("after"),
    });
    expect(wrapper.text()).toContain("Il designer non ha elencato le modifiche.");
    expect(wrapper.find("[data-testid='design-iteration-warnings']").exists()).toBe(false);
  });

  it("explains a discarded answer in plain words and offers to try again", async () => {
    const rejected = job({
      status: "REJECTED",
      stage: null,
      finished_at: "2026-09-29T09:16:00+00:00",
      failure: {
        code: "MOCKUP_QUALITY_REJECTED",
        reasons: [
          { code: "TABLE_TOO_SHORT", screen_code: "SCR-001", detail: "table has 2 rows" },
          { code: "LOW_CONTRAST", screen_code: "SCR-009", detail: ".badge 2.10" },
          { code: "STYLES_FORBIDDEN", screen_code: null, detail: "position absolute" },
          { code: "SOMETHING_NEW", screen_code: null, detail: "" },
        ],
      },
    });
    const wrapper = mountPanel({ job: rejected, before: documentOf("before") });
    const failure = wrapper.get("[data-testid='design-iteration-failure']");
    expect(failure.attributes("role")).toBe("alert");
    expect(failure.text()).toContain("La nuova versione va rifatta");
    expect(failure.text()).toContain(
      "Lo Studio ha scartato la risposta perché non superava i controlli di qualità.",
    );
    expect(failure.findAll("li").map((item) => item.text())).toEqual([
      "Nella schermata «Registro dei prestiti»: Una tabella aveva troppo poche righe per sembrare vera",
      "Un testo non si leggeva bene sul suo sfondo",
      "Il codice delle schermate conteneva qualcosa che lo Studio non accetta",
      "Uno dei controlli dello Studio non è stato superato",
    ]);
    const request = failure.get("[data-testid='design-iteration-failure-request']");
    expect(request.get("p").text()).toBe("La tua richiesta");
    expect(request.get("blockquote").text()).toBe("Aggiungi la ricerca per titolo");
    expect(request.text()).not.toMatch(/[«»]/);
    expect(failure.text()).not.toMatch(/TABLE_TOO_SHORT|SCR-00|\.badge/);
    await wrapper.get("[data-testid='design-iteration-retry']").trigger("click");
    expect(wrapper.emitted("retry")).toEqual([["Aggiungi la ricerca per titolo"]]);
  });

  it("explains a failed drawing and a request that did not start", async () => {
    const failed = job({
      status: "FAILED",
      stage: null,
      failure: { code: "UNSAFE_MOCKUP_OUTPUT", reasons: [] },
    });
    const wrapper = mountPanel({ job: failed });
    expect(wrapper.get("[data-testid='design-iteration-failure']").text()).toContain(
      "La nuova versione non è stata disegnata",
    );
    expect(wrapper.text()).toContain("La risposta conteneva elementi che lo Studio non accetta.");
    await wrapper.setProps({ job: null, error: "GENERATION_BUDGET_EXCEEDED" });
    expect(wrapper.get("[data-testid='design-iteration-panel']").attributes("data-phase")).toBe(
      "error",
    );
    expect(wrapper.text()).toContain("La richiesta non è partita");
    expect(wrapper.text()).toContain(
      "Il tetto di spesa impostato non basta per questa generazione.",
    );
    expect(wrapper.find("[data-testid='design-iteration-retry']").exists()).toBe(false);
    await wrapper.setProps({ error: "TOO_MANY_GENERATIONS" });
    expect(wrapper.find("[data-testid='design-iteration-retry']").exists()).toBe(true);
    await wrapper.setProps({ request: null });
    expect(wrapper.find("[data-testid='design-iteration-retry']").exists()).toBe(false);
  });

  it("has a sentence in both languages for every code of the contract", () => {
    const failures = [
      "MOCKUP_QUALITY_REJECTED",
      "UNSAFE_MOCKUP_OUTPUT",
      "MOCKUP_LANGUAGE_MISMATCH",
      "MOCKUP_SCREEN_COUNT",
      "MOCKUP_COVERAGE_TOO_LOW",
      "GENERATED_MOCKUP_REQUIRES_VISUAL_LANGUAGE",
      "GENERATION_BUDGET_EXCEEDED",
      "TOO_MANY_GENERATIONS",
      "REAL_MOCKUP_MODEL_NOT_CONFIGURED",
      "DESIGN_CONTEXT_CHANGED",
      "GENERATED_MOCKUP_REQUIRED",
      "ITERATION_REQUEST_INVALID",
      "GENERATION_JOB_NOT_FOUND",
      "GENERATED_MOCKUP_NOT_FOUND",
      "DESIGN_ALTERNATIVE_NOT_FOUND",
    ];
    for (const locale of ["it", "en"] as const) {
      const generic = generationFailureText("UNKNOWN_CODE", locale);
      const sentences = failures.map((code) => generationFailureText(code, locale));
      expect(
        sentences.every((sentence) => sentence !== generic && !/[A-Z]{2,}_/.test(sentence)),
      ).toBe(true);
      expect(new Set(sentences).size).toBe(failures.length);
      expect(generationFailureText(null, locale)).toBe(generic);
    }
    expect(generationFailureText("GENERATION_BUDGET_EXCEEDED", "it")).toBe(
      "Il tetto di spesa impostato non basta per questa generazione.",
    );
    const reasons = [
      "UNREACHABLE_SCREEN",
      "NO_TRANSITION",
      "SELF_LINK",
      "UNKNOWN_REQUIREMENT",
      "UNTRACED_CONTROL",
      "UNTRACED_SCREEN",
      "UNLABELLED_CONTROL",
      "UNNAMED_ACTION",
      "TABLE_WITHOUT_HEADERS",
      "HEADING_COUNT",
      "SCREEN_TOO_EMPTY",
      "TABLE_TOO_SHORT",
      "EMPTY_CELL",
      "SELECT_TOO_SHORT",
      "PLACEHOLDER_TEXT",
      "LOW_CONTRAST",
      "UNREADABLE_TEXT_COLOUR",
      "DATED_BACKGROUND",
      "HEADING_LEVEL_SKIPPED",
      "LIST_TOO_SHORT",
      "EMPTY_CONTAINER",
      "DECORATIVE_ICON_EXPOSED",
      "BACKGROUND_WITHOUT_TEXT_COLOUR",
      "NO_RESPONSIVE_RULE",
      "SINGLE_STATE",
    ];
    for (const locale of ["it", "en"] as const) {
      const generic = generationReasonText("UNKNOWN_CODE", locale);
      const sentences = reasons.map((code) => generationReasonText(code, locale));
      expect(sentences.every((sentence) => sentence !== generic)).toBe(true);
      expect(new Set(sentences).size).toBe(reasons.length);
    }
    expect(generationReasonText("TABLE_TOO_SHORT", "it")).toBe(
      "Una tabella aveva troppo poche righe per sembrare vera",
    );
    expect(generationReasonText("LOW_CONTRAST", "it")).toBe(
      "Un testo non si leggeva bene sul suo sfondo",
    );
    expect(generationFailureText("UNSAFE_MOCKUP_OUTPUT", "it")).toBe(
      "La risposta conteneva elementi che lo Studio non accetta.",
    );
  });

  it("lists the rules that hold for the project with the way to remove one", async () => {
    const wrapper = mountPanel({
      job: null,
      assertions: ["Il tono resta gentile", "Niente rosso"],
    });
    const rules = wrapper.findAll("[data-testid='design-iteration-rule']");
    expect(rules).toHaveLength(2);
    expect(rules.every((rule) => rule.attributes("data-claim-status") === "confirmed")).toBe(true);
    expect(wrapper.get("[data-testid='design-iteration-rules'] h3").text()).toBe(
      "Regole valide per le prossime versioni",
    );
    const remove = wrapper.findAll("[data-testid='design-iteration-remove-rule']");
    expect(remove[1]?.attributes("aria-label")).toBe("Togli la regola: Niente rosso");
    await remove[1]?.trigger("click");
    expect(wrapper.emitted("remove-assertion")).toEqual([["Niente rosso"]]);
  });

  it("keeps the earlier requests closed until the person opens them", async () => {
    const wrapper = mountPanel({ job: null, items });
    const toggle = wrapper.get("[data-testid='design-iteration-history-toggle']");
    expect(toggle.text()).toBe("› Richieste precedenti (2)");
    expect(toggle.attributes("aria-expanded")).toBe("false");
    expect(wrapper.find("[data-testid='design-iteration-history-item']").exists()).toBe(false);
    await toggle.trigger("click");
    expect(toggle.attributes("aria-expanded")).toBe("true");
    const entries = wrapper.findAll("[data-testid='design-iteration-history-item']");
    const controlled = toggle.attributes("aria-controls") ?? "missing";
    expect(wrapper.get(`[id='${controlled}']`).findAll("li[data-status]")).toHaveLength(2);
    expect(entries).toHaveLength(2);
    expect(entries[0]?.text()).toContain("Da decidere");
    expect(entries[0]?.get("[data-testid='design-iteration-history-request']").text()).toBe(
      "Aggiungi la ricerca per titolo",
    );
    expect(entries[0]?.text()).not.toContain("«");
    expect(entries[0]?.text()).toContain("Il tono resta gentile");
    expect(entries[1]?.text()).toContain("Scartata dallo Studio");
    expect(entries[1]?.find("[data-status='rejected']").exists()).toBe(true);
    expect(wrapper.text()).not.toMatch(/412000|gen-7/);
  });

  it("quotes a request that holds quotation marks as a block without adding marks of its own", () => {
    const text = "Dopo «Togliti» chiedi sempre conferma";
    const wrapper = mountPanel({ job: job(), request: text });
    const request = wrapper.get("[data-testid='design-iteration-request']");
    expect(request.element.tagName).toBe("BLOCKQUOTE");
    expect(request.text()).toBe(text);
    expect(wrapper.text()).not.toContain("««");
  });

  it("names the screens by their titles in the changes of the new version and of the earlier requests", async () => {
    const coded = job({
      ...ready,
      result: {
        ...ready.result!,
        changes: ["Porta ora alla nuova SCR-003", "SCR-002 Nuovo prestito ha la data in alto"],
      },
    });
    const wrapper = mountPanel({
      job: coded,
      before: documentOf("before"),
      after: null,
      screens: [{ code: "SCR-003", title: "Prestito registrato" }],
      items: [{ ...items[0]!, changes: ["Tolta la SCR-001 in eccesso"] }],
    });
    expect(
      wrapper.findAll("[data-testid='design-iteration-changes'] li").map((item) => item.text()),
    ).toEqual([
      "Porta ora alla nuova «Prestito registrato»",
      "«Nuovo prestito» ha la data in alto",
    ]);
    await wrapper.get("[data-testid='design-iteration-history-toggle']").trigger("click");
    expect(wrapper.get("[data-testid='design-iteration-history-item']").text()).toContain(
      "Tolta la «Registro dei prestiti» in eccesso",
    );
    expect(wrapper.text()).not.toMatch(/SCR-00/);
  });

  it("speaks English when the page is in English", () => {
    const wrapper = mountPanel({
      locale: "en",
      job: ready,
      before: documentOf("before"),
      after: documentOf("after"),
    });
    expect(wrapper.get("h2").text()).toBe("Changes you asked for");
    expect(wrapper.get("[data-testid='design-iteration-apply']").text()).toBe(
      "Apply the new version",
    );
    expect(wrapper.text()).toContain("On the screen “Nuovo prestito”: A list had a single item");
  });

  it("says how long a new version usually takes, in English too", () => {
    const wrapper = mountPanel({ locale: "en", job: job() });
    expect(wrapper.get("[data-testid='design-iteration-duration']").text()).toBe(
      "It usually takes 5 to 10 minutes. You can keep working: the drawing goes on even if you close the page.",
    );
  });

  it("has no axe violations while drawing, when ready and after a rejection", async () => {
    await expectAccessible(
      mountPanel({ job: job(), assertions: ["Il tono resta gentile"] }).element,
      { iframes: false },
    );
    await expectAccessible(
      mountPanel({
        job: ready,
        before: documentOf("before"),
        after: documentOf("after"),
        items,
      }).element,
      { iframes: false },
    );
    await expectAccessible(
      mountPanel({
        job: job({ status: "REJECTED", failure: { code: "MOCKUP_QUALITY_REJECTED", reasons: [] } }),
      }).element,
      { iframes: false },
    );
  });

  it("has a sentence of its own for every code that the review and the validator of the mockup raise", () => {
    for (const locale of ["it", "en"] as const) {
      const generic = generationReasonText("A_CODE_NOBODY_RAISES", locale);
      for (const [module, codes] of Object.entries(REVIEW_CODES)) {
        const missing = codes.filter((code) => generationReasonText(code, locale) === generic);
        expect({ module, locale, missing }).toEqual({ module, locale, missing: [] });
        for (const code of codes) {
          expect(generationReasonText(code, locale)).not.toMatch(/[A-Z]{2,}_[A-Z]/);
        }
      }
    }
    expect(generationReasonText("WEAK_CONTROL_BORDER", "it")).toBe(
      "Il bordo di un campo o di un pulsante si vedeva appena",
    );
    expect(generationReasonText("REQUIREMENT_CODE_UNMAPPED", "it")).toBe(
      "Il mockup citava i requisiti in un modo che lo Studio non riconosce",
    );
    expect(generationReasonText("STYLES_COLOUR", "en")).toBe(
      "The styles wrote a colour by hand instead of using the palette of the alternative",
    );
    expect(generationReasonText("LINK_TARGET", "en")).toBe(
      "A link led to a screen that does not exist",
    );
  });

  it("says in plain words what the Studio removed or completed when it repaired a mockup", () => {
    const repairs = REVIEW_CODES["generated_mockup_repair.py"];
    for (const [locale, still] of [
      ["it", "il mockup resta valido"],
      ["en", "the mockup is still valid"],
    ] as const) {
      const others = new Set(
        ["ELEMENT_FORBIDDEN", "ATTRIBUTE_FORBIDDEN", "REQUIREMENT_MAPPING", "NOT_A_CODE"].map(
          (code) => generationReasonText(code, locale),
        ),
      );
      const sentences = repairs.map((code) => generationReasonText(code, locale));
      expect(new Set(sentences).size).toBe(repairs.length);
      for (const sentence of sentences) {
        expect(others.has(sentence)).toBe(false);
        expect(sentence.startsWith(locale === "it" ? "Lo Studio ha " : "The Studio ")).toBe(true);
        expect(sentence.endsWith(still)).toBe(true);
      }
    }
    expect(generationReasonText("ATTRIBUTE_REMOVED", "it")).toBe(
      "Lo Studio ha tolto da un elemento un'impostazione che avrebbe caricato o avviato qualcosa: il mockup resta valido",
    );
  });

  it("shows the notes of a repair among the points to check of a new version", () => {
    const wrapper = mountPanel({
      job: {
        ...ready,
        result: {
          ...ready.result!,
          warnings: [
            { code: "ELEMENT_REMOVED", screen_code: "SCR-001", detail: "img (2)" },
            { code: "STYLE_RULE_REMOVED", screen_code: null, detail: "body" },
          ],
        },
      },
      before: documentOf("before"),
      after: documentOf("after"),
    });
    const warnings = wrapper.get("[data-testid='design-iteration-warnings']");
    expect(warnings.text()).toContain(
      "Lo Studio ha tolto un elemento che non accetta, come un'immagine o uno script: il mockup resta valido",
    );
    expect(warnings.text()).toContain(
      "Lo Studio ha tolto dagli stili una regola che non accetta: il mockup resta valido",
    );
    expect(warnings.text()).not.toMatch(/ELEMENT_REMOVED|STYLE_RULE_REMOVED|img \(2\)/);
  });

  it("has a sentence of its own for every failure of the contract, of the store and of the provider", () => {
    for (const locale of ["it", "en"] as const) {
      const generic = generationFailureText("A_CODE_NOBODY_RAISES", locale);
      const missing = CONTRACT_FAILURES.filter(
        (code) => generationFailureText(code, locale) === generic,
      );
      expect({ locale, missing }).toEqual({ locale, missing: [] });
    }
    expect(generationFailureText("GENERATION_BUDGET_UNAVAILABLE", "it")).toContain(
      "tetto di spesa",
    );
  });

  it("offers to try again only when trying again can help", () => {
    for (const code of [
      "GENERATION_BUDGET_EXCEEDED",
      "REAL_MOCKUP_MODEL_NOT_CONFIGURED",
      "AUTHENTICATION_FAILED",
      "DESIGN_CONTEXT_CHANGED",
    ]) {
      expect(generationRetryable(code)).toBe(false);
    }
    for (const code of [
      "MOCKUP_QUALITY_REJECTED",
      "TOO_MANY_GENERATIONS",
      "GENERATION_BUDGET_UNAVAILABLE",
      null,
    ]) {
      expect(generationRetryable(code)).toBe(true);
    }
  });
});
