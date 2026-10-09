import { createPinia, setActivePinia } from "pinia";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { ApiError } from "../api/client";
import { DesignCritiqueApiError, type DesignCritiqueApi } from "../api/designCritique";
import type {
  DesignCritiqueResultPayload,
  DesignCritiqueRunPayload,
  DesignCritiqueSourcePayload,
} from "../types/designCritique";
import {
  CRITIQUE_FILE_TOO_LARGE,
  CRITIQUE_FILE_TYPE,
  CRITIQUE_MAX_FILE_BYTES,
  CRITIQUE_SHOT_DISCARDED,
  critiqueFileProblem,
  useDesignCritiqueStore,
  type AuthorizedCritiqueRequest,
} from "./designCritique";

const PROJECT = "11111111-1111-4111-8111-111111111111";
const OTHER_PROJECT = "11111111-1111-4111-8111-111111111999";
const SOURCE_ID = "22222222-2222-4222-8222-222222222222";
const TWIN_ID = "44444444-4444-4444-8444-444444444444";

const authorize: AuthorizedCritiqueRequest = (operation) => operation("token");

const SOURCE: DesignCritiqueSourcePayload = {
  id: SOURCE_ID,
  project_id: PROJECT,
  kind: "IMAGE",
  title: "Booking page",
  url: null,
  page: null,
  shots: [
    {
      code: "SCR-001",
      media_type: "image/png",
      byte_size: 8,
      sha256: "a".repeat(64),
      width: 1170,
      height: 2532,
      viewport_width: null,
    },
  ],
  created_at: "2026-10-09T10:00:00Z",
  content_hash: "b".repeat(64),
};

function run(id: string, source: DesignCritiqueSourcePayload = SOURCE): DesignCritiqueRunPayload {
  return {
    id,
    project_id: PROJECT,
    source,
    twins: [{ twin_id: TWIN_ID, version_number: 1, name: "Giulia" }],
    responses: [
      {
        twin_id: TWIN_ID,
        twin_version: 1,
        summary: "I find the times, but the button is far.",
        evidence_gaps: [],
        findings: [],
      },
    ],
    verdicts: [{ twin_id: TWIN_ID, anchor_key: "SCR-001", verdict: "WORKS" }],
    started_at: "2026-10-09T10:00:00Z",
    completed_at: "2026-10-09T10:02:22Z",
    duration_seconds: 142,
    cost_microusd: 0,
    content_hash: "c".repeat(64),
  };
}

const NEW_RUN = run("33333333-3333-4333-8333-333333333333");
const OLD_RUN = run("33333333-3333-4333-8333-333333333000", {
  ...SOURCE,
  id: "22222222-2222-4222-8222-222222222000",
  title: "Old home page",
});

function recorded(value: DesignCritiqueRunPayload = NEW_RUN): DesignCritiqueResultPayload {
  return { status: "DESIGN_CRITIQUE_RECORDED", run: value };
}

function fakeApi() {
  return {
    uploadSource: vi.fn<DesignCritiqueApi["uploadSource"]>(async () => SOURCE),
    sources: vi.fn<DesignCritiqueApi["sources"]>(async () => [OLD_RUN.source]),
    shot: vi.fn<DesignCritiqueApi["shot"]>(
      async () => new Blob(["fake-png"], { type: "image/png" }),
    ),
    critique: vi.fn<DesignCritiqueApi["critique"]>(async () => recorded()),
    runs: vi.fn<DesignCritiqueApi["runs"]>(async () => [OLD_RUN]),
  } satisfies DesignCritiqueApi;
}

function refusal(status: number, code: string | null): DesignCritiqueApiError {
  return new DesignCritiqueApiError("The design critique request failed", {
    status,
    code,
    payload: code === null ? null : { detail: { code } },
  });
}

function image(name = "booking.png", type = "image/png", size: number | null = null): File {
  const file = new File(["fake-png"], name, { type });
  if (size !== null) {
    Object.defineProperty(file, "size", { configurable: true, value: size });
  }
  return file;
}

function deferred<T>() {
  let resolve: (value: T) => void = () => undefined;
  const promise = new Promise<T>((done) => {
    resolve = done;
  });
  return { promise, resolve };
}

const URL_METHODS = ["createObjectURL", "revokeObjectURL"] as const;
const originals = Object.fromEntries(
  URL_METHODS.map((name) => [name, Object.getOwnPropertyDescriptor(URL, name)]),
);

