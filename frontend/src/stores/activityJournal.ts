import { defineStore } from "pinia";
import { computed, ref, type InjectionKey } from "vue";

import { activityApi, ActivityApiError, type ActivityApi } from "../api/activity";
import { ApiError, onRequestFailure } from "../api/client";
import {
  MAX_BATCH_EVENTS,
  SESSION_CODE_PATTERN,
  TARGET_PATTERN,
  fullMatch,
  type ActivityEventInput,
  type ActivitySection,
  type WebJournalKind,
} from "../types/activity";

export type AuthorizedRequest = <T>(operation: (accessToken: string) => Promise<T>) => Promise<T>;

export interface ActivityContext {
  section: ActivitySection;
  mode: "GUIDED" | "EXPERT";
  locale: "it" | "en";
}

export interface ActivityJournalServices {
  api?: ActivityApi | undefined;
  now?: (() => Date) | undefined;
}

export type ActivityStartOutcome =
  | "STARTED"
  | "ACTIVITY_INPUT_INVALID"
  | "ACTIVITY_SESSION_ACTIVE"
  | "ACTIVITY_SESSION_CODE_USED"
  | "FAILED";

export interface ActivitySignal {
  whyOpened(code: string): void;
  mockupOpened(code: string | null): void;
}

export const activitySignalKey: InjectionKey<ActivitySignal> = Symbol("activity-journal");

export const ACTIVITY_STORAGE_PREFIX = "orchestwin.activity.";
export const SEND_INTERVAL_MILLISECONDS = 5000;
export const MAX_QUEUED_EVENTS = 500;

type Delivery = "SENT" | "DROPPED" | "KEPT" | "STOPPED";

const START_REFUSALS: readonly ActivityStartOutcome[] = [
  "ACTIVITY_INPUT_INVALID",
  "ACTIVITY_SESSION_ACTIVE",
  "ACTIVITY_SESSION_CODE_USED",
];

export function activityStorageKey(projectId: string): string {
  return `${ACTIVITY_STORAGE_PREFIX}${projectId}`;
}

function savedCode(projectId: string): string | null {
  try {
    return window.sessionStorage.getItem(activityStorageKey(projectId));
  } catch {
    return null;
  }
}

function saveCode(projectId: string, code: string | null): void {
  try {
    if (code === null) {
      window.sessionStorage.removeItem(activityStorageKey(projectId));
    } else {
      window.sessionStorage.setItem(activityStorageKey(projectId), code);
    }
  } catch {
    return;
  }
}

export function detailTarget(element: Element): string {
  const value = element.closest("[data-testid]")?.getAttribute("data-testid") ?? null;
  return fullMatch(TARGET_PATTERN, value) ? value : "details";
}

function sessionGone(error: unknown): boolean {
  return (
    error instanceof ActivityApiError &&
    error.status === 409 &&
    error.code === "ACTIVITY_SESSION_NOT_ACTIVE"
  );
}

function retryable(error: unknown): boolean {
  return (
    !(error instanceof ApiError) ||
    error.status === 0 ||
    error.status === 401 ||
    error.status === 408 ||
    error.status === 429 ||
    error.status >= 500
  );
}

async function deliver(
  api: ActivityApi,
  authorize: AuthorizedRequest,
  projectId: string,
  sessionCode: string,
  events: ActivityEventInput[],
  keepalive: boolean,
): Promise<Delivery> {
  try {
    await authorize((token) =>
      api.record(projectId, { session_code: sessionCode, source: "WEB", events }, token, {
        keepalive,
      }),
    );
    return "SENT";
  } catch (error) {
    if (sessionGone(error)) return "STOPPED";
    if (retryable(error)) return "KEPT";
    return error instanceof ApiError && error.status < 400 ? "SENT" : "DROPPED";
  }
}

async function deliverAll(
  api: ActivityApi,
  authorize: AuthorizedRequest,
  projectId: string,
  sessionCode: string,
  events: ActivityEventInput[],
): Promise<void> {
  for (let index = 0; index < events.length; index += MAX_BATCH_EVENTS) {
    const batch = events.slice(index, index + MAX_BATCH_EVENTS);
    const delivery = await deliver(api, authorize, projectId, sessionCode, batch, false);
    if (delivery === "STOPPED") saveCode(projectId, null);
    if (delivery === "STOPPED" || delivery === "KEPT") return;
  }
}

