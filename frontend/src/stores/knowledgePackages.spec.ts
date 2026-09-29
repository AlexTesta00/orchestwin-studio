import { createPinia, setActivePinia } from "pinia";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { KnowledgePackagesApiError, type KnowledgePackagesApi } from "../api/knowledgePackages";
import type {
  KnowledgePackageDownload,
  KnowledgePackageHistoryPayload,
  KnowledgePackagePublicationPayload,
  KnowledgePackageVersionPayload,
} from "../types/knowledgePackages";
import { type AuthorizedRequest, useKnowledgePackagesStore } from "./knowledgePackages";

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

function packageVersion(versionNumber: number): KnowledgePackageVersionPayload {
  return {
    id: `00000000-0000-4000-8000-00000000000${versionNumber}`,
    project_id: PROJECT_ID,
    project_name: "Reception desk",
    version_number: versionNumber,
    schema_version: 1,
    content_hash: String(versionNumber).repeat(64),
    archive_hash: "f".repeat(64),
    file_name: `orchestwin-${PROJECT_ID}-knowledge-v${versionNumber}.zip`,
    file_count: 12,
    archive_size: 20480,
    created_at: `2026-09-2${versionNumber}T09:00:00Z`,
    stages: [],
    twins: [],
    feedback: {
      reviews: 0,
      findings: 0,
      decisions: 0,
      discussions: 0,
      insights: 0,
    },
    diagram_count: 6,
    table_count: 4,
    entries: ["README.md", "manifest.json"],
  };
}

const FIRST = packageVersion(1);
const SECOND = packageVersion(2);
const THIRD = packageVersion(3);

const DOWNLOAD: KnowledgePackageDownload = {
  blob: new Blob(["PK"], { type: "application/zip" }),
  fileName: `orchestwin-${PROJECT_ID}-knowledge-v2.zip`,
  archiveHash: "f".repeat(64),
};

const authorize: AuthorizedRequest = async <T>(
  operation: (accessToken: string) => Promise<T>,
): Promise<T> => operation("access-token");

function history(...versions: KnowledgePackageVersionPayload[]): KnowledgePackageHistoryPayload {
  return { project_id: PROJECT_ID, versions };
}

function fakeApi(overrides: Partial<KnowledgePackagesApi> = {}): KnowledgePackagesApi {
  return {
    publish: async () => ({ reused: false, version: THIRD }),
    history: async () => history(SECOND, FIRST),
    download: async () => DOWNLOAD,
    ...overrides,
  };
}

function failure(status: number, code: string): KnowledgePackagesApiError {
  return new KnowledgePackagesApiError("The knowledge package request failed", {
    status,
    code,
    payload: null,
  });
}