function stubObjectUrls() {
  let created = 0;
  const createObjectURL = vi.fn<(blob: Blob) => string>(() => `blob:shot-${(created += 1)}`);
  const revokeObjectURL = vi.fn<(url: string) => void>();
  Object.defineProperty(URL, "createObjectURL", {
    configurable: true,
    writable: true,
    value: createObjectURL,
  });
  Object.defineProperty(URL, "revokeObjectURL", {
    configurable: true,
    writable: true,
    value: revokeObjectURL,
  });
  return { createObjectURL, revokeObjectURL };
}

describe("design critique store", () => {
  beforeEach(() => {
    setActivePinia(createPinia());
  });

  afterEach(() => {
    for (const name of URL_METHODS) {
      const original = originals[name];
      if (original === undefined) {
        Reflect.deleteProperty(URL, name);
      } else {
        Object.defineProperty(URL, name, original);
      }
    }
  });

  it("checks the type and the size of a file as the Studio does", () => {
    expect(critiqueFileProblem(image())).toBeNull();
    expect(critiqueFileProblem(image("photo.jpg", "image/jpeg"))).toBeNull();
    expect(critiqueFileProblem(image("logo.gif", "image/gif"))).toBe(CRITIQUE_FILE_TYPE);
    expect(critiqueFileProblem(image("logo.svg", "image/svg+xml"))).toBe(CRITIQUE_FILE_TYPE);
    expect(critiqueFileProblem(image("big.png", "image/png", CRITIQUE_MAX_FILE_BYTES))).toBeNull();
    expect(critiqueFileProblem(image("big.png", "image/png", CRITIQUE_MAX_FILE_BYTES + 1))).toBe(
      CRITIQUE_FILE_TOO_LARGE,
    );
  });

  it.each([
    ["a file that is not an image", image("notes.pdf", "application/pdf"), CRITIQUE_FILE_TYPE],
    [
      "an image larger than 5 MB",
      image("huge.jpg", "image/jpeg", CRITIQUE_MAX_FILE_BYTES + 1),
      CRITIQUE_FILE_TOO_LARGE,
    ],
  ])("refuses %s without calling the Studio", async (_case, file, code) => {
    const api = fakeApi();
    const store = useDesignCritiqueStore();

    const refused = store.critiqueImage(PROJECT, file, null, "en-US", authorize, api);

    await expect(refused).rejects.toBeInstanceOf(DesignCritiqueApiError);
    await expect(refused).rejects.toMatchObject({ status: 0, code });
    expect(store.error?.code).toBe(code);
    expect(api.uploadSource).not.toHaveBeenCalled();
    expect(api.critique).not.toHaveBeenCalled();
    expect(store.pending).toEqual({ load: false, upload: false, critique: false });
  });

  it("uploads the image as a form, asks for the critique and puts the new run first", async () => {
    const api = fakeApi();
    const upload = deferred<DesignCritiqueSourcePayload>();
    const answer = deferred<DesignCritiqueResultPayload>();
    api.uploadSource.mockImplementationOnce(() => upload.promise);
    api.critique.mockImplementationOnce(() => answer.promise);
    const store = useDesignCritiqueStore();
    await store.load(PROJECT, authorize, api);
    const file = image();

    const asked = store.critiqueImage(PROJECT, file, "  Booking page ", "it-IT", authorize, api);
    expect(store.pending).toEqual({ load: false, upload: true, critique: false });
    upload.resolve(SOURCE);
    await vi.waitFor(() => expect(store.pending.critique).toBe(true));
    expect(store.pending.upload).toBe(false);
    answer.resolve(recorded());

    expect(await asked).toEqual(NEW_RUN);
    expect(store.pending).toEqual({ load: false, upload: false, critique: false });
    expect(store.runs).toEqual([NEW_RUN, OLD_RUN]);
    expect(store.lastRun).toEqual(NEW_RUN);
    expect(store.latestRun).toEqual(NEW_RUN);
    expect(store.sources.map((item) => item.id)).toEqual([SOURCE_ID, OLD_RUN.source.id]);
    expect(store.error).toBeNull();

    const [project, form, token] = api.uploadSource.mock.calls[0] ?? [];
    expect(project).toBe(PROJECT);
    expect(token).toBe("token");
    expect([...(form?.keys() ?? [])]).toEqual(["kind", "title", "shots"]);
    expect(form?.get("kind")).toBe("IMAGE");
    expect(form?.get("title")).toBe("Booking page");
    expect((form?.get("shots") as File).name).toBe("booking.png");
    expect(await (form?.get("shots") as File).text()).toBe("fake-png");
    expect(api.critique).toHaveBeenCalledWith(
      PROJECT,
      { source_id: SOURCE_ID, locale: "it-IT" },
      "token",
    );
  });

  it("leaves the title out of the form when it is empty", async () => {
    const api = fakeApi();
    const store = useDesignCritiqueStore();

    await store.critiqueImage(PROJECT, image(), "   ", "en-US", authorize, api);
    await store.critiqueImage(PROJECT, image("other.png"), null, "en-US", authorize, api);

    expect(api.uploadSource.mock.calls.map((call) => [...call[1].keys()])).toEqual([
      ["kind", "shots"],
      ["kind", "shots"],
    ]);
  });

  it("asks again after a failed critique without uploading the same image twice", async () => {
    const api = fakeApi();
    api.critique.mockRejectedValueOnce(refusal(502, "DESIGN_CRITIQUE_FAILED"));
    const store = useDesignCritiqueStore();
    const file = image();

    await expect(
      store.critiqueImage(PROJECT, file, "Booking page", "en-US", authorize, api),
    ).rejects.toMatchObject({ code: "DESIGN_CRITIQUE_FAILED" });
    expect(store.error?.code).toBe("DESIGN_CRITIQUE_FAILED");
    expect(store.pending.critique).toBe(false);

    expect(
      await store.critiqueImage(PROJECT, file, "Booking page", "en-US", authorize, api),
    ).toEqual(NEW_RUN);
    expect(store.error).toBeNull();
    expect(api.uploadSource).toHaveBeenCalledTimes(1);
    expect(api.critique).toHaveBeenCalledTimes(2);

    await store.critiqueImage(PROJECT, file, "Booking page", "en-US", authorize, api);
    await store.critiqueImage(PROJECT, image(), "Booking page", "en-US", authorize, api);
    expect(api.uploadSource).toHaveBeenCalledTimes(3);
  });

  it.each([
    [
      "an upload refused for its size",
      "upload",
      refusal(413, null),
      "DESIGN_CRITIQUE_IMAGE_TOO_LARGE",
    ],
    ["an upload that fails", "upload", refusal(500, null), "DESIGN_CRITIQUE_UPLOAD_FAILED"],
    [
      "an upload refused without approved twins",
      "upload",
      refusal(409, "DESIGN_CRITIQUE_TWINS_REQUIRED"),
      "DESIGN_CRITIQUE_TWINS_REQUIRED",
    ],
    [
      "a critique without a model that sees images",
      "critique",
      refusal(503, "DESIGN_CRITIQUE_PROVIDER_UNSUPPORTED"),
      "DESIGN_CRITIQUE_PROVIDER_UNSUPPORTED",
    ],
    [
      "a critique cut by the network",
      "critique",
      new TypeError("Failed to fetch"),
      "DESIGN_CRITIQUE_FAILED",
    ],
    [
      "a critique asked after the session expired",
      "critique",
      new ApiError(401, "invalid_authentication"),
      "invalid_authentication",
    ],
  ] as const)("names %s", async (_case, step, failure, code) => {
    const api = fakeApi();
    if (step === "upload") {
      api.uploadSource.mockRejectedValueOnce(failure);
    } else {
      api.critique.mockRejectedValueOnce(failure);
    }
    const store = useDesignCritiqueStore();

    await expect(store.critiqueImage(PROJECT, image(), null, "en-US", authorize, api)).rejects.toBe(
      failure,
    );

    expect(store.error?.code).toBe(code);
    expect(store.runs).toEqual([]);
    expect(store.pending).toEqual({ load: false, upload: false, critique: false });
  });

  it("loads the critiques and the supplied designs of the project", async () => {
    const api = fakeApi();
    const store = useDesignCritiqueStore();

    await store.load(PROJECT, authorize, api);

    expect(api.runs).toHaveBeenCalledWith(PROJECT, "token");
    expect(api.sources).toHaveBeenCalledWith(PROJECT, "token");
    expect(store.projectId).toBe(PROJECT);
    expect(store.runs).toEqual([OLD_RUN]);
    expect(store.sources).toEqual([OLD_RUN.source]);
    expect(store.loaded).toBe(true);
    expect(store.pending.load).toBe(false);
  });

  it("keeps the critiques when the supplied designs cannot be read and names a failed load", async () => {
    const api = fakeApi();
    api.sources.mockRejectedValueOnce(refusal(502, null));
    const store = useDesignCritiqueStore();

    await store.load(PROJECT, authorize, api);
    expect(store.runs).toEqual([OLD_RUN]);
    expect(store.sources).toEqual([]);
    expect(store.error).toBeNull();

    api.runs.mockRejectedValueOnce(refusal(503, null));
    await expect(store.load(PROJECT, authorize, api)).rejects.toBeInstanceOf(
      DesignCritiqueApiError,
    );
    expect(store.error?.code).toBe("DESIGN_CRITIQUE_LOAD_FAILED");
    expect(store.runs).toEqual([OLD_RUN]);
    expect(store.pending.load).toBe(false);
  });

  it("starts again for another project and ignores a late answer of the previous one", async () => {
    const api = fakeApi();
    const answer = deferred<DesignCritiqueResultPayload>();
    api.critique.mockImplementationOnce(() => answer.promise);
    const store = useDesignCritiqueStore();
    await store.load(PROJECT, authorize, api);

    const late = store.critiqueImage(PROJECT, image(), null, "en-US", authorize, api);
    await vi.waitFor(() => expect(store.pending.critique).toBe(true));
    api.runs.mockResolvedValueOnce([]);
    await store.load(OTHER_PROJECT, authorize, api);
    answer.resolve(recorded());

    expect(await late).toEqual(NEW_RUN);
    expect(store.projectId).toBe(OTHER_PROJECT);
    expect(store.runs).toEqual([]);
    expect(store.lastRun).toBeNull();
    expect(store.pending).toEqual({ load: false, upload: false, critique: false });

    store.reset();
    expect(store.projectId).toBeNull();
    expect(store.loaded).toBe(false);
  });

  it("creates one address per screenshot, reuses it and revokes them all", async () => {
    const urls = stubObjectUrls();
    const api = fakeApi();
    const store = useDesignCritiqueStore();

    const [first, again] = await Promise.all([
      store.shotUrl(PROJECT, SOURCE_ID, "SCR-001", authorize, api),
      store.shotUrl(PROJECT, SOURCE_ID, "SCR-001", authorize, api),
    ]);
    const second = await store.shotUrl(PROJECT, SOURCE_ID, "SCR-002", authorize, api);

    expect([first, again, second]).toEqual(["blob:shot-1", "blob:shot-1", "blob:shot-2"]);
    expect(await store.shotUrl(PROJECT, SOURCE_ID, "SCR-001", authorize, api)).toBe("blob:shot-1");
    expect(api.shot.mock.calls).toEqual([
      [PROJECT, SOURCE_ID, "SCR-001", "token"],
      [PROJECT, SOURCE_ID, "SCR-002", "token"],
    ]);
    expect(urls.createObjectURL).toHaveBeenCalledTimes(2);
    expect(urls.createObjectURL.mock.calls[0]?.[0]).toBeInstanceOf(Blob);

    store.revokeShotUrls();
    expect(urls.revokeObjectURL.mock.calls).toEqual([["blob:shot-1"], ["blob:shot-2"]]);
    expect(await store.shotUrl(PROJECT, SOURCE_ID, "SCR-001", authorize, api)).toBe("blob:shot-3");

    store.reset();
    expect(urls.revokeObjectURL).toHaveBeenLastCalledWith("blob:shot-3");
  });

  it("drops a screenshot that arrives after its addresses were revoked", async () => {
    const urls = stubObjectUrls();
    const api = fakeApi();
    const arrival = deferred<Blob>();
    api.shot.mockImplementationOnce(() => arrival.promise);
    const store = useDesignCritiqueStore();

    const pending = store.shotUrl(PROJECT, SOURCE_ID, "SCR-001", authorize, api);
    store.revokeShotUrls();
    arrival.resolve(new Blob(["fake-png"], { type: "image/png" }));

    await expect(pending).rejects.toMatchObject({ code: CRITIQUE_SHOT_DISCARDED });
    expect(urls.revokeObjectURL).toHaveBeenCalledWith("blob:shot-1");
    expect(await store.shotUrl(PROJECT, SOURCE_ID, "SCR-001", authorize, api)).toBe("blob:shot-2");
  });
});
