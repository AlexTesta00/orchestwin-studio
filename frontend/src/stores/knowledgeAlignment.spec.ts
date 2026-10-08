import { createPinia, setActivePinia } from "pinia";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { KnowledgeAlignmentApiError, type KnowledgeAlignmentApi } from "../api/knowledgeAlignment";
import {
  ALIGNMENT_PROJECT_ID as PROJECT_ID,
  applyAnswer,
  DESIGN_PROPOSAL,
  designChangeResult,
  LATEST_RUN,
  proposalList,
  REQUIREMENTS_PROPOSAL,
  requirementsRevision,
  RUN_SUMMARY,
  SECOND_REQUIREMENTS_PROPOSAL,
  skippedProposal,
  TESTS_PROPOSAL,
} from "../test/knowledgeAlignmentFixtures";
import type {
  AlignmentProposalListPayload,
  AlignmentProposalPayload,
  ProposalApplyPayload,
  ProposalSkipPayload,
} from "../types/knowledgeAlignment";
import {
  revisionDiffId,
  useKnowledgeAlignmentStore,
  type AuthorizedRequest,
} from "./knowledgeAlignment";

const SECOND_PROJECT_ID = "22222222-2222-4222-8222-222222222222";
const TOKEN = "test-token-not-real";
const DIFF_ID = "dddddddd-dddd-4ddd-8ddd-dddddddddddd";

const EVERY_PROPOSAL = [
  REQUIREMENTS_PROPOSAL,
  DESIGN_PROPOSAL,
  TESTS_PROPOSAL,
  SECOND_REQUIREMENTS_PROPOSAL,
];

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

const authorize: AuthorizedRequest = async <T>(
  operation: (accessToken: string) => Promise<T>,
): Promise<T> => operation(TOKEN);

function byCode(code: string): AlignmentProposalPayload {
  const found = EVERY_PROPOSAL.find((proposal) => proposal.code === code);

  if (found === undefined) {
    throw new Error(`Unknown proposal ${code}`);
  }

  return found;
}

function fakeApi(overrides: Partial<KnowledgeAlignmentApi> = {}): KnowledgeAlignmentApi {
  return {
    proposals: async () => proposalList(EVERY_PROPOSAL),
    apply: async (_project, code, text) =>
      applyAnswer(byCode(code), text, byCode(code).section === "TESTS" ? null : DIFF_ID),
    skip: async (_project, code, reason) => ({ proposal: skippedProposal(byCode(code), reason) }),
    runs: async () => ({ items: [RUN_SUMMARY] }),
    ...overrides,
  };
}

function failure(status: number, code: string): KnowledgeAlignmentApiError {
  return new KnowledgeAlignmentApiError(code, { status, code, payload: null });
}

