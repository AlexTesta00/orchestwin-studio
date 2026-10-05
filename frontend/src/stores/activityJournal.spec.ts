import { createPinia, setActivePinia } from "pinia";
import { flushPromises } from "@vue/test-utils";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { ActivityApiError, type ActivityApi } from "../api/activity";
import { ApiError } from "../api/client";
import { SectionsApiError } from "../api/sections";
import {
  activityStorageKey,
  detailTarget,
  MAX_QUEUED_EVENTS,
  SEND_INTERVAL_MILLISECONDS,
  useActivityJournalStore,
  type ActivityContext,
  type AuthorizedRequest,
} from "./activityJournal";

const PROJECT = "11111111-1111-4111-8111-111111111111";
const TOKEN = "test-token-not-real";
const STARTED_AT = "2026-10-04T09:00:00+00:00";
const ENDED_AT = "2026-10-04T10:00:00+00:00";
const KEY = activityStorageKey(PROJECT);
const CONTEXT: ActivityContext = { section: "DESIGN", mode: "EXPERT", locale: "it" };

const authorize: AuthorizedRequest = (operation) => operation(TOKEN);

function clock(): () => Date {
  let seconds = 0;
  return () => new Date(Date.UTC(2026, 9, 4, 9, 0, seconds++));
}

function fakeApi() {
  return {
    current: vi.fn<ActivityApi["current"]>(),
    session: vi.fn<ActivityApi["session"]>(async () => ({
      active: true,
      session: { code: "SES-P01", started_at: STARTED_AT },
    })),
    start: vi.fn<ActivityApi["start"]>(async (_project, code) => ({
      status: "ACTIVITY_SESSION_STARTED" as const,
      session: { code, started_at: STARTED_AT },
    })),
    end: vi.fn<ActivityApi["end"]>(async (_project, code) => ({
      status: "ACTIVITY_SESSION_ENDED" as const,
      session: { code, started_at: STARTED_AT, ended_at: ENDED_AT },
    })),
    record: vi.fn<ActivityApi["record"]>(async (_project, body) => ({
      status: "ACTIVITY_EVENTS_RECORDED" as const,
      recorded: body.events.length,
    })),
  };
}

type FakeApi = ReturnType<typeof fakeApi>;

function refusal(status: number, code: string): ActivityApiError {
  return new ActivityApiError("The activity request failed", { status, code, payload: null });
}

function batches(api: FakeApi) {
  return api.record.mock.calls.map(([project, body, token, options]) => ({
    project,
    token,
    keepalive: options?.keepalive === true,
    session: body.session_code,
    source: body.source,
    events: body.events,
  }));
}

function sentEvents(api: FakeApi) {
  return batches(api).flatMap((batch) => batch.events);
}

async function tick(times = 1): Promise<void> {
  for (let round = 0; round < times; round += 1) {
    await vi.advanceTimersByTimeAsync(SEND_INTERVAL_MILLISECONDS);
    await flushPromises();
  }
}

async function recording(api: FakeApi, context: ActivityContext = CONTEXT) {
  const journal = useActivityJournalStore();
  journal.observe(context);
  await journal.open(PROJECT, authorize, { api, now: clock() });
  await expect(journal.start("SES-P01")).resolves.toBe("STARTED");
  return journal;
}

function details(testId: string | null, parentTestId: string | null = null): HTMLDetailsElement {
  const element = document.createElement("details");
  if (testId !== null) element.dataset.testid = testId;
  if (parentTestId === null) {
    document.body.append(element);
  } else {
    const parent = document.createElement("section");
    parent.dataset.testid = parentTestId;
    parent.append(element);
    document.body.append(parent);
  }
  return element;
}

