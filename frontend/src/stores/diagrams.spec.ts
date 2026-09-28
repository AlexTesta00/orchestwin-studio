import { createPinia, setActivePinia } from "pinia";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { DiagramsApiError, type DiagramsApi } from "../api/diagrams";
import type {
  DiagramKind,
  DiagramLocale,
  DiagramPayload,
  DiagramStage,
  ProjectDiagramsPayload,
} from "../types/diagrams";
import { type AuthorizedRequest, useDiagramsStore } from "./diagrams";

const PROJECT_ID = "11111111-1111-4111-8111-111111111111";
const SECOND_PROJECT_ID = "22222222-2222-4222-8222-222222222222";

interface Deferred<T> {
  promise: Promise<T>;
  resolve: (value: T) => void;
  reject: (reason: unknown) => void;
}

function deferred<T>(): Deferred<T> {
  let resolve!: (value: T) => void;
  let reject!: (reason: unknown) => void;
  const promise = new Promise<T>((onResolve, onReject) => {
    resolve = onResolve;
    reject = onReject;
  });

  return { promise, resolve, reject };
}

function diagram(
  key: string,
  stage: DiagramStage,
  kind: DiagramKind,
  title: string,
): DiagramPayload {
  return {
    key,
    stage,
    kind,
    subject: null,
    title,
    description: `${title}.`,
    path: `diagrams/${key}.mmd`,
    source: "flowchart LR\n  owner --> studio",
  };
}

function diagramsPayload(locale: DiagramLocale): ProjectDiagramsPayload {
  const italian = locale === "it";

  return {
    project_id: PROJECT_ID,
    locale,
    mermaid_version: "12.0.0",
    system_name: "Reception desk",
    requirements: {
      version_id: "33333333-3333-4333-8333-333333333333",
      version_number: 2,
      content_hash: "a".repeat(64),
    },
    design: {
      version_id: "44444444-4444-4444-8444-444444444444",
      version_number: 1,
      content_hash: "b".repeat(64),
    },
    diagrams: [
      diagram(
        "requirements/use-cases",
        "requirements",
        "USE_CASES",
        italian ? "Casi d'uso" : "Use cases",
      ),
      diagram(
        "requirements/traceability",
        "requirements",
        "REQUIREMENTS_TRACEABILITY",
        italian ? "Tracciabilità" : "Traceability",
      ),
      diagram(
        "design/screen-map",
        "design",
        "SCREEN_MAP",
        italian ? "Mappa schermate" : "Screen map",
      ),
    ],
  };
}

const ENGLISH = diagramsPayload("en");
const ITALIAN = diagramsPayload("it");

const authorize: AuthorizedRequest = async <T>(
  operation: (accessToken: string) => Promise<T>,
): Promise<T> => operation("access-token");

function answering(result: ProjectDiagramsPayload | Promise<ProjectDiagramsPayload>): DiagramsApi {
  return { current: async () => result };
}

function byLocale(
  english: Promise<ProjectDiagramsPayload>,
  italian: ProjectDiagramsPayload | Promise<ProjectDiagramsPayload>,
): DiagramsApi {
  return { current: async (_projectId, locale) => (locale === "en" ? english : italian) };
}

function failing(error: unknown): DiagramsApi {
  return {
    current: async () => {
      throw error;
    },
  };
}

function failure(status: number, code: string): DiagramsApiError {
  return new DiagramsApiError("The diagrams request failed", { status, code, payload: null });
}