export const useActivityJournalStore = defineStore("activityJournal", () => {
  const projectId = ref<string | null>(null);
  const code = ref<string | null>(null);
  const starting = ref(false);
  const stopping = ref(false);
  const recording = computed(() => code.value !== null);

  let authorize: AuthorizedRequest | null = null;
  let api: ActivityApi = activityApi;
  let now: () => Date = () => new Date();
  let context: ActivityContext = { section: "BRIEF", mode: "GUIDED", locale: "en" };
  let queue: ActivityEventInput[] = [];
  let sending: Promise<Delivery | null> | null = null;
  let timer: ReturnType<typeof setInterval> | null = null;
  let detach: (() => void) | null = null;
  let epoch = 0;
  const inFlight = new Set<ActivityEventInput>();
  const deliveries = new Set<Promise<Delivery | null>>();
  const openedDetails = new WeakSet<HTMLDetailsElement>();

  function push(
    kind: WebJournalKind,
    fields: { target?: string | null; status?: string | null } = {},
  ): void {
    if (code.value === null) return;
    queue.push({
      kind,
      section: context.section,
      target: fields.target ?? null,
      client_at: now().toISOString(),
      duration_ms: null,
      status: fields.status ?? null,
    });
    if (queue.length > MAX_QUEUED_EVENTS) queue = queue.slice(queue.length - MAX_QUEUED_EVENTS);
  }

  function failed(error: ApiError): void {
    if (error instanceof ActivityApiError) return;
    push("REQUEST_FAILED", {
      status: String(error.status),
      target: fullMatch(TARGET_PATTERN, error.detail) ? error.detail : null,
    });
  }

  function pageHidden(): void {
    void flush(true);
  }

  function halt(): void {
    epoch += 1;
    code.value = null;
    queue = [];
    sending = null;
    inFlight.clear();
    deliveries.clear();
    if (timer !== null) clearInterval(timer);
    timer = null;
    detach?.();
    detach = null;
    window.removeEventListener("pagehide", pageHidden);
  }

  function begin(value: string, resumed: boolean): void {
    halt();
    code.value = value;
    detach = onRequestFailure(failed);
    timer = setInterval(() => {
      if (queue.length > 0) void flush();
    }, SEND_INTERVAL_MILLISECONDS);
    window.addEventListener("pagehide", pageHidden);
    push("SECTION_OPENED");
    if (!resumed) {
      push("MODE_CHANGED", { status: context.mode });
      push("LOCALE_SET", { status: context.locale });
    }
  }

  async function transmit(keepalive: boolean): Promise<Delivery | null> {
    const id = projectId.value;
    const session = code.value;
    const request = authorize;
    if (id === null || session === null || request === null) return null;
    const batch = queue.filter((event) => !inFlight.has(event)).slice(0, MAX_BATCH_EVENTS);
    if (batch.length === 0) return null;
    const current = epoch;
    for (const event of batch) inFlight.add(event);
    const delivery = await deliver(api, request, id, session, batch, keepalive);
    if (current !== epoch) return delivery;
    for (const event of batch) inFlight.delete(event);
    if (delivery === "STOPPED") {
      saveCode(id, null);
      halt();
    } else if (delivery !== "KEPT") {
      const sent = new Set(batch);
      queue = queue.filter((event) => !sent.has(event));
    }
    return delivery;
  }

  function send(keepalive: boolean): Promise<Delivery | null> {
    if (!keepalive && sending !== null) return sending;
    const run = transmit(keepalive);
    deliveries.add(run);
    if (!keepalive) sending = run;
    void run.then(() => {
      deliveries.delete(run);
      if (sending === run) sending = null;
    });
    return run;
  }

  async function flush(keepalive = false): Promise<void> {
    await send(keepalive);
  }

  async function drain(): Promise<boolean> {
    while (code.value !== null && queue.length > 0) {
      if (deliveries.size > 0) {
        await Promise.all([...deliveries]);
        continue;
      }
      const delivery = await send(false);
      if (delivery === null || delivery === "KEPT") return false;
    }
    return code.value !== null;
  }

  function close(): void {
    const id = projectId.value;
    const session = code.value;
    const request = authorize;
    if (id !== null && session !== null && request !== null) {
      push("PAGE_HIDDEN");
      const pending = queue.filter((event) => !inFlight.has(event));
      void deliverAll(api, request, id, session, pending);
    }
    halt();
    projectId.value = null;
    authorize = null;
    starting.value = false;
    stopping.value = false;
  }

  async function open(
    id: string,
    request: AuthorizedRequest,
    services: ActivityJournalServices = {},
  ): Promise<void> {
    close();
    projectId.value = id;
    authorize = request;
    api = services.api ?? activityApi;
    now = services.now ?? (() => new Date());
    const saved = id.length > 0 ? savedCode(id) : null;
    if (saved === null) return;
    if (!fullMatch(SESSION_CODE_PATTERN, saved)) {
      saveCode(id, null);
      return;
    }
    const client = api;
    const current = epoch;
    try {
      const state = await request((token) => client.session(id, token));
      if (current !== epoch) return;
      if (state.active && state.session?.code === saved) {
        begin(saved, true);
      } else {
        saveCode(id, null);
      }
    } catch (error) {
      if (current === epoch && error instanceof ActivityApiError && error.status === 404) {
        saveCode(id, null);
      }
    }
  }

  function observe(next: ActivityContext): void {
    const previous = context;
    context = { ...next };
    if (next.mode !== previous.mode) push("MODE_CHANGED", { status: next.mode });
    if (next.locale !== previous.locale) push("LOCALE_SET", { status: next.locale });
    if (next.section !== previous.section) push("SECTION_OPENED");
  }

  async function start(raw: string): Promise<ActivityStartOutcome> {
    const value = raw.trim();
    if (!fullMatch(SESSION_CODE_PATTERN, value)) return "ACTIVITY_INPUT_INVALID";
    const id = projectId.value;
    const request = authorize;
    if (id === null || request === null || starting.value || code.value !== null) return "FAILED";
    const client = api;
    const current = epoch;
    starting.value = true;
    try {
      await request((token) => client.start(id, value, token));
      saveCode(id, value);
      if (current === epoch) {
        starting.value = false;
        begin(value, false);
      }
      return "STARTED";
    } catch (error) {
      if (current === epoch) starting.value = false;
      const refusal = error instanceof ActivityApiError ? error.code : null;
      return START_REFUSALS.find((outcome) => outcome === refusal) ?? "FAILED";
    }
  }

  async function stop(): Promise<boolean> {
    const id = projectId.value;
    const session = code.value;
    const request = authorize;
    if (id === null || session === null || request === null || stopping.value) return false;
    const client = api;
    stopping.value = true;
    push("PAGE_HIDDEN");
    const emptied = await drain();
    if (projectId.value !== id) return false;
    if (code.value !== session) {
      stopping.value = false;
      return code.value === null;
    }
    const current = epoch;
    let ended = false;
    if (emptied) {
      try {
        await request((token) => client.end(id, session, token));
        ended = true;
      } catch (error) {
        ended = sessionGone(error) || (error instanceof ActivityApiError && error.status === 404);
      }
    }
    if (ended) {
      saveCode(id, null);
      if (current === epoch) halt();
    } else if (current === epoch) {
      push("PAGE_VISIBLE");
    }
    if (projectId.value === id) stopping.value = false;
    return ended;
  }

  function visibilityChanged(hidden: boolean): void {
    push(hidden ? "PAGE_HIDDEN" : "PAGE_VISIBLE");
    if (hidden) void flush(true);
  }

  function detailToggled(event: Event): void {
    const element = event.target;
    if (!(element instanceof HTMLDetailsElement)) return;
    if (!element.open) {
      openedDetails.delete(element);
      return;
    }
    if (code.value === null || openedDetails.has(element)) return;
    openedDetails.add(element);
    push("DETAIL_OPENED", { target: detailTarget(element) });
  }

  function whyOpened(value: string): void {
    push("WHY_OPENED", { target: fullMatch(TARGET_PATTERN, value) ? value : "why" });
  }

  function mockupOpened(value: string | null): void {
    push("MOCKUP_OPENED", { target: fullMatch(TARGET_PATTERN, value) ? value : "mockup" });
  }

  return {
    projectId,
    code,
    starting,
    stopping,
    recording,
    open,
    close,
    observe,
    start,
    stop,
    flush,
    visibilityChanged,
    detailToggled,
    whyOpened,
    mockupOpened,
  };
});