describe("activity journal", () => {
  beforeEach(() => {
    setActivePinia(createPinia());
    sessionStorage.clear();
    vi.useFakeTimers({ toFake: ["setInterval", "clearInterval"] });
  });

  afterEach(() => {
    useActivityJournalStore().close();
    vi.useRealTimers();
    document.body.innerHTML = "";
  });

  it("asks nothing and records nothing while this browser has not started a session", async () => {
    const api = fakeApi();
    const journal = useActivityJournalStore();
    journal.observe(CONTEXT);
    await journal.open(PROJECT, authorize, { api, now: clock() });

    journal.observe({ section: "BRIEF", mode: "GUIDED", locale: "en" });
    journal.whyOpened("REQ-001");
    journal.mockupOpened("DES-001");
    const element = details("design-panel");
    element.open = true;
    journal.detailToggled({ target: element } as unknown as Event);
    journal.visibilityChanged(true);
    journal.visibilityChanged(false);
    window.dispatchEvent(new Event("pagehide"));
    void new SectionsApiError("The sections request failed", {
      status: 409,
      code: "SECTIONS_STALE",
      payload: null,
    });
    await journal.flush();
    await tick(6);
    journal.close();
    await flushPromises();

    expect(journal.recording).toBe(false);
    expect(sessionStorage.getItem(KEY)).toBeNull();
    for (const call of [api.session, api.start, api.end, api.record, api.current]) {
      expect(call).not.toHaveBeenCalled();
    }
  });

  it("starts with a valid code, keeps it in this browser and sends the opening events after five seconds", async () => {
    const api = fakeApi();
    const journal = useActivityJournalStore();
    journal.observe(CONTEXT);
    await journal.open(PROJECT, authorize, { api, now: clock() });

    await expect(journal.start("  SES-P01 ")).resolves.toBe("STARTED");

    expect(api.start).toHaveBeenCalledExactlyOnceWith(PROJECT, "SES-P01", TOKEN);
    expect(sessionStorage.getItem(KEY)).toBe("SES-P01");
    expect(journal.recording).toBe(true);
    expect(journal.code).toBe("SES-P01");
    expect(journal.starting).toBe(false);
    await vi.advanceTimersByTimeAsync(SEND_INTERVAL_MILLISECONDS - 1);
    expect(api.record).not.toHaveBeenCalled();
    await tick();
    expect(batches(api)).toEqual([
      {
        project: PROJECT,
        token: TOKEN,
        keepalive: false,
        session: "SES-P01",
        source: "WEB",
        events: [
          {
            kind: "SECTION_OPENED",
            section: "DESIGN",
            target: null,
            client_at: "2026-10-04T09:00:00.000Z",
            duration_ms: null,
            status: null,
          },
          {
            kind: "MODE_CHANGED",
            section: "DESIGN",
            target: null,
            client_at: "2026-10-04T09:00:01.000Z",
            duration_ms: null,
            status: "EXPERT",
          },
          {
            kind: "LOCALE_SET",
            section: "DESIGN",
            target: null,
            client_at: "2026-10-04T09:00:02.000Z",
            duration_ms: null,
            status: "it",
          },
        ],
      },
    ]);
    await tick(2);
    expect(api.record).toHaveBeenCalledTimes(1);
  });

  it.each(["", "SES-", "ses-p01", "SES-P01 Mario", `SES-${"A".repeat(21)}`, "XYZ-P01", "SES--P01"])(
    "refuses the code %j without asking the Studio",
    async (value) => {
      const api = fakeApi();
      const journal = useActivityJournalStore();
      await journal.open(PROJECT, authorize, { api, now: clock() });

      await expect(journal.start(value)).resolves.toBe("ACTIVITY_INPUT_INVALID");

      expect(api.start).not.toHaveBeenCalled();
      expect(journal.recording).toBe(false);
      expect(sessionStorage.getItem(KEY)).toBeNull();
    },
  );

  it.each([
    [
      "409 ACTIVITY_SESSION_ACTIVE",
      refusal(409, "ACTIVITY_SESSION_ACTIVE"),
      "ACTIVITY_SESSION_ACTIVE",
    ],
    [
      "409 ACTIVITY_SESSION_CODE_USED",
      refusal(409, "ACTIVITY_SESSION_CODE_USED"),
      "ACTIVITY_SESSION_CODE_USED",
    ],
    [
      "422 ACTIVITY_INPUT_INVALID",
      refusal(422, "ACTIVITY_INPUT_INVALID"),
      "ACTIVITY_INPUT_INVALID",
    ],
    ["503 ACTIVITY_SERVICE_UNAVAILABLE", refusal(503, "ACTIVITY_SERVICE_UNAVAILABLE"), "FAILED"],
    ["of a network failure", new TypeError("Failed to fetch"), "FAILED"],
  ])("tells the answer %s to a start and records nothing", async (_label, failure, outcome) => {
    const api = fakeApi();
    api.start.mockRejectedValueOnce(failure);
    const journal = useActivityJournalStore();
    await journal.open(PROJECT, authorize, { api, now: clock() });

    await expect(journal.start("SES-P01")).resolves.toBe(outcome);

    expect(journal.recording).toBe(false);
    expect(journal.starting).toBe(false);
    expect(sessionStorage.getItem(KEY)).toBeNull();
    await tick(2);
    expect(api.record).not.toHaveBeenCalled();
  });

  it("resumes after a reload only when the Studio confirms the same active code", async () => {
    sessionStorage.setItem(KEY, "SES-P01");
    const api = fakeApi();
    const journal = useActivityJournalStore();
    journal.observe(CONTEXT);

    await journal.open(PROJECT, authorize, { api, now: clock() });

    expect(api.session).toHaveBeenCalledExactlyOnceWith(PROJECT, TOKEN);
    expect(journal.recording).toBe(true);
    expect(journal.code).toBe("SES-P01");
    await tick();
    expect(sentEvents(api).map((event) => [event.kind, event.section])).toEqual([
      ["SECTION_OPENED", "DESIGN"],
    ]);
  });

  it.each([
    ["is no longer active", { active: false, session: null }, null],
    [
      "has another code",
      { active: true, session: { code: "SES-P02", started_at: STARTED_AT } },
      null,
    ],
    ["does not know the project", refusal(404, "PROJECT_NOT_FOUND"), null],
    ["cannot be reached", new TypeError("Failed to fetch"), "SES-P01"],
  ])("does not resume a session that %s", async (_label, answer, kept) => {
    sessionStorage.setItem(KEY, "SES-P01");
    const api = fakeApi();
    if (answer instanceof Error) api.session.mockRejectedValueOnce(answer);
    else api.session.mockResolvedValueOnce(answer);
    const journal = useActivityJournalStore();

    await journal.open(PROJECT, authorize, { api, now: clock() });

    expect(journal.recording).toBe(false);
    expect(sessionStorage.getItem(KEY)).toBe(kept);
    await tick(2);
    expect(api.record).not.toHaveBeenCalled();
  });

  it("forgets a stored value that is not a session code without asking the Studio", async () => {
    sessionStorage.setItem(KEY, "Mario Rossi");
    const api = fakeApi();

    await useActivityJournalStore().open(PROJECT, authorize, { api, now: clock() });

    expect(api.session).not.toHaveBeenCalled();
    expect(sessionStorage.getItem(KEY)).toBeNull();
  });

  it("sends at most fifty events a batch and keeps at most five hundred, dropping the oldest", async () => {
    const api = fakeApi();
    const journal = await recording(api);
    const codes = Array.from(
      { length: 520 },
      (_item, index) => `REQ-${String(index + 1).padStart(4, "0")}`,
    );
    for (const code of codes) journal.whyOpened(code);

    await tick(11);

    const sent = batches(api);
    expect(sent).toHaveLength(MAX_QUEUED_EVENTS / 50);
    expect(sent.every((batch) => batch.events.length === 50)).toBe(true);
    expect(sentEvents(api).map((event) => event.target)).toEqual(codes.slice(20));
    expect(sentEvents(api).every((event) => event.kind === "WHY_OPENED")).toBe(true);
  });

  it("keeps the queue when the network or the Studio fail for a while and sends it again", async () => {
    const api = fakeApi();
    api.record
      .mockRejectedValueOnce(new TypeError("Failed to fetch"))
      .mockRejectedValueOnce(refusal(503, "ACTIVITY_SERVICE_UNAVAILABLE"));
    const journal = await recording(api);

    await tick(3);

    expect(api.record).toHaveBeenCalledTimes(3);
    const [first, second, third] = batches(api);
    expect(second?.events).toEqual(first?.events);
    expect(third?.events).toEqual(first?.events);
    expect(journal.recording).toBe(true);
    await tick();
    expect(api.record).toHaveBeenCalledTimes(3);
  });

  it.each(["ACTIVITY_INPUT_INVALID", "ACTIVITY_JOURNAL_FULL"])(
    "drops a batch refused with %s and goes on recording",
    async (code) => {
      const api = fakeApi();
      api.record.mockRejectedValueOnce(refusal(code === "ACTIVITY_JOURNAL_FULL" ? 409 : 422, code));
      const journal = await recording(api);

      await tick();
      journal.whyOpened("REQ-001");
      await tick(2);

      expect(api.record).toHaveBeenCalledTimes(2);
      expect(batches(api)[1]?.events.map((event) => event.target)).toEqual(["REQ-001"]);
      expect(journal.recording).toBe(true);
      expect(sessionStorage.getItem(KEY)).toBe("SES-P01");
    },
  );

  it("stops recording and forgets the code when the Studio says the session is no longer active", async () => {
    const api = fakeApi();
    api.record.mockRejectedValueOnce(refusal(409, "ACTIVITY_SESSION_NOT_ACTIVE"));
    const journal = await recording(api);

    await tick();

    expect(journal.recording).toBe(false);
    expect(journal.code).toBeNull();
    expect(sessionStorage.getItem(KEY)).toBeNull();
    journal.whyOpened("REQ-001");
    void new ApiError(409, "DESIGN_STALE");
    journal.visibilityChanged(true);
    await tick(3);
    expect(api.record).toHaveBeenCalledTimes(1);
  });

  it("sends at once and kept alive when the page is hidden or left", async () => {
    const api = fakeApi();
    const journal = await recording(api);

    journal.visibilityChanged(true);
    await flushPromises();
    expect(batches(api)).toHaveLength(1);
    expect(batches(api)[0]?.keepalive).toBe(true);
    expect(batches(api)[0]?.events.map((event) => event.kind)).toEqual([
      "SECTION_OPENED",
      "MODE_CHANGED",
      "LOCALE_SET",
      "PAGE_HIDDEN",
    ]);

    journal.visibilityChanged(false);
    await flushPromises();
    expect(api.record).toHaveBeenCalledTimes(1);
    window.dispatchEvent(new Event("pagehide"));
    await flushPromises();
    expect(batches(api)[1]).toMatchObject({ keepalive: true });
    expect(batches(api)[1]?.events.map((event) => [event.kind, event.section])).toEqual([
      ["PAGE_VISIBLE", "DESIGN"],
    ]);
  });

  it("records the section, the mode and the language at every change while recording", async () => {
    const api = fakeApi();
    const journal = await recording(api);

    journal.observe({ section: "DESIGN", mode: "EXPERT", locale: "it" });
    journal.observe({ section: "REQUIREMENTS", mode: "EXPERT", locale: "it" });
    journal.observe({ section: "BRIEF", mode: "GUIDED", locale: "en" });
    await tick();

    expect(
      sentEvents(api)
        .slice(3)
        .map((event) => [event.kind, event.section, event.status]),
    ).toEqual([
      ["SECTION_OPENED", "REQUIREMENTS", null],
      ["MODE_CHANGED", "BRIEF", "GUIDED"],
      ["LOCALE_SET", "BRIEF", "en"],
      ["SECTION_OPENED", "BRIEF", null],
    ]);
  });

  it("records every opening of a detail once, with its test id or a fixed placeholder", async () => {
    const api = fakeApi();
    const journal = await recording(api);
    const toggled = (element: HTMLDetailsElement, open: boolean) => {
      element.open = open;
      journal.detailToggled({ target: element } as unknown as Event);
    };
    const own = details("design-alternatives");
    const inherited = details(null, "twin-persona-1");
    const invalid = details("why chain!");
    const bare = details(null);

    toggled(own, true);
    toggled(own, true);
    toggled(inherited, true);
    toggled(invalid, true);
    toggled(bare, true);
    toggled(own, false);
    toggled(own, true);
    journal.detailToggled({ target: document.createElement("dialog") } as unknown as Event);
    await tick();

    expect(
      sentEvents(api)
        .slice(3)
        .map((event) => [event.kind, event.target]),
    ).toEqual([
      ["DETAIL_OPENED", "design-alternatives"],
      ["DETAIL_OPENED", "twin-persona-1"],
      ["DETAIL_OPENED", "details"],
      ["DETAIL_OPENED", "details"],
      ["DETAIL_OPENED", "design-alternatives"],
    ]);
    expect(detailTarget(details(`a${"b".repeat(80)}`))).toBe("details");
    expect(detailTarget(details("d".repeat(80)))).toBe("d".repeat(80));
  });

  it("records the opened Why and mockup with their code or a fixed placeholder", async () => {
    const api = fakeApi();
    const journal = await recording(api);

    journal.whyOpened("REQ-001");
    journal.whyOpened("UT-ABCDEF12-v1:user_twin.goals");
    journal.whyOpened("REQ 001");
    journal.whyOpened("x".repeat(81));
    journal.mockupOpened("DES-002");
    journal.mockupOpened(null);
    journal.mockupOpened("Registro con tabella");
    await tick();

    expect(
      sentEvents(api)
        .slice(3)
        .map((event) => [event.kind, event.target]),
    ).toEqual([
      ["WHY_OPENED", "REQ-001"],
      ["WHY_OPENED", "UT-ABCDEF12-v1:user_twin.goals"],
      ["WHY_OPENED", "why"],
      ["WHY_OPENED", "why"],
      ["MOCKUP_OPENED", "DES-002"],
      ["MOCKUP_OPENED", "mockup"],
      ["MOCKUP_OPENED", "mockup"],
    ]);
  });

  it("records the failed requests of the page and never those of the journal itself", async () => {
    const api = fakeApi();
    const journal = await recording(api);
    journal.observe({ ...CONTEXT, section: "REQUIREMENTS" });

    void new SectionsApiError("The sections request failed", {
      status: 409,
      code: "SECTIONS_STALE",
      payload: null,
    });
    void new ApiError(503, "PROVIDER_UNAVAILABLE");
    void new SectionsApiError("The sections request failed", {
      status: 500,
      code: null,
      payload: null,
    });
    void new ApiError(0, "ACCESS_TOKEN_REQUIRED");
    void new ApiError(200, "INVALID_API_RESPONSE");
    void refusal(409, "ACTIVITY_SESSION_ACTIVE");
    void refusal(503, "ACTIVITY_SERVICE_UNAVAILABLE");
    await tick();

    expect(
      sentEvents(api)
        .slice(3)
        .map((event) => [event.kind, event.section, event.status, event.target]),
    ).toEqual([
      ["SECTION_OPENED", "REQUIREMENTS", null, null],
      ["REQUEST_FAILED", "REQUIREMENTS", "409", "SECTIONS_STALE"],
      ["REQUEST_FAILED", "REQUIREMENTS", "503", "PROVIDER_UNAVAILABLE"],
      ["REQUEST_FAILED", "REQUIREMENTS", "500", null],
    ]);
  });

  it("at Stop records the page as hidden at that instant, sends the queue and only then ends the session", async () => {
    const api = fakeApi();
    const journal = await recording(api);
    await tick();
    journal.whyOpened("REQ-001");

    await expect(journal.stop()).resolves.toBe(true);

    expect(batches(api)).toHaveLength(2);
    expect(
      batches(api)[1]?.events.map((event) => [event.kind, event.section, event.client_at]),
    ).toEqual([
      ["WHY_OPENED", "DESIGN", "2026-10-04T09:00:03.000Z"],
      ["PAGE_HIDDEN", "DESIGN", "2026-10-04T09:00:04.000Z"],
    ]);
    expect(batches(api)[1]?.keepalive).toBe(false);
    expect(api.end).toHaveBeenCalledExactlyOnceWith(PROJECT, "SES-P01", TOKEN);
    expect(api.record.mock.invocationCallOrder[1]).toBeLessThan(
      api.end.mock.invocationCallOrder[0] ?? 0,
    );
    expect(journal.recording).toBe(false);
    expect(journal.stopping).toBe(false);
    expect(sessionStorage.getItem(KEY)).toBeNull();
    journal.whyOpened("REQ-002");
    await tick(2);
    expect(api.record).toHaveBeenCalledTimes(2);
  });

  it("waits for a batch already on its way before sending the rest and ending the session", async () => {
    const api = fakeApi();
    let arrive: () => void = () => undefined;
    api.record.mockImplementationOnce(
      (_project, body) =>
        new Promise((resolve) => {
          arrive = () =>
            resolve({ status: "ACTIVITY_EVENTS_RECORDED", recorded: body.events.length });
        }),
    );
    const journal = await recording(api);
    journal.visibilityChanged(true);
    journal.visibilityChanged(false);

    const stopping = journal.stop();
    await flushPromises();
    expect(api.record).toHaveBeenCalledTimes(1);
    expect(api.end).not.toHaveBeenCalled();
    arrive();
    await expect(stopping).resolves.toBe(true);

    expect(batches(api).map((batch) => batch.events.map((event) => event.kind))).toEqual([
      ["SECTION_OPENED", "MODE_CHANGED", "LOCALE_SET", "PAGE_HIDDEN"],
      ["PAGE_VISIBLE", "PAGE_HIDDEN"],
    ]);
    expect(api.record.mock.invocationCallOrder[1]).toBeLessThan(
      api.end.mock.invocationCallOrder[0] ?? 0,
    );
  });

  it.each([
    ["the session already ended", refusal(409, "ACTIVITY_SESSION_NOT_ACTIVE"), true],
    ["the network fails", new TypeError("Failed to fetch"), false],
  ])("stops or keeps recording when %s at the end", async (_label, failure, stopped) => {
    const api = fakeApi();
    api.end.mockRejectedValueOnce(failure);
    const journal = await recording(api);

    await expect(journal.stop()).resolves.toBe(stopped);

    expect(journal.recording).toBe(!stopped);
    expect(journal.stopping).toBe(false);
    expect(sessionStorage.getItem(KEY)).toBe(stopped ? null : "SES-P01");
    await tick();
    expect(sentEvents(api).map((event) => event.kind)).toEqual([
      "SECTION_OPENED",
      "MODE_CHANGED",
      "LOCALE_SET",
      "PAGE_HIDDEN",
      ...(stopped ? [] : ["PAGE_VISIBLE"]),
    ]);
  });

  it("does not end the session while the queue cannot be sent and keeps both events in order", async () => {
    const api = fakeApi();
    api.record.mockRejectedValueOnce(new TypeError("Failed to fetch"));
    const journal = await recording(api);

    await expect(journal.stop()).resolves.toBe(false);

    expect(api.end).not.toHaveBeenCalled();
    expect(journal.recording).toBe(true);
    expect(journal.stopping).toBe(false);
    expect(sessionStorage.getItem(KEY)).toBe("SES-P01");
    await tick();
    expect(batches(api)[1]?.events.map((event) => event.kind)).toEqual([
      "SECTION_OPENED",
      "MODE_CHANGED",
      "LOCALE_SET",
      "PAGE_HIDDEN",
      "PAGE_VISIBLE",
    ]);
  });

  it("closes the page of the project by sending what is left and keeps the code for the return", async () => {
    const api = fakeApi();
    const journal = await recording(api);
    journal.whyOpened("REQ-001");

    journal.close();
    await flushPromises();

    expect(journal.recording).toBe(false);
    expect(sessionStorage.getItem(KEY)).toBe("SES-P01");
    expect(sentEvents(api).map((event) => event.kind)).toEqual([
      "SECTION_OPENED",
      "MODE_CHANGED",
      "LOCALE_SET",
      "WHY_OPENED",
      "PAGE_HIDDEN",
    ]);

    await journal.open(PROJECT, authorize, { api, now: clock() });
    expect(journal.recording).toBe(true);
    await tick();
    expect(sentEvents(api).at(-1)?.kind).toBe("SECTION_OPENED");
  });
});
