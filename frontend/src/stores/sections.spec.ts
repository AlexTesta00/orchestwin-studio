import { createPinia, setActivePinia } from "pinia";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { SectionsApiError, type SectionsApi } from "../api/sections";
import type { ProjectSectionsPayload, SectionsAlignmentPayload } from "../types/sections";
import { type AuthorizedRequest, useSectionsStore } from "./sections";

const PROJECT_ID = "11111111-1111-4111-8111-111111111111";
const SECOND_PROJECT_ID = "22222222-2222-4222-8222-222222222222";
const TOKEN = "test-token-not-real";

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

function sections(firstPassComplete = true): ProjectSectionsPayload {
  return {
    first_pass_complete: firstPassComplete,
    sections: [
      { key: "BRIEF", state: "FINE", version_number: 1, reasons: [], blocked: null, codes: [] },
      { key: "TEAM", state: "FINE", version_number: 1, reasons: [], blocked: null, codes: [] },
      {
        key: "USER_TWINS",
        state: "TO_UPDATE",
        version_number: 1,
        reasons: ["PERSPECTIVES_CHANGED"],
        blocked: null,
        codes: [],
      },
      {
        key: "REQUIREMENTS",
        state: "FINE",
        version_number: 1,
        reasons: [],
        blocked: null,
        codes: [],
      },
      { key: "DESIGN", state: "FINE", version_number: 1, reasons: [], blocked: null, codes: [] },
      {
        key: "PACKAGE",
        state: "NOT_STARTED",
        version_number: null,
        reasons: [],
        blocked: null,
        codes: [],
      },
    ],
    alignment: { available: true, sections: ["USER_TWINS"], uncovered_codes: [] },
  };
}

const ALIGNED: SectionsAlignmentPayload = {
  status: "ALIGNED",
  results: [{ key: "USER_TWINS", outcome: "ALIGNED", issue: null, version_number: 2, codes: [] }],
  sections: {
    ...sections(),
    alignment: { available: false, sections: [], uncovered_codes: [] },
  },
};

const authorize: AuthorizedRequest = async <T>(
  operation: (accessToken: string) => Promise<T>,
): Promise<T> => operation(TOKEN);

function fakeApi(
  read: SectionsApi["read"] = async () => sections(),
  align: SectionsApi["align"] = async () => ALIGNED,
) {
  return { read: vi.fn<SectionsApi["read"]>(read), align: vi.fn<SectionsApi["align"]>(align) };
}

function failure(status: number, code: string): SectionsApiError {
  return new SectionsApiError("The sections request failed", { status, code, payload: null });
}