describe("Knowledge Alignment store", () => {
  beforeEach(() => {
    setActivePinia(createPinia());
  });

  it("loads the waiting proposals and the latest run of the project", async () => {
    const proposals = vi.fn<KnowledgeAlignmentApi["proposals"]>(async () =>
      proposalList(EVERY_PROPOSAL),
    );
    const store = useKnowledgeAlignmentStore();

    const items = await store.load(PROJECT_ID, authorize, fakeApi({ proposals }));

    expect(proposals).toHaveBeenCalledWith(PROJECT_ID, "waiting", TOKEN);
    expect(items).toEqual(EVERY_PROPOSAL);
    expect(store.projectId).toBe(PROJECT_ID);
    expect(store.proposals).toEqual(EVERY_PROPOSAL);
    expect(store.latestRun).toEqual(LATEST_RUN);
    expect(store.waiting.map((proposal) => proposal.code)).toEqual([
      "ALN-001",
      "ALN-002",
      "ALN-003",
      "ALN-004",
    ]);
    expect(store.bySection("REQUIREMENTS").map((proposal) => proposal.code)).toEqual([
      "ALN-001",
      "ALN-004",
    ]);
    expect(store.bySection("DESIGN")).toEqual([DESIGN_PROPOSAL]);
    expect(store.bySection("TESTS")).toEqual([TESTS_PROPOSAL]);
    expect(store.runs).toBeNull();
    expect(store.error).toBeNull();
    expect(store.isBusy).toBe(false);
  });

  it("takes no latest run from a Studio that lists none", async () => {
    const store = useKnowledgeAlignmentStore();

    await store.load(
      PROJECT_ID,
      authorize,
      fakeApi({
        proposals: async () => ({ items: [] }) as unknown as AlignmentProposalListPayload,
      }),
    );

    expect(store.proposals).toEqual([]);
    expect(store.latestRun).toBeNull();
    expect(store.bySection("REQUIREMENTS")).toEqual([]);
  });

  it("applies a proposal of the requirements and gives the id of the diff it created", async () => {
    const apply = vi.fn<KnowledgeAlignmentApi["apply"]>(async (_project, code, text) =>
      applyAnswer(byCode(code), text, DIFF_ID),
    );
    const api = fakeApi({ apply });
    const store = useKnowledgeAlignmentStore();
    await store.load(PROJECT_ID, authorize, api);

    const diffId = await store.apply(PROJECT_ID, "ALN-001", null, authorize, api);

    expect(apply).toHaveBeenCalledWith(PROJECT_ID, "ALN-001", null, TOKEN);
    expect(diffId).toBe(DIFF_ID);
    const applied = store.proposals.find((proposal) => proposal.code === "ALN-001");
    expect(applied?.status).toBe("APPLIED");
    expect(applied?.applied_diff_id).toBe(DIFF_ID);
    expect(applied?.applied_text).toBe(REQUIREMENTS_PROPOSAL.request);
    expect(store.waiting.map((proposal) => proposal.code)).toEqual([
      "ALN-002",
      "ALN-003",
      "ALN-004",
    ]);
    expect(store.bySection("REQUIREMENTS").map((proposal) => proposal.status)).toEqual([
      "APPLIED",
      "PROPOSED",
    ]);
    expect(store.decisionOf("ALN-001")).toBeNull();
    expect(store.pending.apply).toBe(false);
    expect(store.error).toBeNull();
  });

  it("sends the text edited by the owner and reads the diff of a change to the design", async () => {
    const apply = vi.fn<KnowledgeAlignmentApi["apply"]>(async (_project, code, text) =>
      applyAnswer(byCode(code), text, DIFF_ID),
    );
    const api = fakeApi({ apply });
    const store = useKnowledgeAlignmentStore();
    await store.load(PROJECT_ID, authorize, api);

    const diffId = await store.apply(PROJECT_ID, "ALN-002", "Edited text.", authorize, api);

    expect(apply).toHaveBeenCalledWith(PROJECT_ID, "ALN-002", "Edited text.", TOKEN);
    expect(diffId).toBe(DIFF_ID);
    expect(store.bySection("DESIGN")[0]?.applied_text).toBe("Edited text.");
  });

  it("applies a proposal of the tests without a revision and gives no diff", async () => {
    const api = fakeApi();
    const store = useKnowledgeAlignmentStore();
    await store.load(PROJECT_ID, authorize, api);

    await expect(store.apply(PROJECT_ID, "ALN-003", null, authorize, api)).resolves.toBeNull();

    expect(store.bySection("TESTS")[0]?.status).toBe("APPLIED");
    expect(store.bySection("TESTS")[0]?.applied_diff_id).toBeNull();
  });

  it("adds a proposal that the Studio answers with and that the store did not know", async () => {
    const api = fakeApi({ proposals: async () => proposalList([DESIGN_PROPOSAL]) });
    const store = useKnowledgeAlignmentStore();
    await store.load(PROJECT_ID, authorize, api);

    await store.skip(PROJECT_ID, "ALN-004", null, authorize, api);

    expect(store.proposals.map((proposal) => [proposal.code, proposal.status])).toEqual([
      ["ALN-002", "PROPOSED"],
      ["ALN-004", "SKIPPED"],
    ]);
  });

  it("keeps a refused proposal waiting and captures the refusal", async () => {
    const refusal = failure(409, "REQUIREMENTS_REVISION_PENDING");
    const api = fakeApi({
      apply: async () => {
        throw refusal;
      },
    });
    const store = useKnowledgeAlignmentStore();
    await store.load(PROJECT_ID, authorize, api);

    await expect(store.apply(PROJECT_ID, "ALN-001", null, authorize, api)).rejects.toBe(refusal);

    expect(store.error).toEqual({
      message: "REQUIREMENTS_REVISION_PENDING",
      code: "REQUIREMENTS_REVISION_PENDING",
      status: 409,
    });
    expect(store.bySection("REQUIREMENTS")[0]?.status).toBe("PROPOSED");
    expect(store.decisionOf("ALN-001")).toBeNull();
    expect(store.pending.apply).toBe(false);
    expect(store.isBusy).toBe(false);
  });

  it("skips a proposal with the reason of the owner", async () => {
    const skip = vi.fn<KnowledgeAlignmentApi["skip"]>(async (_project, code, reason) => ({
      proposal: skippedProposal(byCode(code), reason),
    }));
    const api = fakeApi({ skip });
    const store = useKnowledgeAlignmentStore();
    await store.load(PROJECT_ID, authorize, api);

    const skipped = await store.skip(PROJECT_ID, "ALN-002", "Already there.", authorize, api);

    expect(skip).toHaveBeenCalledWith(PROJECT_ID, "ALN-002", "Already there.", TOKEN);
    expect(skipped.status).toBe("SKIPPED");
    expect(skipped.decision_note).toBe("Already there.");
    expect(store.bySection("DESIGN")).toEqual([skipped]);
    expect(store.waiting.map((proposal) => proposal.code)).toEqual([
      "ALN-001",
      "ALN-003",
      "ALN-004",
    ]);
    expect(store.pending.skip).toBe(false);
  });

  it("captures and rethrows a failed skip and a failed load", async () => {
    const decided = failure(409, "ALIGNMENT_PROPOSAL_DECIDED");
    const offline = new TypeError("Failed to fetch");
    const store = useKnowledgeAlignmentStore();
    await store.load(PROJECT_ID, authorize, fakeApi());

    await expect(
      store.skip(
        PROJECT_ID,
        "ALN-001",
        null,
        authorize,
        fakeApi({
          skip: async () => {
            throw decided;
          },
        }),
      ),
    ).rejects.toBe(decided);

    expect(store.error).toEqual({
      message: "ALIGNMENT_PROPOSAL_DECIDED",
      code: "ALIGNMENT_PROPOSAL_DECIDED",
      status: 409,
    });
    expect(store.pending.skip).toBe(false);

    await expect(
      store.reload(
        PROJECT_ID,
        authorize,
        fakeApi({
          proposals: async () => {
            throw offline;
          },
        }),
      ),
    ).rejects.toBe(offline);

    expect(store.error).toEqual({ message: "Failed to fetch", code: null, status: null });
    expect(store.proposals).toEqual(EVERY_PROPOSAL);
    expect(store.pending.load).toBe(false);
  });

  it("reads the runs of the project with their counts", async () => {
    const runs = vi.fn<KnowledgeAlignmentApi["runs"]>(async () => ({ items: [RUN_SUMMARY] }));
    const store = useKnowledgeAlignmentStore();

    const items = await store.loadRuns(PROJECT_ID, authorize, fakeApi({ runs }));

    expect(runs).toHaveBeenCalledWith(PROJECT_ID, TOKEN);
    expect(items).toEqual([RUN_SUMMARY]);
    expect(store.runs).toEqual([RUN_SUMMARY]);
    expect(store.runs?.[0]?.waiting).toBe(3);
    expect(store.pending.runs).toBe(false);
  });

  it("tracks the decision of each proposal while it is in flight", async () => {
    const pendingApply = deferred<ProposalApplyPayload>();
    const secondApply = deferred<ProposalApplyPayload>();
    const pendingSkip = deferred<ProposalSkipPayload>();
    let applies = 0;
    const api = fakeApi({
      apply: async () => {
        applies += 1;
        return applies === 1 ? pendingApply.promise : secondApply.promise;
      },
      skip: async () => pendingSkip.promise,
    });
    const store = useKnowledgeAlignmentStore();
    await store.load(PROJECT_ID, authorize, api);

    const first = store.apply(PROJECT_ID, "ALN-001", null, authorize, api);
    const second = store.apply(PROJECT_ID, "ALN-004", null, authorize, api);
    const skipping = store.skip(PROJECT_ID, "ALN-002", null, authorize, api);

    expect(store.decisionOf("ALN-001")).toBe("apply");
    expect(store.decisionOf("ALN-004")).toBe("apply");
    expect(store.decisionOf("ALN-002")).toBe("skip");
    expect(store.decisionOf("ALN-003")).toBeNull();
    expect(store.pending).toEqual({ load: false, runs: false, apply: true, skip: true });
    expect(store.isBusy).toBe(true);

    pendingSkip.resolve({ proposal: skippedProposal(DESIGN_PROPOSAL, null) });
    await skipping;

    expect(store.decisionOf("ALN-002")).toBeNull();
    expect(store.pending).toEqual({ load: false, runs: false, apply: true, skip: false });

    pendingApply.resolve(applyAnswer(REQUIREMENTS_PROPOSAL, null, DIFF_ID));
    await first;

    expect(store.decisionOf("ALN-001")).toBeNull();
    expect(store.decisionOf("ALN-004")).toBe("apply");
    expect(store.pending.apply).toBe(true);

    secondApply.resolve(applyAnswer(SECOND_REQUIREMENTS_PROPOSAL, null, DIFF_ID));
    await second;

    expect(store.pending).toEqual({ load: false, runs: false, apply: false, skip: false });
    expect(store.isBusy).toBe(false);
    expect(store.waiting.map((proposal) => proposal.code)).toEqual(["ALN-003"]);
  });

  it("shares one request between concurrent loads, answers later loads from what it holds and reads again only on reload", async () => {
    const pendingList = deferred<AlignmentProposalListPayload>();
    const proposals = vi.fn<KnowledgeAlignmentApi["proposals"]>(async () => pendingList.promise);
    const api = fakeApi({ proposals });
    const store = useKnowledgeAlignmentStore();

    const loads = [
      store.load(PROJECT_ID, authorize, api),
      store.load(PROJECT_ID, authorize, api),
      store.load(PROJECT_ID, authorize, api),
    ];

    expect(proposals).toHaveBeenCalledTimes(1);
    expect(proposals).toHaveBeenCalledWith(PROJECT_ID, "waiting", TOKEN);
    expect(store.pending.load).toBe(true);

    pendingList.resolve(proposalList(EVERY_PROPOSAL));
    const answers = await Promise.all(loads);

    expect(answers).toEqual([EVERY_PROPOSAL, EVERY_PROPOSAL, EVERY_PROPOSAL]);
    expect(store.proposals).toEqual(EVERY_PROPOSAL);
    expect(store.latestRun).toEqual(LATEST_RUN);
    expect(store.pending.load).toBe(false);

    await expect(store.load(PROJECT_ID, authorize, api)).resolves.toEqual(EVERY_PROPOSAL);

    expect(proposals).toHaveBeenCalledTimes(1);
    expect(store.pending.load).toBe(false);

    proposals.mockResolvedValueOnce(proposalList([TESTS_PROPOSAL]));
    await expect(store.reload(PROJECT_ID, authorize, api)).resolves.toEqual([TESTS_PROPOSAL]);

    expect(proposals).toHaveBeenCalledTimes(2);
    expect(store.proposals).toEqual([TESTS_PROPOSAL]);

    await expect(store.load(PROJECT_ID, authorize, api)).resolves.toEqual([TESTS_PROPOSAL]);

    expect(proposals).toHaveBeenCalledTimes(2);
  });

  it("reads again for a new project or through another client", async () => {
    const proposals = vi.fn<KnowledgeAlignmentApi["proposals"]>(async (project) =>
      proposalList(project === PROJECT_ID ? EVERY_PROPOSAL : [TESTS_PROPOSAL]),
    );
    const api = fakeApi({ proposals });
    const otherClient = fakeApi({ proposals });
    const store = useKnowledgeAlignmentStore();

    await store.load(PROJECT_ID, authorize, api);
    await store.load(PROJECT_ID, authorize, api);
    expect(proposals).toHaveBeenCalledTimes(1);

    await expect(store.load(PROJECT_ID, authorize, otherClient)).resolves.toEqual(EVERY_PROPOSAL);
    expect(proposals).toHaveBeenCalledTimes(2);

    await expect(store.load(SECOND_PROJECT_ID, authorize, api)).resolves.toEqual([TESTS_PROPOSAL]);
    expect(proposals).toHaveBeenCalledTimes(3);
    expect(proposals).toHaveBeenLastCalledWith(SECOND_PROJECT_ID, "waiting", TOKEN);
    expect(store.projectId).toBe(SECOND_PROJECT_ID);
    expect(store.proposals).toEqual([TESTS_PROPOSAL]);

    await store.load(PROJECT_ID, authorize, api);
    expect(proposals).toHaveBeenCalledTimes(4);
    expect(store.proposals).toEqual(EVERY_PROPOSAL);
  });

  it("lets a reload share the request of a load still in flight", async () => {
    const pendingList = deferred<AlignmentProposalListPayload>();
    const proposals = vi.fn<KnowledgeAlignmentApi["proposals"]>(async () => pendingList.promise);
    const api = fakeApi({ proposals });
    const store = useKnowledgeAlignmentStore();

    const first = store.load(PROJECT_ID, authorize, api);
    const again = store.reload(PROJECT_ID, authorize, api);

    expect(proposals).toHaveBeenCalledTimes(1);
    pendingList.resolve(proposalList([TESTS_PROPOSAL]));

    await expect(Promise.all([first, again])).resolves.toEqual([
      [TESTS_PROPOSAL],
      [TESTS_PROPOSAL],
    ]);
    expect(store.proposals).toEqual([TESTS_PROPOSAL]);
  });

  it("gives the same refusal to every load that shared the request", async () => {
    const missing = failure(404, "PROJECT_NOT_FOUND");
    const proposals = vi.fn<KnowledgeAlignmentApi["proposals"]>(async () => {
      throw missing;
    });
    const api = fakeApi({ proposals });
    const store = useKnowledgeAlignmentStore();

    const first = store.load(PROJECT_ID, authorize, api);
    const second = store.load(PROJECT_ID, authorize, api);

    await expect(first).rejects.toBe(missing);
    await expect(second).rejects.toBe(missing);
    expect(proposals).toHaveBeenCalledTimes(1);
    expect(store.error).toEqual({
      message: "PROJECT_NOT_FOUND",
      code: "PROJECT_NOT_FOUND",
      status: 404,
    });
    expect(store.pending.load).toBe(false);

    proposals.mockResolvedValueOnce(proposalList([TESTS_PROPOSAL]));
    await expect(store.load(PROJECT_ID, authorize, api)).resolves.toEqual([TESTS_PROPOSAL]);
    expect(proposals).toHaveBeenCalledTimes(2);
    expect(store.error).toBeNull();
  });

  it("does not share the request with a load of another project or through another client", async () => {
    const pendingList = deferred<AlignmentProposalListPayload>();
    const proposals = vi.fn<KnowledgeAlignmentApi["proposals"]>(async () => pendingList.promise);
    const api = fakeApi({ proposals });
    const otherClient = fakeApi({ proposals });
    const store = useKnowledgeAlignmentStore();

    const first = store.load(PROJECT_ID, authorize, api);
    const second = store.load(PROJECT_ID, authorize, otherClient);
    const third = store.load(SECOND_PROJECT_ID, authorize, api);

    expect(proposals).toHaveBeenCalledTimes(3);
    expect(proposals.mock.calls.map((call) => call[0])).toEqual([
      PROJECT_ID,
      PROJECT_ID,
      SECOND_PROJECT_ID,
    ]);

    pendingList.resolve(proposalList([TESTS_PROPOSAL]));
    await Promise.all([first, second, third]);

    expect(store.projectId).toBe(SECOND_PROJECT_ID);
    expect(store.proposals).toEqual([TESTS_PROPOSAL]);
    expect(store.pending.load).toBe(false);
  });

  it("keeps the answer of the newest load when an older one, asked through another client, ends later", async () => {
    const older = deferred<AlignmentProposalListPayload>();
    const slow = fakeApi({ proposals: async () => older.promise });
    const fast = fakeApi({ proposals: async () => proposalList([TESTS_PROPOSAL]) });
    const store = useKnowledgeAlignmentStore();

    const first = store.load(PROJECT_ID, authorize, slow);
    await store.load(PROJECT_ID, authorize, fast);
    older.resolve(proposalList(EVERY_PROPOSAL));
    await first;

    expect(store.proposals).toEqual([TESTS_PROPOSAL]);
    expect(store.pending.load).toBe(false);
  });

  it("ignores the answers of a previous project", async () => {
    const pendingList = deferred<AlignmentProposalListPayload>();
    const pendingApply = deferred<ProposalApplyPayload>();
    const api = fakeApi({
      proposals: async () => pendingList.promise,
      apply: async () => pendingApply.promise,
    });
    const store = useKnowledgeAlignmentStore();

    const load = store.load(PROJECT_ID, authorize, api);
    const applying = store.apply(PROJECT_ID, "ALN-001", null, authorize, api);
    store.activateProject(SECOND_PROJECT_ID);
    pendingList.resolve(proposalList(EVERY_PROPOSAL));
    pendingApply.resolve(applyAnswer(REQUIREMENTS_PROPOSAL, null, DIFF_ID));
    await load;
    await expect(applying).resolves.toBe(DIFF_ID);

    expect(store.projectId).toBe(SECOND_PROJECT_ID);
    expect(store.proposals).toEqual([]);
    expect(store.latestRun).toBeNull();
    expect(store.deciding).toEqual({});
    expect(store.error).toBeNull();
    expect(store.isBusy).toBe(false);
  });

  it("reads the id of the diff from both kinds of revision", () => {
    expect(revisionDiffId(requirementsRevision(DIFF_ID))).toBe(DIFF_ID);
    expect(revisionDiffId(requirementsRevision(null))).toBeNull();
    expect(revisionDiffId(designChangeResult(DIFF_ID, []))).toBe(DIFF_ID);
    expect(revisionDiffId(null)).toBeNull();
  });
});
