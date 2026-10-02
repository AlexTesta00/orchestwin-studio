import { createPinia, setActivePinia } from "pinia";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { CodeChangesApiError, type CodeChangesApi } from "../api/codeChanges";
import type {
  AlignmentPayload,
  ChangeReviewListPayload,
  ChangeReviewRunPayload,
  CodeChangeListPayload,
  CodeChangePayload,
  CodeTaskPayload,
  CodeTaskStatus,
} from "../types/codeChanges";
import { type AuthorizedRequest, useCodeChangesStore } from "./codeChanges";

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

function change(commit: string, overrides: Partial<CodeChangePayload> = {}): CodeChangePayload {
  return {
    commit,
    parent: null,
    committed_at: "2026-09-29T08:00:00+00:00",
    author: "Alex",
    message: `Commit ${commit.slice(0, 7)}`,
    files: [],
    recorded_at: "2026-09-29T08:01:00+00:00",
    review: null,
    decision: null,
    ...overrides,
  };
}

const NEWEST = change("c".repeat(40), {
  review: {
    run_id: "33333333-3333-4333-8333-333333333333",
    reviewed_at: "2026-09-29T09:00:00+00:00",
    verdict: "CODE_DRIFT",
    summary: "The list lost its empty state.",
  },
  decision: { kind: "CODE_TASKS", decided_at: "2026-09-29T09:10:00+00:00", note: null },
});
const UNREVIEWED = change("b".repeat(40));
const ALIGNED = change("a".repeat(40), {
  review: {
    run_id: "44444444-4444-4444-8444-444444444444",
    reviewed_at: "2026-09-28T09:00:00+00:00",
    verdict: "ALIGNED",
    summary: "The code follows the design.",
  },
  decision: { kind: "ALIGNED", decided_at: "2026-09-28T09:10:00+00:00", note: null },
});
const OLDEST = change("9".repeat(40));

const ALIGNMENT: AlignmentPayload = {
  project_id: PROJECT_ID,
  reference: { requirements: null, design: null },
  aligned: {
    commit: ALIGNED.commit,
    decided_at: "2026-09-28T09:10:00+00:00",
    requirements_version_number: 2,
    design_version_number: 3,
  },
  pending_changes: 2,
  latest_change: NEWEST,
  tasks: [
    {
      code: "TSK-001",
      text: "Show the empty state of the guest list.",
      about: { requirements: ["REQ-003"], screens: ["SCR-002"] },
      from_commit: NEWEST.commit,
      created_at: "2026-09-29T09:10:00+00:00",
      status: "OPEN",
    },
  ],
  review_available: true,
};

function run(id: string, commit = NEWEST.commit): ChangeReviewRunPayload {
  return {
    id,
    commit,
    reviewed_at: "2026-09-29T09:00:00+00:00",
    locale: "en-US",
    reference: {
      requirements_version_number: 2,
      design_version_number: 3,
      alternative_code: "DES-001",
    },
    critiques: [],
    alignment: {
      status: "CODE_DRIFT",
      summary: "The list lost its empty state.",
      affected: { requirements: ["REQ-003"], screens: [] },
      design_request: null,
      requirements_request: null,
      code_tasks: ["Show the empty state again."],
    },
    cost_microusd: 650000,
  };
}

const authorize: AuthorizedRequest = async <T>(
  operation: (accessToken: string) => Promise<T>,
): Promise<T> => operation("test-token-not-real");

function list(...items: CodeChangePayload[]): CodeChangeListPayload {
  return { items };
}

function task(code: string, status: CodeTaskStatus): CodeTaskPayload {
  return {
    code,
    text: `Task ${code}`,
    about: { requirements: [], screens: [], criteria: [] },
    origin: {
      kind: "OWNER",
      commit: null,
      test_run_id: null,
      twin_id: null,
      twin_name: null,
      finding: null,
    },
    from_commit: null,
    created_at: "2026-09-29T09:20:00+00:00",
    status,
    closed_at: status === "OPEN" ? null : "2026-09-29T10:00:00+00:00",
    note: null,
  };
}

const EVERY_TASK: CodeTaskPayload[] = [
  ALIGNMENT.tasks[0]!,
  task("TSK-002", "DONE"),
  task("TSK-003", "DROPPED"),
  task("TSK-004", "DONE"),
];

function fakeApi(overrides: Partial<CodeChangesApi> = {}): CodeChangesApi {
  return {
    alignment: async () => ALIGNMENT,
    changes: async () => list(NEWEST, UNREVIEWED, ALIGNED, OLDEST),
    reviews: async () => ({ items: [run("newest-run"), run("older-run")] }),
    tasks: async () => ({ items: EVERY_TASK }),
    ...overrides,
  };
}

function failure(status: number, code: string): CodeChangesApiError {
  return new CodeChangesApiError("The code change request failed", {
    status,
    code,
    payload: null,
  });
}

