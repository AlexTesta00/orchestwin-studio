import { flushPromises, mount, type VueWrapper } from "@vue/test-utils";
import { afterEach, describe, expect, it, vi } from "vitest";

import { ActivityApiError, type ActivityApi } from "../api/activity";
import type { AuthorizedRequest } from "../stores/activityJournal";
import { expectAccessible } from "../test/axe";
import {
  SECTIONS,
  type ActivitySection,
  type ProjectActivity,
  type ProjectActivitySection,
  type ProjectActivitySession,
} from "../types/activity";
import ActivityTimeline from "./ActivityTimeline.vue";

type Locale = "it" | "en";

const PROJECT = "11111111-1111-4111-8111-111111111111";
const OTHER = "22222222-2222-4222-8222-222222222222";
const TOKEN = "test-token-not-real";
const BRIEF_STARTED = "2026-10-08T07:00:00+00:00";
const BRIEF_APPROVED = "2026-10-08T07:12:34+00:00";
const DESIGN_STARTED = "2026-10-08T07:30:00+00:00";
const FIRST_STARTED = "2026-10-08T08:00:00+00:00";
const FIRST_ENDED = "2026-10-08T08:45:00+00:00";
const SECOND_STARTED = "2026-10-08T09:00:00+00:00";
const UNKNOWN_LIMIT = "NEW_LIMIT_OF_THE_MEASURE";
const LIMITS = [
  "ACTOR_DERIVED_FROM_RECORD_KIND",
  "CLIENT_CLOCK_NOT_VERIFIED",
  "ELAPSED_INCLUDES_IDLE_TIME",
  "FAILED_EVALUATION_RUNS_NOT_RECORDED",
  "GENERATION_JOBS_NOT_PERSISTED",
  "PRE_MODEL_REFUSALS_NOT_RECORDED",
  "VIEW_ACTIONS_ONLY_IN_STUDY_SESSIONS",
];

const WORDS = {
  it: {
    title: "Tempi e passi del progetto",
    loading: "Carico…",
    failed: "Non è stato possibile leggere i tempi e i passi del progetto.",
    retry: "Riprova",
    refresh: "Aggiorna",
    missing: "non ancora",
    caption: "Tempi e passi per sezione",
    sections: [
      "Brief",
      "Prospettive",
      "User Twin",
      "Definizione",
      "Design e valutazione",
      "Dossier",
    ],
    columns: [
      "Sezione",
      "Primo evento",
      "Prima approvazione",
      "Tempo fino all'approvazione",
      "Gesti",
      "Generazioni riuscite",
      "Generazioni fallite",
      "Attesa delle generazioni",
    ],
    sessionColumns: ["Permanenza", "Dettagli aperti", "Perché? aperti", "Mockup aperti"],
    headings: ["Totali", "Sessioni di prova", "Limiti della misura"],
    totals: ["Eventi", "Gesti", "Generazioni", "Attesa delle generazioni"],
    events: "12.345",
    noSessions: "Nessuna sessione di prova.",
    facts: ["Inizio", "Fine", "Eventi", "Intervalli scartati"],
    running: "in corso",
    sessionEvents: "1234",
    limits: [
      "Chi ha fatto ogni passo si ricava dal tipo di registrazione.",
      "Gli orari mandati dal browser e da ut vengono dall'orologio del computer, che lo Studio non verifica.",
      "I tempi comprendono le pause.",
      "Le valutazioni dei twin non riuscite non si registrano.",
      "Le generazioni ancora in corso non si salvano: se lo Studio si ferma, possono mancare.",
      "Le richieste rifiutate prima di arrivare al modello non si registrano.",
      "Sezioni, dettagli, Perché? e mockup aperti si contano solo durante una sessione di prova.",
    ],
  },
  en: {
    title: "Times and steps of the project",
    loading: "Loading…",
    failed: "The times and steps of the project could not be read.",
    retry: "Try again",
    refresh: "Refresh",
    missing: "not yet",
    caption: "Times and steps by section",
    sections: [
      "Brief",
      "Perspectives",
      "User Twin",
      "Definition",
      "Design & Evaluation",
      "Dossier",
    ],
    columns: [
      "Section",
      "First event",
      "First approval",
      "Time to approval",
      "Actions",
      "Successful generations",
      "Failed generations",
      "Wait for generations",
    ],
    sessionColumns: ["Time spent", "Details opened", "Why? opened", "Mockups opened"],
    headings: ["Totals", "Study sessions", "Limits of the measure"],
    totals: ["Events", "Actions", "Generations", "Wait for generations"],
    events: "12,345",
    noSessions: "No study session.",
    facts: ["Start", "End", "Events", "Discarded intervals"],
    running: "in progress",
    sessionEvents: "1,234",
    limits: [
      "Who took each step is inferred from the kind of record.",
      "The times sent by the browser and by ut come from the computer's clock, which the Studio does not check.",
      "The times include breaks.",
      "Twin evaluations that failed are not recorded.",
      "Generations still running are not saved: if the Studio stops, they may be missing.",
      "Requests refused before they reach the model are not recorded.",
      "Sections, details, Why? and mockups opened are counted only during a study session.",
    ],
  },
} as const;

