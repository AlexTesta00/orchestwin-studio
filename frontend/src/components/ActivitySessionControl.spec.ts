import { createPinia, setActivePinia } from "pinia";
import { flushPromises, mount, type VueWrapper } from "@vue/test-utils";
import { afterEach, describe, expect, it, vi } from "vitest";

import { ActivityApiError, type ActivityApi } from "../api/activity";
import {
  activityStorageKey,
  useActivityJournalStore,
  type AuthorizedRequest,
} from "../stores/activityJournal";
import { expectAccessible } from "../test/axe";
import ActivitySessionControl from "./ActivitySessionControl.vue";

const PROJECT = "11111111-1111-4111-8111-111111111111";
const STARTED_AT = "2026-10-04T09:00:00+00:00";

const authorize: AuthorizedRequest = (operation) => operation("test-token-not-real");

const WORDS = {
  it: {
    title: "Sessione di prova",
    intro:
      "Registra quali sezioni e dettagli apri e quando. Non registra ciò che scrivi né i contenuti del progetto.",
    label: "Codice della sessione",
    hint: "Usa un codice come SES-P01, senza nomi.",
    start: "Avvia la registrazione",
    active: "Registrazione di tempi e passi attiva · SES-P01",
    stop: "Ferma",
    invalid: "Il codice non è valido.",
    alreadyActive: "Una sessione di prova è già attiva.",
    used: "Questo codice è già stato usato in questo progetto.",
    failed: "La registrazione non è partita. Riprova.",
  },
  en: {
    title: "Study session",
    intro:
      "Records which sections and details you open and when. It does not record what you type or the project's content.",
    label: "Session code",
    hint: "Use a code such as SES-P01, without names.",
    start: "Start recording",
    active: "Recording of times and steps is on · SES-P01",
    stop: "Stop",
    invalid: "The code is not valid.",
    alreadyActive: "A study session is already active.",
    used: "This code was already used in this project.",
    failed: "Recording did not start. Try again.",
  },
} as const;

function fakeApi() {
  return {
    current: vi.fn<ActivityApi["current"]>(),
    session: vi.fn<ActivityApi["session"]>(),
    start: vi.fn<ActivityApi["start"]>(async (_project, code) => ({
      status: "ACTIVITY_SESSION_STARTED" as const,
      session: { code, started_at: STARTED_AT },
    })),
    end: vi.fn<ActivityApi["end"]>(async (_project, code) => ({
      status: "ACTIVITY_SESSION_ENDED" as const,
      session: { code, started_at: STARTED_AT, ended_at: STARTED_AT },
    })),
    record: vi.fn<ActivityApi["record"]>(async (_project, body) => ({
      status: "ACTIVITY_EVENTS_RECORDED" as const,
      recorded: body.events.length,
    })),
  };
}

let wrapper: VueWrapper | null = null;

async function render(locale: "it" | "en" = "it", rowTarget: HTMLElement | null = null) {
  const pinia = createPinia();
  setActivePinia(pinia);
  const api = fakeApi();
  const journal = useActivityJournalStore();
  await journal.open(PROJECT, authorize, { api });
  wrapper = mount(ActivitySessionControl, {
    props: { locale, rowTarget },
    global: { plugins: [pinia] },
    attachTo: document.body,
  });
  return { wrapper, api, journal };
}

async function startWith(control: VueWrapper, code: string): Promise<void> {
  await control.get('[data-testid="activity-session-code"]').setValue(code);
  await control.get("form").trigger("submit");
  await flushPromises();
}

function query(selector: string): HTMLElement | null {
  return document.body.querySelector<HTMLElement>(selector);
}

afterEach(() => {
  wrapper?.unmount();
  wrapper = null;
  useActivityJournalStore().close();
  sessionStorage.clear();
  document.body.innerHTML = "";
});