describe("Diagrams store", () => {
  beforeEach(() => {
    setActivePinia(createPinia());
  });

  it("starts empty and idle", () => {
    const store = useDiagramsStore();

    expect(store.projectId).toBeNull();
    expect(store.locale).toBeNull();
    expect(store.result).toBeNull();
    expect(store.diagrams).toEqual([]);
    expect(store.byStage("requirements")).toEqual([]);
    expect(store.isBusy).toBe(false);
  });

  it("loads the diagrams in the requested locale and filters them by stage", async () => {
    const current = vi.fn<DiagramsApi["current"]>(async () => ITALIAN);
    const store = useDiagramsStore();

    const result = await store.load(PROJECT_ID, "it", authorize, { current });

    expect(current).toHaveBeenCalledWith(PROJECT_ID, "it", "access-token");
    expect(result).toEqual(ITALIAN);
    expect(store.projectId).toBe(PROJECT_ID);
    expect(store.locale).toBe("it");
    expect(store.result).toEqual(ITALIAN);
    expect(store.diagrams).toEqual(ITALIAN.diagrams);
    expect(store.byStage("requirements").map((item) => item.key)).toEqual([
      "requirements/use-cases",
      "requirements/traceability",
    ]);
    expect(store.byStage("design").map((item) => item.title)).toEqual(["Mappa schermate"]);
    expect(store.error).toBeNull();
    expect(store.pending.load).toBe(false);
  });

  it("keeps the loading flag until the latest request settles and ignores an older locale", async () => {
    const english = deferred<ProjectDiagramsPayload>();
    const italian = deferred<ProjectDiagramsPayload>();
    const api = byLocale(english.promise, italian.promise);
    const store = useDiagramsStore();

    const englishLoad = store.load(PROJECT_ID, "en", authorize, api);

    expect(store.pending.load).toBe(true);
    expect(store.isBusy).toBe(true);

    const italianLoad = store.load(PROJECT_ID, "it", authorize, api);
    english.resolve(ENGLISH);

    expect(await englishLoad).toEqual(ENGLISH);
    expect(store.pending.load).toBe(true);
    expect(store.locale).toBeNull();
    expect(store.result).toBeNull();

    italian.resolve(ITALIAN);
    await italianLoad;

    expect(store.pending.load).toBe(false);
    expect(store.isBusy).toBe(false);
    expect(store.locale).toBe("it");
    expect(store.result).toEqual(ITALIAN);
  });

  it("keeps the latest locale when the response of an older locale arrives last", async () => {
    const english = deferred<ProjectDiagramsPayload>();
    const api = byLocale(english.promise, ITALIAN);
    const store = useDiagramsStore();

    const englishLoad = store.load(PROJECT_ID, "en", authorize, api);
    await store.load(PROJECT_ID, "it", authorize, api);
    english.resolve(ENGLISH);
    await englishLoad;

    expect(store.locale).toBe("it");
    expect(store.result).toEqual(ITALIAN);
    expect(store.byStage("design").map((item) => item.title)).toEqual(["Mappa schermate"]);
    expect(store.pending.load).toBe(false);
  });

  it("does not report the failure of a request that a newer one replaced", async () => {
    const english = deferred<ProjectDiagramsPayload>();
    const api = byLocale(english.promise, ITALIAN);
    const store = useDiagramsStore();
    const unavailable = failure(503, "DIAGRAM_SERVICE_UNAVAILABLE");

    const englishLoad = store.load(PROJECT_ID, "en", authorize, api);
    await store.load(PROJECT_ID, "it", authorize, api);
    english.reject(unavailable);

    await expect(englishLoad).rejects.toBe(unavailable);
    expect(store.error).toBeNull();
    expect(store.result).toEqual(ITALIAN);
    expect(store.pending.load).toBe(false);
  });

  it("treats a project without requirements as no diagrams yet", async () => {
    const store = useDiagramsStore();
    await store.load(PROJECT_ID, "it", authorize, answering(ITALIAN));

    const notFound = failing(failure(404, "DIAGRAMS_NOT_FOUND"));
    const result = await store.load(PROJECT_ID, "en", authorize, notFound);

    expect(result).toBeNull();
    expect(store.result).toBeNull();
    expect(store.locale).toBe("en");
    expect(store.diagrams).toEqual([]);
    expect(store.byStage("requirements")).toEqual([]);
    expect(store.error).toBeNull();
    expect(store.pending.load).toBe(false);
  });

  it("captures and rethrows any other failure and clears it on the next load", async () => {
    const store = useDiagramsStore();
    const unavailable = failure(503, "DIAGRAM_SERVICE_UNAVAILABLE");
    const offline = new TypeError("Failed to fetch");

    const unavailableLoad = store.load(PROJECT_ID, "en", authorize, failing(unavailable));

    await expect(unavailableLoad).rejects.toBe(unavailable);
    expect(store.error).toEqual({
      message: "The diagrams request failed",
      code: "DIAGRAM_SERVICE_UNAVAILABLE",
      status: 503,
    });
    expect(store.pending.load).toBe(false);

    const offlineLoad = store.load(PROJECT_ID, "en", authorize, failing(offline));

    await expect(offlineLoad).rejects.toBe(offline);
    expect(store.error).toEqual({ message: "Failed to fetch", code: null, status: null });

    await store.load(PROJECT_ID, "en", authorize, answering(ENGLISH));

    expect(store.error).toBeNull();
    expect(store.result).toEqual(ENGLISH);
  });

  it("ignores a response that arrives after the active project changes", async () => {
    const pending = deferred<ProjectDiagramsPayload>();
    const store = useDiagramsStore();

    const staleLoad = store.load(PROJECT_ID, "en", authorize, answering(pending.promise));
    store.activateProject(SECOND_PROJECT_ID);
    pending.resolve(ENGLISH);
    await staleLoad;

    expect(store.projectId).toBe(SECOND_PROJECT_ID);
    expect(store.locale).toBeNull();
    expect(store.result).toBeNull();
    expect(store.pending.load).toBe(false);
    expect(store.error).toBeNull();
  });

  it("resets the state and drops the responses still in flight", async () => {
    const pending = deferred<ProjectDiagramsPayload>();
    const store = useDiagramsStore();
    await store.load(PROJECT_ID, "it", authorize, answering(ITALIAN));

    const staleLoad = store.load(PROJECT_ID, "en", authorize, answering(pending.promise));
    store.reset();

    expect(store.projectId).toBeNull();
    expect(store.locale).toBeNull();
    expect(store.result).toBeNull();
    expect(store.diagrams).toEqual([]);
    expect(store.pending.load).toBe(false);

    store.activateProject(PROJECT_ID);
    pending.resolve(ENGLISH);
    await staleLoad;

    expect(store.projectId).toBe(PROJECT_ID);
    expect(store.locale).toBeNull();
    expect(store.result).toBeNull();
    expect(store.error).toBeNull();
  });
});