const SESSIONS: ProjectActivitySession[] = [
  {
    code: "SES-P01",
    started_at: FIRST_STARTED,
    ended_at: FIRST_ENDED,
    events: 1234,
    sources: ["STUDIO", "WEB"],
    discarded_intervals: 1,
  },
  {
    code: "SES-P02",
    started_at: SECOND_STARTED,
    ended_at: null,
    events: 3,
    sources: ["STUDIO"],
    discarded_intervals: 0,
  },
];

const authorize: AuthorizedRequest = (operation) => operation(TOKEN);

function section(
  key: ActivitySection,
  values: Partial<Omit<ProjectActivitySection, "key">> = {},
): ProjectActivitySection {
  return {
    key,
    first_event_at: null,
    last_event_at: null,
    first_approved_at: null,
    approved_at: null,
    elapsed_seconds: null,
    owner_actions: 0,
    gate: { submissions: 0, approvals: 0, revision_requests: 0, rejections: 0 },
    generations: { count: 0, succeeded: 0, failed: 0, retries: 0, wait_seconds: 0 },
    journal: { opened: 0, dwell_seconds: 0, details_opened: 0, why_opened: 0, mockups_opened: 0 },
    ...values,
  };
}

function activityDocument(
  sessions: ProjectActivitySession[] = [],
  limits: string[] = LIMITS,
): ProjectActivity {
  return {
    kind: "orchestwin.project-activity",
    schema_version: 1,
    project_id: PROJECT,
    events: [],
    sections: [
      section("DESIGN", {
        first_event_at: DESIGN_STARTED,
        owner_actions: 2,
        generations: { count: 3, succeeded: 2, failed: 1, retries: 1, wait_seconds: 182.6 },
        journal: {
          opened: 2,
          dwell_seconds: 3725.2,
          details_opened: 4,
          why_opened: 1,
          mockups_opened: 2,
        },
      }),
      section("BRIEF", {
        first_event_at: BRIEF_STARTED,
        first_approved_at: BRIEF_APPROVED,
        approved_at: BRIEF_APPROVED,
        elapsed_seconds: 754.6,
        owner_actions: 5,
        journal: {
          opened: 1,
          dwell_seconds: 42.9,
          details_opened: 1,
          why_opened: 0,
          mockups_opened: 0,
        },
      }),
      section("PACKAGE"),
      section("TEAM"),
      section("REQUIREMENTS"),
      section("USER_TWINS"),
    ],
    brief_dialogue: { questions: 0, answered: 0, unknown_answers: 0, answer_seconds: [] },
    sessions,
    totals: {
      events: 12345,
      owner_actions: 7,
      generations: 3,
      generation_wait_seconds: 182.6,
      first_event_at: BRIEF_STARTED,
      last_event_at: SECOND_STARTED,
    },
    limits,
  };
}

function moment(locale: Locale, value: string): string {
  return new Intl.DateTimeFormat(locale === "it" ? "it-IT" : "en-GB", {
    day: "numeric",
    month: "short",
    hour: "2-digit",
    minute: "2-digit",
  }).format(new Date(value));
}

function deferred<T>() {
  let resolve: (value: T) => void = () => undefined;
  const promise = new Promise<T>((done) => {
    resolve = done;
  });
  return { promise, resolve };
}

function fakeApi() {
  return {
    current: vi.fn<ActivityApi["current"]>(),
    session: vi.fn<ActivityApi["session"]>(),
    start: vi.fn<ActivityApi["start"]>(),
    end: vi.fn<ActivityApi["end"]>(),
    record: vi.fn<ActivityApi["record"]>(),
  };
}

let wrapper: VueWrapper | null = null;

function render(locale: Locale = "en") {
  const api = fakeApi();
  const control = mount(ActivityTimeline, {
    props: { projectId: PROJECT, authorize, locale, api },
    attachTo: document.body,
  });
  wrapper = control;
  return { control, api };
}

const ROOT = '[data-testid="activity-timeline"]';