describe("study session control", () => {
  it.each(["it", "en"] as const)(
    "stays closed at the bottom with its title, sentence, labelled code field and start button in %s",
    async (locale) => {
      const { wrapper: control } = await render(locale);
      const words = WORDS[locale];
      const panel = control.get('[data-testid="activity-session"]');
      const input = control.get('[data-testid="activity-session-code"]');
      const hint = document.getElementById(input.attributes("aria-describedby") ?? "");

      expect(panel.element.tagName).toBe("DETAILS");
      expect(panel.attributes("open")).toBeUndefined();
      expect(control.get("summary").text()).toBe(words.title);
      expect(control.get("form p").text()).toBe(words.intro);
      expect(control.get(`label[for="${input.attributes("id")}"]`).text()).toBe(words.label);
      expect(hint?.textContent?.trim()).toBe(words.hint);
      expect(control.get('[data-testid="activity-session-start"]').text()).toBe(words.start);
      expect(input.attributes()).toMatchObject({
        type: "text",
        maxlength: "24",
        autocomplete: "off",
      });
      for (const target of [
        control.get("summary"),
        input,
        control.get('[data-testid="activity-session-start"]'),
      ]) {
        expect(target.classes()).toContain("min-h-11");
      }
      expect(query('[data-testid="activity-session-active"]')).toBeNull();
      expect(query('[role="alert"]')).toBeNull();
    },
  );

  it("starts recording, shows the row with the code and Stop and moves the focus to Stop", async () => {
    const { wrapper: control, api, journal } = await render("it");

    await startWith(control, " SES-P01 ");

    expect(api.start).toHaveBeenCalledExactlyOnceWith(PROJECT, "SES-P01", "test-token-not-real");
    expect(journal.recording).toBe(true);
    expect(sessionStorage.getItem(activityStorageKey(PROJECT))).toBe("SES-P01");
    const row = control.get('[data-testid="activity-session-active"]');
    expect(row.attributes("role")).toBe("status");
    expect(row.get('[data-testid="activity-session-status"]').text()).toBe(WORDS.it.active);
    const stop = row.get('[data-testid="activity-session-stop"]');
    expect(stop.text()).toBe(WORDS.it.stop);
    expect(stop.attributes("aria-describedby")).toBe(
      row.get('[data-testid="activity-session-status"]').attributes("id"),
    );
    expect(document.activeElement).toBe(stop.element);
    expect(control.find('[data-testid="activity-session"]').exists()).toBe(false);
  });

  it("puts the row at the top of the page when the page gives it a place", async () => {
    const top = document.createElement("div");
    top.dataset.testid = "page-top";
    document.body.prepend(top);
    const { wrapper: control } = await render("en", top);

    await startWith(control, "SES-P01");

    const row = query('[data-testid="activity-session-active"]');
    expect(row?.parentElement).toBe(top);
    expect(row?.textContent).toContain(WORDS.en.active);
    expect(document.activeElement).toBe(
      row?.querySelector('[data-testid="activity-session-stop"]'),
    );
  });

  it.each([
    ["it", "SES-mario", null, WORDS.it.invalid],
    ["en", "P01", null, WORDS.en.invalid],
    ["it", "SES-P01", "ACTIVITY_SESSION_ACTIVE", WORDS.it.alreadyActive],
    ["en", "SES-P01", "ACTIVITY_SESSION_ACTIVE", WORDS.en.alreadyActive],
    ["it", "SES-P01", "ACTIVITY_SESSION_CODE_USED", WORDS.it.used],
    ["en", "SES-P01", "ACTIVITY_SESSION_CODE_USED", WORDS.en.used],
    ["it", "SES-P01", "ACTIVITY_SERVICE_UNAVAILABLE", WORDS.it.failed],
    ["en", "SES-P01", "ACTIVITY_SERVICE_UNAVAILABLE", WORDS.en.failed],
  ] as const)(
    "says in %s why the code %s did not start the recording (%s)",
    async (locale, code, answer, message) => {
      const { wrapper: control, api, journal } = await render(locale);
      if (answer !== null) {
        api.start.mockRejectedValueOnce(
          new ActivityApiError("The activity request failed", {
            status: answer === "ACTIVITY_SERVICE_UNAVAILABLE" ? 503 : 409,
            code: answer,
            payload: null,
          }),
        );
      }

      await startWith(control, code);

      const alert = control.get('[role="alert"]');
      const input = control.get('[data-testid="activity-session-code"]');
      expect(alert.text()).toBe(message);
      expect(input.attributes("aria-describedby")?.split(" ")).toContain(alert.attributes("id"));
      expect(input.attributes("aria-invalid")).toBe(answer === null ? "true" : undefined);
      expect(api.start).toHaveBeenCalledTimes(answer === null ? 0 : 1);
      expect(journal.recording).toBe(false);
      expect(control.find('[data-testid="activity-session-active"]').exists()).toBe(false);

      await input.setValue("SES-P02");
      expect(control.find('[role="alert"]').exists()).toBe(false);
    },
  );

  it("stops from the row and gives the focus back to the closed control", async () => {
    const { wrapper: control, api, journal } = await render("it");
    await startWith(control, "SES-P01");

    await control.get('[data-testid="activity-session-stop"]').trigger("click");
    await flushPromises();

    expect(api.end).toHaveBeenCalledExactlyOnceWith(PROJECT, "SES-P01", "test-token-not-real");
    expect(journal.recording).toBe(false);
    expect(sessionStorage.getItem(activityStorageKey(PROJECT))).toBeNull();
    expect(control.find('[data-testid="activity-session-active"]').exists()).toBe(false);
    const panel = control.get('[data-testid="activity-session"]');
    expect(panel.attributes("open")).toBeUndefined();
    expect(document.activeElement).toBe(panel.get("summary").element);
  });

  it("never shows an error when recording or stopping fails and keeps the row", async () => {
    const { wrapper: control, api, journal } = await render("en");
    await startWith(control, "SES-P01");
    api.record.mockRejectedValueOnce(new TypeError("Failed to fetch"));
    api.record.mockRejectedValueOnce(new TypeError("Failed to fetch"));

    await journal.flush();
    await control.get('[data-testid="activity-session-stop"]').trigger("click");
    await flushPromises();
    expect(api.end).not.toHaveBeenCalled();

    api.end.mockRejectedValueOnce(new TypeError("Failed to fetch"));
    await control.get('[data-testid="activity-session-stop"]').trigger("click");
    await flushPromises();

    expect(api.end).toHaveBeenCalledTimes(1);
    expect(journal.recording).toBe(true);
    expect(control.find('[data-testid="activity-session-active"]').exists()).toBe(true);
    expect(control.get('[data-testid="activity-session-stop"]').attributes("disabled")).toBe(
      undefined,
    );
    expect(query('[role="alert"]')).toBeNull();
  });

  it("wraps on a narrow screen and has no axe violations, closed, open and recording", async () => {
    const { wrapper: control } = await render("it");
    const panel = control.get<HTMLDetailsElement>('[data-testid="activity-session"]');
    await expectAccessible(panel.element);
    panel.element.open = true;
    await expectAccessible(panel.element);
    expect(control.get('[data-testid="activity-session-code"]').classes()).toEqual(
      expect.arrayContaining(["w-full", "min-w-0"]),
    );

    await startWith(control, "SES-P01");

    const row = control.get('[data-testid="activity-session-active"]');
    expect(row.classes()).toEqual(expect.arrayContaining(["flex-wrap", "min-w-0"]));
    expect(row.get('[data-testid="activity-session-status"]').classes()).toEqual(
      expect.arrayContaining(["min-w-0", "wrap-anywhere"]),
    );
    expect(row.get('[data-testid="activity-session-stop"]').classes()).toContain("min-h-11");
    await expectAccessible(row.element);
  });
});