describe("Knowledge Packages store", () => {
  beforeEach(() => {
    setActivePinia(createPinia());
  });

  it("loads the published versions newest first", async () => {
    const historyCall = vi.fn<KnowledgePackagesApi["history"]>(async () => history(SECOND, FIRST));
    const store = useKnowledgePackagesStore();

    expect(store.latest).toBeNull();

    const versions = await store.load(PROJECT_ID, authorize, fakeApi({ history: historyCall }));

    expect(historyCall).toHaveBeenCalledWith(PROJECT_ID, "access-token");
    expect(versions).toEqual([SECOND, FIRST]);
    expect(store.projectId).toBe(PROJECT_ID);
    expect(store.versions).toEqual([SECOND, FIRST]);
    expect(store.latest).toEqual(SECOND);
    expect(store.error).toBeNull();
    expect(store.isBusy).toBe(false);
  });

  it("treats an unknown project as an empty history", async () => {
    const store = useKnowledgePackagesStore();

    const versions = await store.load(
      PROJECT_ID,
      authorize,
      fakeApi({
        history: async () => {
          throw failure(404, "PROJECT_NOT_FOUND");
        },
      }),
    );

    expect(versions).toEqual([]);
    expect(store.versions).toEqual([]);
    expect(store.latest).toBeNull();
    expect(store.error).toBeNull();
    expect(store.pending.load).toBe(false);
  });

  it("captures and rethrows a failed history read", async () => {
    const store = useKnowledgePackagesStore();
    const unavailable = failure(503, "KNOWLEDGE_PACKAGE_SERVICE_UNAVAILABLE");
    const offline = new TypeError("Failed to fetch");

    await expect(
      store.load(
        PROJECT_ID,
        authorize,
        fakeApi({
          history: async () => {
            throw unavailable;
          },
        }),
      ),
    ).rejects.toBe(unavailable);

    expect(store.error).toEqual({
      message: "The knowledge package request failed",
      code: "KNOWLEDGE_PACKAGE_SERVICE_UNAVAILABLE",
      status: 503,
    });
    expect(store.pending.load).toBe(false);

    await expect(
      store.load(
        PROJECT_ID,
        authorize,
        fakeApi({
          history: async () => {
            throw offline;
          },
        }),
      ),
    ).rejects.toBe(offline);

    expect(store.error).toEqual({ message: "Failed to fetch", code: null, status: null });
  });

  it("publishes a new version on top of the history", async () => {
    const publish = vi.fn<KnowledgePackagesApi["publish"]>(async () => ({
      reused: false,
      version: THIRD,
    }));
    const api = fakeApi({ publish });
    const store = useKnowledgePackagesStore();
    await store.load(PROJECT_ID, authorize, api);

    const publication = await store.publish(PROJECT_ID, authorize, api);

    expect(publish).toHaveBeenCalledWith(PROJECT_ID, "access-token");
    expect(publication).toEqual({ reused: false, version: THIRD });
    expect(store.lastPublication).toEqual(publication);
    expect(store.versions.map((item) => item.version_number)).toEqual([3, 2, 1]);
    expect(store.latest).toEqual(THIRD);
    expect(store.pending.publish).toBe(false);
  });

  it("puts a version that is already listed on top without duplicating it", async () => {
    const reusedSecond = { ...SECOND, file_count: 13 };
    const store = useKnowledgePackagesStore();
    await store.load(PROJECT_ID, authorize, fakeApi());

    await store.publish(
      PROJECT_ID,
      authorize,
      fakeApi({ publish: async () => ({ reused: true, version: reusedSecond }) }),
    );

    expect(store.versions).toEqual([reusedSecond, FIRST]);
    expect(store.lastPublication?.reused).toBe(true);

    await store.publish(
      PROJECT_ID,
      authorize,
      fakeApi({ publish: async () => ({ reused: true, version: FIRST }) }),
    );

    expect(store.versions).toEqual([FIRST, reusedSecond]);
  });

  it("keeps a publication that completes while an older history read is in flight", async () => {
    const pendingHistory = deferred<KnowledgePackageHistoryPayload>();
    const api = fakeApi({ history: async () => pendingHistory.promise });
    const store = useKnowledgePackagesStore();

    const load = store.load(PROJECT_ID, authorize, api);
    await store.publish(PROJECT_ID, authorize, api);
    pendingHistory.resolve(history(SECOND, FIRST));
    await load;

    expect(store.versions.map((item) => item.version_number)).toEqual([3, 2, 1]);
    expect(store.latest).toEqual(THIRD);
  });

  it("returns the archive of a version without storing it", async () => {
    const download = vi.fn<KnowledgePackagesApi["download"]>(async () => DOWNLOAD);
    const store = useKnowledgePackagesStore();

    const result = await store.download(PROJECT_ID, 2, authorize, fakeApi({ download }));

    expect(download).toHaveBeenCalledWith(PROJECT_ID, 2, "access-token");
    expect(result).toBe(DOWNLOAD);
    expect(store.versions).toEqual([]);
    expect(store.pending.download).toBe(false);
  });

  it("tracks the flag of each operation while it is in flight", async () => {
    const pendingHistory = deferred<KnowledgePackageHistoryPayload>();
    const pendingPublication = deferred<KnowledgePackagePublicationPayload>();
    const pendingDownload = deferred<KnowledgePackageDownload>();
    const api = fakeApi({
      history: async () => pendingHistory.promise,
      publish: async () => pendingPublication.promise,
      download: async () => pendingDownload.promise,
    });
    const store = useKnowledgePackagesStore();

    const load = store.load(PROJECT_ID, authorize, api);

    expect(store.pending).toEqual({ load: true, publish: false, download: false });
    expect(store.isBusy).toBe(true);

    pendingHistory.resolve(history(SECOND, FIRST));
    await load;
    const publish = store.publish(PROJECT_ID, authorize, api);
    const download = store.download(PROJECT_ID, 2, authorize, api);

    expect(store.pending).toEqual({ load: false, publish: true, download: true });

    pendingPublication.resolve({ reused: false, version: THIRD });
    await publish;

    expect(store.pending).toEqual({ load: false, publish: false, download: true });
    expect(store.isBusy).toBe(true);

    pendingDownload.resolve(DOWNLOAD);
    await download;

    expect(store.pending).toEqual({ load: false, publish: false, download: false });
    expect(store.isBusy).toBe(false);
  });

  it("captures and rethrows a blocked publication and a missing archive", async () => {
    const blocked = failure(409, "DESIGN_APPROVAL_REQUIRED");
    const missing = failure(404, "KNOWLEDGE_PACKAGE_NOT_FOUND");
    const api = fakeApi({
      publish: async () => {
        throw blocked;
      },
      download: async () => {
        throw missing;
      },
    });
    const store = useKnowledgePackagesStore();
    await store.load(PROJECT_ID, authorize, api);

    await expect(store.publish(PROJECT_ID, authorize, api)).rejects.toBe(blocked);

    expect(store.error).toEqual({
      message: "The knowledge package request failed",
      code: "DESIGN_APPROVAL_REQUIRED",
      status: 409,
    });
    expect(store.lastPublication).toBeNull();
    expect(store.versions).toEqual([SECOND, FIRST]);
    expect(store.pending.publish).toBe(false);

    await expect(store.download(PROJECT_ID, 9, authorize, api)).rejects.toBe(missing);

    expect(store.error).toEqual({
      message: "The knowledge package request failed",
      code: "KNOWLEDGE_PACKAGE_NOT_FOUND",
      status: 404,
    });
    expect(store.pending.download).toBe(false);
  });

  it("ignores the responses of a previous project", async () => {
    const pendingHistory = deferred<KnowledgePackageHistoryPayload>();
    const pendingPublication = deferred<KnowledgePackagePublicationPayload>();
    const pendingDownload = deferred<KnowledgePackageDownload>();
    const api = fakeApi({
      history: async () => pendingHistory.promise,
      publish: async () => pendingPublication.promise,
      download: async () => pendingDownload.promise,
    });
    const store = useKnowledgePackagesStore();
    const missing = failure(404, "KNOWLEDGE_PACKAGE_NOT_FOUND");

    const load = store.load(PROJECT_ID, authorize, api);
    const publish = store.publish(PROJECT_ID, authorize, api);
    const downloadRejected = expect(store.download(PROJECT_ID, 2, authorize, api)).rejects.toBe(
      missing,
    );
    store.activateProject(SECOND_PROJECT_ID);
    pendingHistory.resolve(history(SECOND, FIRST));
    pendingPublication.resolve({ reused: false, version: THIRD });
    pendingDownload.reject(missing);
    await load;
    await publish;
    await downloadRejected;

    expect(store.projectId).toBe(SECOND_PROJECT_ID);
    expect(store.versions).toEqual([]);
    expect(store.lastPublication).toBeNull();
    expect(store.error).toBeNull();
    expect(store.isBusy).toBe(false);
  });
});