function part(name: string): string {
  return `[data-testid="activity-timeline-${name}"]`;
}

function panel(control: VueWrapper): HTMLDetailsElement {
  return control.get<HTMLDetailsElement>(ROOT).element;
}

async function settle(): Promise<void> {
  await new Promise((resolve) => setTimeout(resolve, 0));
  await flushPromises();
}

async function toggle(control: VueWrapper): Promise<void> {
  await control.get("summary").trigger("click");
  await settle();
}

function texts(control: VueWrapper, selector: string): string[] {
  return control.findAll(selector).map((item) => item.text());
}

function row(control: VueWrapper, key: ActivitySection) {
  return control.get(`${part("section")}[data-section="${key}"]`);
}

function cells(control: VueWrapper, key: ActivitySection): string[] {
  return row(control, key)
    .findAll("td")
    .map((cell) => cell.text());
}

function pairs(control: VueWrapper, selector: string): string[][] {
  return control.findAll(selector).map((item) => [item.get("dt").text(), item.get("dd").text()]);
}

afterEach(() => {
  wrapper?.unmount();
  wrapper = null;
  document.body.innerHTML = "";
});

describe("times and steps of the project", () => {
  it.each(["it", "en"] as const)(
    "stays closed and asks nothing until it is opened in %s",
    async (locale) => {
      const { control, api } = render(locale);
      await settle();

      expect(panel(control).tagName).toBe("DETAILS");
      expect(panel(control).open).toBe(false);
      expect(control.get("summary").text()).toBe(WORDS[locale].title);
      expect(control.get("summary").classes()).toContain("min-h-11");
      expect(control.get(part("status")).text()).toBe("");
      expect(control.find(part("sections")).exists()).toBe(false);
      expect(api.current).not.toHaveBeenCalled();
      await expectAccessible(panel(control));
    },
  );

  it("reads the document once at the first opening and shows the six sections in their order", async () => {
    const { control, api } = render("en");
    api.current.mockResolvedValue(activityDocument());

    await toggle(control);

    expect(panel(control).open).toBe(true);
    expect(api.current).toHaveBeenCalledExactlyOnceWith(PROJECT, TOKEN);
    const rows = control.findAll(part("section"));
    expect(rows.map((item) => item.attributes("data-section"))).toEqual([...SECTIONS]);
    expect(rows.map((item) => item.get("th").text())).toEqual(WORDS.en.sections);
    expect(cells(control, "BRIEF")).toEqual([
      moment("en", BRIEF_STARTED),
      moment("en", BRIEF_APPROVED),
      "12 min 34 s",
      "5",
      "0",
      "0",
      "–",
    ]);
    expect(cells(control, "DESIGN")).toEqual([
      moment("en", DESIGN_STARTED),
      "–",
      "–",
      "2",
      "2",
      "1",
      "3 min 02 s",
    ]);
    expect(cells(control, "TEAM")).toEqual(["–", "–", "–", "0", "0", "0", "–"]);
    const approval = row(control, "BRIEF").get('[data-column="first_approved_at"] time');
    expect(approval.attributes("datetime")).toBe(BRIEF_APPROVED);
    const elapsed = row(control, "DESIGN").get('[data-column="elapsed_seconds"] [role="img"]');
    expect(elapsed.attributes("aria-label")).toBe(WORDS.en.missing);

    await toggle(control);
    expect(panel(control).open).toBe(false);
    await toggle(control);

    expect(panel(control).open).toBe(true);
    expect(api.current).toHaveBeenCalledTimes(1);
  });

  it("says it is loading, then reads again with Aggiorna and keeps the focus on the button", async () => {
    const { control, api } = render("it");
    const first = deferred<ProjectActivity>();
    api.current.mockReturnValueOnce(first.promise);

    await toggle(control);

    const status = control.get(part("status"));
    expect(status.attributes("role")).toBe("status");
    expect(status.text()).toBe(WORDS.it.loading);
    expect(status.classes()).not.toContain("sr-only");
    expect(control.find('[aria-busy="true"]').exists()).toBe(true);
    expect(control.find(part("refresh")).exists()).toBe(false);

    first.resolve(activityDocument());
    await flushPromises();

    expect(status.text()).toBe("");
    expect(status.classes()).toContain("sr-only");
    expect(control.find('[aria-busy="true"]').exists()).toBe(false);
    const refresh = control.get<HTMLButtonElement>(part("refresh"));
    expect(refresh.text()).toBe(WORDS.it.refresh);

    const second = deferred<ProjectActivity>();
    api.current.mockReturnValueOnce(second.promise);
    refresh.element.focus();
    await refresh.trigger("click");

    expect(status.text()).toBe(WORDS.it.loading);
    expect(refresh.attributes("disabled")).toBeDefined();
    expect(control.findAll(part("section"))).toHaveLength(6);

    second.resolve(activityDocument(SESSIONS));
    await flushPromises();

    expect(api.current).toHaveBeenCalledTimes(2);
    expect(refresh.attributes("disabled")).toBeUndefined();
    expect(control.findAll(part("session"))).toHaveLength(2);
    expect(document.activeElement).toBe(refresh.element);
  });

  it.each(["it", "en"] as const)(
    "says in %s that the reading failed and reads again from the retry button",
    async (locale) => {
      const { control, api } = render(locale);
      api.current.mockRejectedValueOnce(
        new ActivityApiError("The activity request failed", {
          status: 503,
          code: "ACTIVITY_SERVICE_UNAVAILABLE",
          payload: null,
        }),
      );

      await toggle(control);

      expect(control.get('[role="alert"]').text()).toBe(WORDS[locale].failed);
      const retry = control.get<HTMLButtonElement>(part("retry"));
      expect(retry.text()).toBe(WORDS[locale].retry);
      expect(control.find(part("sections")).exists()).toBe(false);

      const again = deferred<ProjectActivity>();
      api.current.mockReturnValueOnce(again.promise);
      retry.element.focus();
      await retry.trigger("click");

      expect(control.find('[role="alert"]').exists()).toBe(false);
      expect(control.get(part("status")).text()).toBe(WORDS[locale].loading);
      expect(retry.attributes("disabled")).toBeDefined();

      again.resolve(activityDocument());
      await flushPromises();

      expect(api.current).toHaveBeenCalledTimes(2);
      expect(control.find(part("retry")).exists()).toBe(false);
      const refresh = control.get(part("refresh"));
      expect(refresh.element).toBe(retry.element);
      expect(refresh.text()).toBe(WORDS[locale].refresh);
      expect(document.activeElement).toBe(refresh.element);
      expect(control.findAll(part("section"))).toHaveLength(6);
    },
  );

  it("keeps the rows it has and says so when a new reading fails", async () => {
    const { control, api } = render("en");
    api.current.mockResolvedValueOnce(activityDocument());
    api.current.mockRejectedValueOnce(new TypeError("Failed to fetch"));
    await toggle(control);

    await control.get(part("refresh")).trigger("click");
    await flushPromises();

    expect(control.get('[role="alert"]').text()).toBe(WORDS.en.failed);
    expect(control.findAll(part("section"))).toHaveLength(6);
    expect(control.get(part("refresh")).text()).toBe(WORDS.en.refresh);
    expect(control.find(part("retry")).exists()).toBe(false);
  });

  it.each(["it", "en"] as const)(
    "says in %s that there is no study session and leaves out the columns of the sessions",
    async (locale) => {
      const { control, api } = render(locale);
      const base = activityDocument();
      api.current.mockResolvedValue({ ...base, totals: { ...base.totals, generations: 0 } });

      await toggle(control);

      expect(control.get(part("no-sessions")).text()).toBe(WORDS[locale].noSessions);
      expect(control.find(part("sessions")).exists()).toBe(false);
      expect(texts(control, "thead th")).toEqual(WORDS[locale].columns);
      expect(row(control, "BRIEF").findAll("td")).toHaveLength(7);
      const wait = control.get('[data-total="wait"] dd [role="img"]');
      expect(wait.text()).toBe("–");
      expect(wait.attributes("aria-label")).toBe(WORDS[locale].missing);
    },
  );

  it.each(["it", "en"] as const)(
    "lists the study sessions in %s and shows time spent and openings by section",
    async (locale) => {
      const { control, api } = render(locale);
      api.current.mockResolvedValue(activityDocument(SESSIONS));
      const words = WORDS[locale];

      await toggle(control);

      const items = control.findAll(part("session"));
      expect(items.map((item) => item.attributes("data-session-code"))).toEqual([
        "SES-P01",
        "SES-P02",
      ]);
      expect(items.map((item) => item.get("p").text())).toEqual(["SES-P01", "SES-P02"]);
      expect(pairs(control, `${part("session")}[data-session-code="SES-P01"] dl > div`)).toEqual([
        [words.facts[0], moment(locale, FIRST_STARTED)],
        [words.facts[1], moment(locale, FIRST_ENDED)],
        [words.facts[2], words.sessionEvents],
        [words.facts[3], "1"],
      ]);
      expect(pairs(control, `${part("session")}[data-session-code="SES-P02"] dl > div`)).toEqual([
        [words.facts[0], moment(locale, SECOND_STARTED)],
        [words.facts[1], words.running],
        [words.facts[2], "3"],
        [words.facts[3], "0"],
      ]);
      const ended = control.get('[data-session-code="SES-P01"] [data-fact="ended"] time');
      expect(ended.attributes("datetime")).toBe(FIRST_ENDED);
      expect(texts(control, "thead th")).toEqual([...words.columns, ...words.sessionColumns]);
      expect(cells(control, "BRIEF").slice(7)).toEqual(["42 s", "1", "0", "0"]);
      expect(cells(control, "DESIGN").slice(7)).toEqual(["1 h 02 min", "4", "1", "2"]);
      expect(cells(control, "PACKAGE").slice(7)).toEqual(["0 s", "0", "0", "0"]);
    },
  );

  it.each(["it", "en"] as const)(
    "puts the totals and the declared limits in plain %s words and shows an unknown limit by its code",
    async (locale) => {
      const { control, api } = render(locale);
      api.current.mockResolvedValue(activityDocument([], [...LIMITS, UNKNOWN_LIMIT]));
      const words = WORDS[locale];

      await toggle(control);

      expect(texts(control, "h3")).toEqual(words.headings);
      expect(control.get("caption").text()).toBe(words.caption);
      expect(pairs(control, `${part("totals")} > div`)).toEqual([
        [words.totals[0], words.events],
        [words.totals[1], "7"],
        [words.totals[2], "3"],
        [words.totals[3], "3 min 02 s"],
      ]);
      const limits = control.findAll(`${part("limits")} li`);
      expect(limits.map((item) => item.attributes("data-limit"))).toEqual([
        ...LIMITS,
        UNKNOWN_LIMIT,
      ]);
      expect(limits.map((item) => item.text())).toEqual([...words.limits, UNKNOWN_LIMIT]);
      expect(limits.at(-1)?.get("code").text()).toBe(UNKNOWN_LIMIT);
      expect(limits.filter((item) => item.find("code").exists())).toHaveLength(1);
    },
  );

  it("reads the new project when it changes while open and drops the late answer of the old one", async () => {
    const { control, api } = render("en");
    const late = deferred<ProjectActivity>();
    api.current.mockReturnValueOnce(late.promise);
    api.current.mockResolvedValueOnce({ ...activityDocument(SESSIONS), project_id: OTHER });
    await toggle(control);

    await control.setProps({ projectId: OTHER });
    await flushPromises();
    late.resolve(activityDocument());
    await flushPromises();

    expect(api.current.mock.calls).toEqual([
      [PROJECT, TOKEN],
      [OTHER, TOKEN],
    ]);
    expect(control.findAll(part("session"))).toHaveLength(2);

    await toggle(control);
    await control.setProps({ projectId: PROJECT });
    await flushPromises();

    expect(api.current).toHaveBeenCalledTimes(2);
    expect(control.find(part("sections")).exists()).toBe(false);

    api.current.mockResolvedValueOnce(activityDocument());
    await toggle(control);

    expect(api.current).toHaveBeenCalledTimes(3);
    expect(api.current).toHaveBeenLastCalledWith(PROJECT, TOKEN);
    expect(control.find(part("session")).exists()).toBe(false);
  });

  it("names and scopes the table, scrolls it inside its box and has no axe violations", async () => {
    const { control, api } = render("it");
    api.current.mockResolvedValue(activityDocument(SESSIONS, [...LIMITS, UNKNOWN_LIMIT]));

    await toggle(control);

    const region = control.get(part("sections"));
    const caption = region.get("caption");
    expect(region.attributes()).toMatchObject({ role: "region", tabindex: "0" });
    expect(region.attributes("aria-labelledby")).toBe(caption.attributes("id"));
    expect(caption.classes()).toContain("sr-only");
    expect(region.classes()).toEqual(expect.arrayContaining(["overflow-x-auto", "min-w-0"]));
    expect(control.get(ROOT).classes()).toContain("min-w-0");
    const headers = region.findAll("thead th").map((item) => item.attributes("scope"));
    expect(headers).toEqual(Array(12).fill("col"));
    const rowHeaders = region.findAll("tbody th").map((item) => item.attributes("scope"));
    expect(rowHeaders).toEqual(Array(6).fill("row"));
    const wrapping = region.findAll("td").filter((item) => !item.classes("whitespace-nowrap"));
    expect(wrapping).toEqual([]);
    await expectAccessible(panel(control));
  });
});