describe("Sections store", () => {
  beforeEach(() => {
    setActivePinia(createPinia());
  });

  it("starts without sections, which is the first pass", () => {
    const store = useSectionsStore();

    expect(store.projectId).toBeNull();
    expect(store.sections).toBeNull();
    expect(store.absent).toBe(false);
    expect(store.firstPassComplete).toBe(false);
    expect(store.pending).toEqual({ read: false, align: false });
    expect(store.alignment).toBeNull();
  });

  it("reads the sections again on every call, one request each", async () => {
    const api = fakeApi();
    const store = useSectionsStore();

    await expect(store.read(PROJECT_ID, authorize, api)).resolves.toEqual(sections());
    await store.read(PROJECT_ID, authorize, api);

    expect(api.read).toHaveBeenCalledTimes(2);
    expect(api.read).toHaveBeenCalledWith(PROJECT_ID, TOKEN);
    expect(store.sections).toEqual(sections());
    expect(store.firstPassComplete).toBe(true);
    expect(store.pending.read).toBe(false);
  });

  it("stays in the first pass when the Studio has no sections route", async () => {
    const store = useSectionsStore();

    await expect(
      store.read(
        PROJECT_ID,
        authorize,
        fakeApi(async () => null),
      ),
    ).resolves.toBeNull();

    expect(store.absent).toBe(true);
    expect(store.sections).toBeNull();
    expect(store.firstPassComplete).toBe(false);
    expect(store.failure).toBeNull();
  });

  it("stays in the first pass until the first design is approved", async () => {
    const store = useSectionsStore();

    await store.read(
      PROJECT_ID,
      authorize,
      fakeApi(async () => sections(false)),
    );

    expect(store.sections).not.toBeNull();
    expect(store.firstPassComplete).toBe(false);
  });

  it("captures and rethrows a failed read and keeps what it had", async () => {
    const unavailable = failure(503, "SECTIONS_SERVICE_UNAVAILABLE");
    const read = vi
      .fn<SectionsApi["read"]>()
      .mockResolvedValueOnce(sections())
      .mockRejectedValueOnce(unavailable);
    const store = useSectionsStore();

    await store.read(PROJECT_ID, authorize, fakeApi(read));
    await expect(store.read(PROJECT_ID, authorize, fakeApi(read))).rejects.toBe(unavailable);

    expect(store.failure).toEqual({
      message: "The sections request failed",
      code: "SECTIONS_SERVICE_UNAVAILABLE",
      status: 503,
    });
    expect(store.sections).toEqual(sections());
    expect(store.pending.read).toBe(false);
  });

  it("keeps the newest answer when an older read ends later", async () => {
    const older = deferred<ProjectSectionsPayload | null>();
    const read = vi
      .fn<SectionsApi["read"]>()
      .mockReturnValueOnce(older.promise)
      .mockResolvedValueOnce(sections(false));
    const store = useSectionsStore();

    const first = store.read(PROJECT_ID, authorize, fakeApi(read));
    await store.read(PROJECT_ID, authorize, fakeApi(read));
    older.resolve(sections());
    await first;

    expect(store.sections).toEqual(sections(false));
    expect(store.pending.read).toBe(false);
  });

  it("forgets the sections of another project and ignores its late answer", async () => {
    const answer = deferred<ProjectSectionsPayload | null>();
    const read = vi
      .fn<SectionsApi["read"]>()
      .mockReturnValueOnce(answer.promise)
      .mockResolvedValueOnce(null);
    const store = useSectionsStore();

    const first = store.read(PROJECT_ID, authorize, fakeApi(read));
    await store.read(SECOND_PROJECT_ID, authorize, fakeApi(read));
    answer.resolve(sections());
    await first;

    expect(store.projectId).toBe(SECOND_PROJECT_ID);
    expect(store.sections).toBeNull();
    expect(store.absent).toBe(true);
  });

  it("runs the gesture once, keeps its answer and takes the sections it returns", async () => {
    const pending = deferred<SectionsAlignmentPayload>();
    const api = fakeApi(undefined, () => pending.promise);
    const store = useSectionsStore();
    await store.read(PROJECT_ID, authorize, api);

    const gesture = store.align(PROJECT_ID, authorize, api);
    expect(store.pending.align).toBe(true);
    await expect(store.align(PROJECT_ID, authorize, api)).resolves.toBeNull();
    expect(api.align).toHaveBeenCalledTimes(1);

    pending.resolve(ALIGNED);
    await expect(gesture).resolves.toEqual(ALIGNED);

    expect(store.pending.align).toBe(false);
    expect(store.alignment).toEqual(ALIGNED);
    expect(store.sections).toEqual(ALIGNED.sections);
    store.clearAlignment();
    expect(store.alignment).toBeNull();
    expect(store.sections).toEqual(ALIGNED.sections);
  });

  it("does not let a read that started before the gesture overwrite its sections", async () => {
    const older = deferred<ProjectSectionsPayload | null>();
    const read = vi
      .fn<SectionsApi["read"]>()
      .mockResolvedValueOnce(sections())
      .mockReturnValueOnce(older.promise);
    const api = fakeApi(read);
    const store = useSectionsStore();
    await store.read(PROJECT_ID, authorize, api);

    const late = store.read(PROJECT_ID, authorize, api);
    await store.align(PROJECT_ID, authorize, api);
    older.resolve(sections());
    await late;

    expect(store.sections).toEqual(ALIGNED.sections);
    expect(store.pending.read).toBe(false);
  });

  it("captures a refused gesture, rethrows it and lets the person try again", async () => {
    const refused = failure(404, "PROJECT_NOT_FOUND");
    const align = vi
      .fn<SectionsApi["align"]>()
      .mockRejectedValueOnce(refused)
      .mockResolvedValueOnce(ALIGNED);
    const store = useSectionsStore();

    await expect(store.align(PROJECT_ID, authorize, fakeApi(undefined, align))).rejects.toBe(
      refused,
    );
    expect(store.alignmentFailure).toEqual({
      message: "The sections request failed",
      code: "PROJECT_NOT_FOUND",
      status: 404,
    });
    expect(store.pending.align).toBe(false);

    await store.align(PROJECT_ID, authorize, fakeApi(undefined, align));
    expect(store.alignmentFailure).toBeNull();
    expect(store.alignment).toEqual(ALIGNED);
  });
});