describe("Code Changes store", () => {
  beforeEach(() => {
    setActivePinia(createPinia());
  });

  it("loads the alignment, every recorded change and every task of the project", async () => {
    const alignment = vi.fn<CodeChangesApi["alignment"]>(async () => ALIGNMENT);
    const changes = vi.fn<CodeChangesApi["changes"]>(async () =>
      list(NEWEST, UNREVIEWED, ALIGNED, OLDEST),
    );
    const tasks = vi.fn<CodeChangesApi["tasks"]>(async () => ({ items: EVERY_TASK }));
    const store = useCodeChangesStore();

    const snapshot = await store.load(
      PROJECT_ID,
      authorize,
      fakeApi({ alignment, changes, tasks }),
    );

    expect(alignment).toHaveBeenCalledWith(PROJECT_ID, "test-token-not-real");
    expect(changes).toHaveBeenCalledWith(PROJECT_ID, "test-token-not-real");
    expect(tasks).toHaveBeenCalledWith(PROJECT_ID, "test-token-not-real", "all");
    expect(snapshot).toEqual({
      alignment: ALIGNMENT,
      changes: [NEWEST, UNREVIEWED, ALIGNED, OLDEST],
      tasks: EVERY_TASK,
    });
    expect(store.projectId).toBe(PROJECT_ID);
    expect(store.alignment).toEqual(ALIGNMENT);
    expect(store.changes).toEqual([NEWEST, UNREVIEWED, ALIGNED, OLDEST]);
    expect(store.tasks).toEqual(EVERY_TASK);
    expect(store.pendingChanges).toEqual([NEWEST, UNREVIEWED]);
    expect(store.openTasks.map((item) => item.code)).toEqual(["TSK-001"]);
    expect(store.closedTasks).toEqual({ done: 2, dropped: 1 });
    expect(store.staleReviews).toBe(0);
    expect(store.latestReviewed).toEqual(NEWEST);
    expect(store.latestRun).toBeNull();
    expect(store.error).toBeNull();
    expect(store.isBusy).toBe(false);
  });

  it("gives the number of stale reviews that the Studio counts", async () => {
    const store = useCodeChangesStore();

    await store.load(
      PROJECT_ID,
      authorize,
      fakeApi({ alignment: async () => ({ ...ALIGNMENT, stale_reviews: 2 }) }),
    );

    expect(store.staleReviews).toBe(2);
  });

  it.each([
    ["a Studio without the list of the tasks", failure(404, "UNKNOWN")],
    ["a failed read of the tasks", new TypeError("Failed to fetch")],
  ])("loads the rest of the state with %s and counts no closed task", async (_case, refusal) => {
    const store = useCodeChangesStore();

    const snapshot = await store.load(
      PROJECT_ID,
      authorize,
      fakeApi({
        tasks: async () => {
          throw refusal;
        },
      }),
    );

    expect(snapshot.tasks).toBeNull();
    expect(store.tasks).toBeNull();
    expect(store.closedTasks).toBeNull();
    expect(store.alignment).toEqual(ALIGNMENT);
    expect(store.openTasks.map((item) => item.code)).toEqual(["TSK-001"]);
    expect(store.error).toBeNull();
  });

  it("counts no closed task when every task is open", async () => {
    const store = useCodeChangesStore();

    await store.load(
      PROJECT_ID,
      authorize,
      fakeApi({ tasks: async () => ({ items: [task("TSK-009", "OPEN")] }) }),
    );

    expect(store.closedTasks).toEqual({ done: 0, dropped: 0 });
  });

  it("counts every change as pending while no commit is aligned", async () => {
    const store = useCodeChangesStore();

    await store.load(
      PROJECT_ID,
      authorize,
      fakeApi({
        alignment: async () => ({ ...ALIGNMENT, aligned: null, pending_changes: 2 }),
        changes: async () => list(UNREVIEWED, OLDEST),
      }),
    );

    expect(store.pendingChanges).toEqual([UNREVIEWED, OLDEST]);
    expect(store.latestReviewed).toBeNull();
  });

  it("keeps only the open tasks of the alignment", async () => {
    const store = useCodeChangesStore();
    const done = { ...ALIGNMENT.tasks[0]!, code: "TSK-000", status: "DONE" as const };

    await store.load(
      PROJECT_ID,
      authorize,
      fakeApi({ alignment: async () => ({ ...ALIGNMENT, tasks: [done, ...ALIGNMENT.tasks] }) }),
    );

    expect(store.openTasks.map((item) => item.code)).toEqual(["TSK-001"]);
  });

  it("reads the latest run of the newest reviewed commit", async () => {
    const reviews = vi.fn<CodeChangesApi["reviews"]>(async () => ({
      items: [run("newest-run"), run("older-run")],
    }));
    const api = fakeApi({ reviews });
    const store = useCodeChangesStore();
    await store.load(PROJECT_ID, authorize, api);

    const latest = await store.loadRun(PROJECT_ID, NEWEST.commit, authorize, api);

    expect(reviews).toHaveBeenCalledWith(PROJECT_ID, NEWEST.commit, "test-token-not-real");
    expect(latest?.id).toBe("newest-run");
    expect(store.runs[NEWEST.commit]?.id).toBe("newest-run");
    expect(store.latestRun?.id).toBe("newest-run");
    expect(store.pending.run).toBe(false);
  });

  it("remembers that a commit has no run when the Studio lists none", async () => {
    const api = fakeApi({ reviews: async () => ({ items: [] }) });
    const store = useCodeChangesStore();
    await store.load(PROJECT_ID, authorize, api);

    await expect(store.loadRun(PROJECT_ID, NEWEST.commit, authorize, api)).resolves.toBeNull();

    expect(NEWEST.commit in store.runs).toBe(true);
    expect(store.latestRun).toBeNull();
  });

  it("captures and rethrows a failed read of the state and of a run", async () => {
    const missing = failure(404, "PROJECT_NOT_FOUND");
    const ambiguous = failure(409, "CODE_CHANGE_AMBIGUOUS");
    const offline = new TypeError("Failed to fetch");
    const store = useCodeChangesStore();

    await expect(
      store.load(
        PROJECT_ID,
        authorize,
        fakeApi({
          alignment: async () => {
            throw missing;
          },
        }),
      ),
    ).rejects.toBe(missing);

    expect(store.error).toEqual({
      message: "The code change request failed",
      code: "PROJECT_NOT_FOUND",
      status: 404,
    });
    expect(store.alignment).toBeNull();
    expect(store.pending.load).toBe(false);

    await expect(
      store.loadRun(
        PROJECT_ID,
        "4f2a9c1",
        authorize,
        fakeApi({
          reviews: async () => {
            throw ambiguous;
          },
        }),
      ),
    ).rejects.toBe(ambiguous);

    expect(store.error).toEqual({
      message: "The code change request failed",
      code: "CODE_CHANGE_AMBIGUOUS",
      status: 409,
    });
    expect(store.pending.run).toBe(false);

    await expect(
      store.load(
        PROJECT_ID,
        authorize,
        fakeApi({
          changes: async () => {
            throw offline;
          },
        }),
      ),
    ).rejects.toBe(offline);

    expect(store.error).toEqual({ message: "Failed to fetch", code: null, status: null });
  });

  it("tracks the flag of each operation while it is in flight", async () => {
    const pendingAlignment = deferred<AlignmentPayload>();
    const pendingReviews = deferred<ChangeReviewListPayload>();
    const api = fakeApi({
      alignment: async () => pendingAlignment.promise,
      reviews: async () => pendingReviews.promise,
    });
    const store = useCodeChangesStore();

    const load = store.load(PROJECT_ID, authorize, api);

    expect(store.pending).toEqual({ load: true, run: false });
    expect(store.isBusy).toBe(true);

    pendingAlignment.resolve(ALIGNMENT);
    await load;
    const reading = store.loadRun(PROJECT_ID, NEWEST.commit, authorize, api);

    expect(store.pending).toEqual({ load: false, run: true });

    pendingReviews.resolve({ items: [run("newest-run")] });
    await reading;

    expect(store.pending).toEqual({ load: false, run: false });
    expect(store.isBusy).toBe(false);
  });

  it("keeps the answer of the newest load when an older one ends later", async () => {
    const older = deferred<CodeChangeListPayload>();
    let calls = 0;
    const api = fakeApi({
      changes: async () => {
        calls += 1;
        return calls === 1 ? older.promise : list(NEWEST);
      },
    });
    const store = useCodeChangesStore();

    const first = store.load(PROJECT_ID, authorize, api);
    await store.load(PROJECT_ID, authorize, api);
    older.resolve(list(NEWEST, UNREVIEWED, ALIGNED, OLDEST));
    await first;

    expect(store.changes).toEqual([NEWEST]);
    expect(store.pending.load).toBe(false);
  });

  it("ignores the answers of a previous project", async () => {
    const pendingChanges = deferred<CodeChangeListPayload>();
    const pendingReviews = deferred<ChangeReviewListPayload>();
    const api = fakeApi({
      changes: async () => pendingChanges.promise,
      reviews: async () => pendingReviews.promise,
    });
    const store = useCodeChangesStore();
    const missing = failure(404, "CODE_CHANGE_NOT_FOUND");

    const load = store.load(PROJECT_ID, authorize, api);
    const readingRejected = expect(
      store.loadRun(PROJECT_ID, NEWEST.commit, authorize, api),
    ).rejects.toBe(missing);
    store.activateProject(SECOND_PROJECT_ID);
    pendingChanges.resolve(list(NEWEST));
    pendingReviews.reject(missing);
    await load;
    await readingRejected;

    expect(store.projectId).toBe(SECOND_PROJECT_ID);
    expect(store.alignment).toBeNull();
    expect(store.changes).toEqual([]);
    expect(store.tasks).toBeNull();
    expect(store.runs).toEqual({});
    expect(store.error).toBeNull();
    expect(store.isBusy).toBe(false);
  });
});
