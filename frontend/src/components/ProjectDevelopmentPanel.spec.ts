import { createPinia, setActivePinia } from "pinia";

import { flushPromises, mount } from "@vue/test-utils";

import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import ProjectDevelopmentPanel from "./ProjectDevelopmentPanel.vue";
import { createAppI18n } from "@/i18n";
import { expectAccessible } from "@/test/axe";
import { SELECTED_DESIGN_VERSION } from "@/test/designFixtures";

import { CodeChangesApiError, type CodeChangesApi } from "../api/codeChanges";
import {
  clearFollowedGenerations,
  GenerationJobsApiError,
  type GenerationJobsApi,
  type GenerationRequestJob,
} from "../api/generationJobs";
import type { KnowledgeAlignmentApi } from "../api/knowledgeAlignment";
import type { TwinLearningApi } from "../api/twinLearning";
import { useDesignStore } from "../stores/design";
import { useRequirementsStore } from "../stores/requirements";
import type {
  AlignmentPayload,
  ChangeReviewListPayload,
  ChangeReviewRunPayload,
  CodeChangeListPayload,
  CodeChangePayload,
  CodeTaskPayload,
  CodeTaskStatus,
} from "../types/codeChanges";
import type { GenerationOperation } from "../types/designMockups";
import type { KnowledgeAlignmentRunSummaryPayload } from "../types/knowledgeAlignment";
import type { RequirementsSpecificationVersionPayload } from "../types/requirements";
import type { TwinLearningPayload } from "../types/twinLearning";

type Locale = "en" | "it";

const PROJECT_ID = SELECTED_DESIGN_VERSION.project_id;
const SECOND_PROJECT_ID = "22222222-2222-4222-8222-222222222222";
const TOKEN = "test-token-not-real";
const NEWEST_COMMIT = "c0ffee1234567890abcdef1234567890abcdef12";
const SECOND_COMMIT = "b0b0b0b1b0b0b0b0b0b0b0b0b0b0b0b0b0b0b0b0";
const ALIGNED_COMMIT = "a1a1a1a2a1a1a1a1a1a1a1a1a1a1a1a1a1a1a1a1";
const RUN_ID = "33333333-3333-4333-8333-333333333333";
const RECEPTION_ID = "55555555-5555-4555-8555-555555555555";
const TEST_RUN_ID = "99999999-9999-4999-8999-999999999999";
const JOB_ID = "00000000-0000-4000-8000-0000000009aa";

const NEWEST: CodeChangePayload = {
  commit: NEWEST_COMMIT,
  parent: SECOND_COMMIT,
  committed_at: "2026-09-29T08:00:00+00:00",
  author: "Alex",
  message: "Show the reservations of the day\n\nThe list drops the empty state.",
  files: [
    { path: "src/reservations.js", kind: "MODIFIED", added: 30, removed: 4 },
    { path: "src/reservations.css", kind: "ADDED", added: 12, removed: 0 },
  ],
  recorded_at: "2026-09-29T08:01:00+00:00",
  review: {
    run_id: RUN_ID,
    reviewed_at: "2026-09-29T08:05:00+00:00",
    verdict: "CODE_DRIFT",
    summary: "The empty state of the list was removed.",
  },
  decision: { kind: "CODE_TASKS", decided_at: "2026-09-29T08:10:00+00:00", note: null },
};

const SECOND: CodeChangePayload = {
  commit: SECOND_COMMIT,
  parent: ALIGNED_COMMIT,
  committed_at: "2026-09-28T18:00:00+00:00",
  author: null,
  message: "Add the availability screen",
  files: [{ path: "src/availability.js", kind: "ADDED", added: 50, removed: 0 }],
  recorded_at: "2026-09-28T18:01:00+00:00",
  review: null,
  decision: null,
};

const ALIGNED: CodeChangePayload = {
  commit: ALIGNED_COMMIT,
  parent: null,
  committed_at: "2026-09-28T16:00:00+00:00",
  author: "Alex",
  message: "First screens",
  files: [],
  recorded_at: "2026-09-28T16:01:00+00:00",
  review: {
    run_id: "44444444-4444-4444-8444-444444444444",
    reviewed_at: "2026-09-28T16:05:00+00:00",
    verdict: "ALIGNED",
    summary: "The code follows the design.",
  },
  decision: { kind: "ALIGNED", decided_at: "2026-09-28T17:00:00+00:00", note: null },
};

const STALE_NEWEST: CodeChangePayload = {
  ...NEWEST,
  review: {
    ...NEWEST.review!,
    reference: {
      requirements_version_number: 2,
      design_version_number: 1,
      alternative_code: "DES-001",
    },
    stale: true,
  },
};

const FRESH_SECOND: CodeChangePayload = {
  ...SECOND,
  review: {
    run_id: "45454545-4545-4545-8545-454545454545",
    reviewed_at: "2026-09-28T18:05:00+00:00",
    verdict: "ALIGNED",
    summary: "The screen follows the design.",
    reference: {
      requirements_version_number: 2,
      design_version_number: 2,
      alternative_code: "DES-001",
    },
    stale: false,
  },
};

function task(
  code: string,
  overrides: Partial<CodeTaskPayload> = {},
  status: CodeTaskStatus = "OPEN",
): CodeTaskPayload {
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
    created_at: "2026-09-29T08:30:00+00:00",
    status,
    closed_at: status === "OPEN" ? null : "2026-09-29T09:00:00+00:00",
    note: null,
    ...overrides,
  };
}

const TWIN_TASK = task("TSK-001", {
  text: "Show again the message of an empty day.",
  about: { requirements: ["REQ-003"], screens: ["SCR-001"], criteria: [] },
  origin: {
    kind: "CODE_CHANGE",
    commit: NEWEST_COMMIT,
    test_run_id: null,
    twin_id: RECEPTION_ID,
    twin_name: "Reception staff",
    finding: "An empty day shows nothing, so I think that the list failed.",
  },
  from_commit: NEWEST_COMMIT,
  created_at: "2026-09-29T08:10:00+00:00",
});

const VERDICT_TASK = task("TSK-002", {
  text: "Keep the short format of the dates.",
  about: { requirements: [], screens: ["SCR-002"], criteria: [] },
  origin: {
    kind: "CODE_CHANGE",
    commit: NEWEST_COMMIT,
    test_run_id: null,
    twin_id: null,
    twin_name: null,
    finding: null,
  },
  from_commit: NEWEST_COMMIT,
});

const TEST_TASK = task("TSK-003", {
  text: "Show the new guest at the top of the list.",
  about: { requirements: ["REQ-003"], screens: [], criteria: ["AC-002"] },
  origin: {
    kind: "TEST_RUN",
    commit: null,
    test_run_id: TEST_RUN_ID,
    twin_id: RECEPTION_ID,
    twin_name: "Reception staff",
    finding: "A new guest did not appear at the top of the list.",
  },
});

const TESTS_TASK = task("TSK-004", {
  text: "Let the search find a guest by surname.",
  about: { requirements: [], screens: [], criteria: ["AC-002", "AC-005"] },
  origin: {
    kind: "TEST_RUN",
    commit: null,
    test_run_id: TEST_RUN_ID,
    twin_id: RECEPTION_ID,
    twin_name: "Reception staff",
    finding: "The search did not find a guest by surname.",
  },
});

const OWNER_TASK = task("TSK-005", { text: "Add a search by name." });

const SPRINT_27_TASK = {
  code: "TSK-001",
  text: "Show again the message of an empty day.",
  about: { requirements: ["REQ-003"], screens: ["SCR-001"] },
  from_commit: NEWEST_COMMIT,
  created_at: "2026-09-29T08:10:00+00:00",
  status: "OPEN",
} as CodeTaskPayload;

const ALIGNMENT: AlignmentPayload = {
  project_id: PROJECT_ID,
  reference: {
    requirements: { version_id: "requirements", version_number: 2, content_hash: "a".repeat(64) },
    design: {
      version_id: SELECTED_DESIGN_VERSION.id,
      version_number: 2,
      content_hash: SELECTED_DESIGN_VERSION.content_hash,
      alternative_code: "DES-001",
    },
  },
  aligned: {
    commit: ALIGNED_COMMIT,
    decided_at: "2026-09-28T17:00:00+00:00",
    requirements_version_number: 2,
    design_version_number: 2,
  },
  pending_changes: 2,
  latest_change: NEWEST,
  tasks: [TWIN_TASK],
  review_available: true,
};

const RUN: ChangeReviewRunPayload = {
  id: RUN_ID,
  commit: NEWEST_COMMIT,
  reviewed_at: "2026-09-29T08:05:00+00:00",
  locale: "en-US",
  reference: {
    requirements_version_number: 2,
    design_version_number: 2,
    alternative_code: "DES-001",
  },
  critiques: [
    {
      twin_id: RECEPTION_ID,
      twin_name: "Reception staff",
      verdict: "CONCERN",
      summary: "I can see the reservations, but an empty day now shows a blank page.",
      findings: [
        {
          severity: "HIGH",
          text: "An empty day shows nothing, so I think that the list failed.",
          about: { requirement: "REQ-003", screen: "SCR-001", file: "src/reservations.js" },
          action: "Show a sentence when there is no reservation.",
        },
        {
          severity: "LOW",
          text: "The dates use a long format.",
          about: { requirement: null, screen: "SCR-002", file: null },
          action: null,
        },
      ],
    },
    {
      twin_id: "66666666-6666-4666-8666-666666666666",
      twin_name: "Restaurant manager",
      verdict: "FINE",
      summary: "The list of the day is what I need.",
      findings: [
        {
          severity: "MEDIUM",
          text: "I would like the total of the guests.",
          about: { requirement: "REQ-009", screen: null, file: null },
          action: "Add the total of the guests under the list.",
        },
      ],
    },
  ],
  alignment: {
    status: "CODE_DRIFT",
    summary: "The empty state of the list was removed.",
    affected: { requirements: ["REQ-003"], screens: ["SCR-001"] },
    design_request: null,
    requirements_request: null,
    code_tasks: ["Show again the message of an empty day.", "Keep the short format of the dates."],
  },
  cost_microusd: 650000,
};

const EMPTY: AlignmentPayload = {
  ...ALIGNMENT,
  aligned: null,
  pending_changes: 0,
  latest_change: null,
  tasks: [],
};

const DESIGN_AHEAD: AlignmentPayload = {
  ...ALIGNMENT,
  reference: {
    ...ALIGNMENT.reference,
    design: { ...ALIGNMENT.reference.design!, version_number: 6 },
  },
  aligned: { ...ALIGNMENT.aligned!, design_version_number: 3 },
};

const DESIGN_REACHED: AlignmentPayload = {
  ...DESIGN_AHEAD,
  aligned: { ...ALIGNMENT.aligned!, design_version_number: 6 },
};

const NOT_ALIGNED: AlignmentPayload = { ...EMPTY, reference: DESIGN_AHEAD.reference };

const UNKNOWN_ALIGNED_DESIGN: AlignmentPayload = {
  ...DESIGN_AHEAD,
  aligned: { ...ALIGNMENT.aligned!, design_version_number: null },
};

const NO_APPROVED_DESIGN: AlignmentPayload = {
  ...DESIGN_AHEAD,
  reference: { ...ALIGNMENT.reference, design: null },
};

const LEARNING: TwinLearningPayload = {
  project_id: PROJECT_ID,
  update_available: true,
  twins: [
    {
      twin_id: RECEPTION_ID,
      twin_name: "Reception staff",
      profile_version_number: 1,
      development_version_number: 1,
      label: "1.1",
      observations: [
        {
          code: "OBS-001",
          statement: "Reception staff need a sentence when a day has no reservation.",
          basis: "Two findings on the commits of the list.",
          source: "TWIN_CRITIQUE",
          about: { requirement: "REQ-003", screen: "SCR-001" },
          contradicts_profile: null,
          added_in_version: 1,
          approved_at: "2026-09-29T09:30:00+00:00",
          update_id: "77777777-7777-4777-8777-777777777777",
        },
      ],
      retired: [],
      pending_update: null,
      new_material: { changes: 1, tests: 0 },
    },
  ],
};

const NO_TWINS: TwinLearningPayload = { ...LEARNING, twins: [] };

const KNOWLEDGE_RUN: KnowledgeAlignmentRunSummaryPayload = {
  id: "88888888-8888-4888-8888-888888888888",
  project_id: PROJECT_ID,
  from_commit: ALIGNED_COMMIT,
  to_commit: NEWEST_COMMIT,
  commits: [SECOND_COMMIT, NEWEST_COMMIT],
  locale: "en-US",
  requirements_version_number: 2,
  design_version_number: 2,
  alternative_code: "DES-001",
  summary: "The code shows the reservations of the day and drops the empty state of the list.",
  created_at: "2026-09-29T09:30:00+00:00",
  cost_microusd: 320000,
  generation_ids: ["88888888-8888-4888-8888-888888888801"],
  waiting: 1,
  proposals_count: 3,
};

const EARLIER_KNOWLEDGE_RUN: KnowledgeAlignmentRunSummaryPayload = {
  ...KNOWLEDGE_RUN,
  id: "88888888-8888-4888-8888-888888888880",
  from_commit: null,
  to_commit: ALIGNED_COMMIT,
  commits: [ALIGNED_COMMIT],
  summary: "The first screens follow the design.",
  created_at: "2026-09-28T16:30:00+00:00",
  waiting: 0,
  proposals_count: 0,
};

function requirementsVersion(): RequirementsSpecificationVersionPayload {
  return {
    id: "requirements",
    project_id: PROJECT_ID,
    version_number: 2,
    specification: {
      requirements: [
        { code: "REQ-003", title: "Guests are checked in quickly" },
        { code: "REQ-004", title: "The manager sees the day" },
      ],
    },
  } as unknown as RequirementsSpecificationVersionPayload;
}

function changes(...items: CodeChangePayload[]): CodeChangeListPayload {
  return { items };
}

function developmentApi(overrides: Partial<CodeChangesApi> = {}) {
  return {
    alignment: vi.fn<CodeChangesApi["alignment"]>(async () => ALIGNMENT),
    changes: vi.fn<CodeChangesApi["changes"]>(async () => changes(NEWEST, SECOND, ALIGNED)),
    reviews: vi.fn<CodeChangesApi["reviews"]>(async () => ({ items: [RUN] })),
    tasks: vi.fn<CodeChangesApi["tasks"]>(async () => ({ items: [TWIN_TASK] })),
    ...overrides,
  };
}

function learningApi(read: TwinLearningApi["overview"] = async () => NO_TWINS) {
  return { overview: vi.fn<TwinLearningApi["overview"]>(read) };
}

function alignmentApi(runs: KnowledgeAlignmentRunSummaryPayload[] = []) {
  const unused = async () => {
    throw new TypeError("Failed to fetch");
  };
  return {
    runs: vi.fn<KnowledgeAlignmentApi["runs"]>(async () => ({ items: runs })),
    proposals: vi.fn<KnowledgeAlignmentApi["proposals"]>(unused),
    apply: vi.fn<KnowledgeAlignmentApi["apply"]>(unused),
    skip: vi.fn<KnowledgeAlignmentApi["skip"]>(unused),
  };
}

function generation(
  operation: GenerationOperation,
  overrides: Partial<GenerationRequestJob> = {},
): GenerationRequestJob {
  return {
    job_id: JOB_ID,
    kind: "REQUEST",
    operation,
    status: "RUNNING",
    stage: "GENERATING",
    attempt: 1,
    started_at: "2026-09-29T09:00:00+00:00",
    finished_at: null,
    alternative_id: null,
    failure: null,
    response: null,
    ...overrides,
  };
}

function finished(operation: GenerationOperation): GenerationRequestJob {
  return generation(operation, {
    status: "SUCCEEDED",
    stage: null,
    finished_at: "2026-09-29T09:02:00+00:00",
    response: { status_code: 201, body: { status: "REVIEWED" } },
  });
}

function jobsApi(running: GenerationRequestJob[] = [], reads: GenerationRequestJob[] = []) {
  return {
    list: vi.fn<GenerationJobsApi["list"]>(async () => running),
    job: vi.fn<GenerationJobsApi["job"]>(async () => {
      const next = reads.shift();
      if (next === undefined) {
        throw new TypeError("Failed to fetch");
      }
      return next;
    }),
  };
}

interface Extras {
  learning?: TwinLearningApi;
  jobs?: GenerationJobsApi;
  alignment?: KnowledgeAlignmentApi;
  active?: boolean;
}

function mountPanel(api: CodeChangesApi, locale: Locale = "en", extras: Extras = {}) {
  return mount(ProjectDevelopmentPanel, {
    global: { plugins: [createAppI18n(locale)] },
    props: {
      projectId: PROJECT_ID,
      locale,
      authorize: (operation) => operation(TOKEN),
      api,
      learningApi: extras.learning ?? learningApi(),
      jobsApi: extras.jobs ?? jobsApi(),
      alignmentApi: extras.alignment ?? alignmentApi(),
      ...(extras.active === undefined ? {} : { active: extras.active }),
    },
    attachTo: document.body,
  });
}

function words(value: string): string {
  return value.replace(/\s+/g, " ").trim();
}

function spoken(element: { text(): string }): string {
  return words(element.text());
}

function dated(value: string, locale: Locale): string {
  return new Intl.DateTimeFormat(locale === "it" ? "it-IT" : "en-GB", {
    dateStyle: "medium",
    timeStyle: "short",
  }).format(Date.parse(value));
}

describe("ProjectDevelopmentPanel", () => {
  beforeEach(() => {
    setActivePinia(createPinia());
    document.body.innerHTML = "";
    clearFollowedGenerations();
    useDesignStore().$patch({ projectId: PROJECT_ID, current: SELECTED_DESIGN_VERSION });
    useRequirementsStore().$patch({ projectId: PROJECT_ID, current: requirementsVersion() });
  });

  afterEach(() => {
    vi.useRealTimers();
    clearFollowedGenerations();
  });

  it("reads the alignment, every recorded change, every task and the latest run of the newest reviewed commit", async () => {
    const api = developmentApi();
    const learning = learningApi();
    const jobs = jobsApi();
    const wrapper = mountPanel(api, "en", { learning, jobs });
    await flushPromises();

    expect(api.alignment).toHaveBeenCalledWith(PROJECT_ID, TOKEN);
    expect(api.changes).toHaveBeenCalledWith(PROJECT_ID, TOKEN);
    expect(api.tasks).toHaveBeenCalledWith(PROJECT_ID, TOKEN, "all");
    expect(api.reviews).toHaveBeenCalledWith(PROJECT_ID, NEWEST_COMMIT, TOKEN);
    expect(learning.overview).toHaveBeenCalledTimes(1);
    expect(learning.overview).toHaveBeenCalledWith(PROJECT_ID, TOKEN);
    expect(jobs.list).toHaveBeenCalledTimes(1);
    expect(jobs.list).toHaveBeenCalledWith(PROJECT_ID, TOKEN, "RUNNING");
    expect(wrapper.get("h2").text()).toBe("Development outside the Studio");
    expect(spoken(wrapper.get('[data-testid="development-terminal"]'))).toBe(
      "Reviews and decisions are made from the terminal with ut verify: this page only shows their result.",
    );
    expect(wrapper.get('[data-testid="development-terminal"] code').text()).toBe("ut verify");
    expect(wrapper.find('[data-testid="development-job"]').exists()).toBe(false);
    expect(wrapper.find('[data-testid="learning-block"]').exists()).toBe(false);
    wrapper.unmount();
  });

  it("shows the approved reference with the title of the chosen alternative and the aligned point", async () => {
    const wrapper = mountPanel(developmentApi());
    await flushPromises();

    expect(wrapper.get('[data-testid="development-reference-requirements"]').text()).toBe(
      "version 2",
    );
    expect(spoken(wrapper.get('[data-testid="development-reference-design"]'))).toBe(
      "version 2 · DES-001 · Guided reservation flow",
    );
    expect(spoken(wrapper.get('[data-testid="development-aligned"]'))).toBe(
      words(`commit a1a1a1a · ${dated("2026-09-28T17:00:00+00:00", "en")}`),
    );
    expect(wrapper.find('[data-testid="development-no-model"]').exists()).toBe(false);
    expect(wrapper.find('[data-testid="development-empty"]').exists()).toBe(false);
    wrapper.unmount();
  });

  it.each([
    [
      "en",
      "The design is at version 6, the code is aligned with version 3: from the terminal ut align --from-design brings the code up to the current design.",
    ],
    [
      "it",
      "Il design è alla versione 6, il codice è allineato alla versione 3: dal terminale ut align --from-design porta il codice al design attuale.",
    ],
  ] as const)(
    "says in %s right after the aligned point that the design is ahead of the code",
    async (locale, sentence) => {
      const wrapper = mountPanel(developmentApi({ alignment: async () => DESIGN_AHEAD }), locale);
      await flushPromises();

      const notice = wrapper.get('[data-testid="development-design-ahead"]');
      expect(spoken(notice)).toBe(sentence);
      expect(notice.findAll("code").map((item) => item.text())).toEqual(["ut align --from-design"]);
      const reference = wrapper.get('[data-testid="development-reference"]').element;
      expect(reference.parentElement?.nextElementSibling).toBe(notice.element);
      await expectAccessible(wrapper.element);
      wrapper.unmount();
    },
  );

  it.each([
    ["at the same version", DESIGN_REACHED],
    ["before any commit is aligned", NOT_ALIGNED],
    ["when the aligned point names no design version", UNKNOWN_ALIGNED_DESIGN],
    ["when no design is approved", NO_APPROVED_DESIGN],
  ] as const)(
    "says nothing about the design being ahead of the code %s",
    async (_case, payload) => {
      const wrapper = mountPanel(developmentApi({ alignment: async () => payload }));
      await flushPromises();

      expect(wrapper.find('[data-testid="development-reference"]').exists()).toBe(true);
      expect(wrapper.find('[data-testid="development-design-ahead"]').exists()).toBe(false);
      wrapper.unmount();
    },
  );

  it("keeps its content as wide as the section, whatever a long word inside it holds", async () => {
    const wrapper = mountPanel(developmentApi());
    await flushPromises();

    expect(wrapper.get('[data-testid="development-state"]').classes()).toEqual(
      expect.arrayContaining(["grid", "grid-cols-1"]),
    );
    wrapper.unmount();
  });

  it("lists the commits after the aligned point with their verdict and decision in words", async () => {
    const wrapper = mountPanel(developmentApi());
    await flushPromises();

    expect(wrapper.get('[data-testid="development-pending"] h3').text()).toBe(
      "Pending commits (2)",
    );
    const rows = wrapper.findAll('[data-testid="development-change"]');
    expect(rows).toHaveLength(2);
    expect(spoken(rows[0]!.get("p"))).toBe(
      words(`c0ffee1 · ${dated(NEWEST.committed_at, "en")} · 2 files`),
    );
    expect(rows[0]!.get('[data-testid="development-change-title"]').text()).toBe(
      "Show the reservations of the day",
    );
    const verdict = rows[0]!.get('[data-testid="development-change-verdict"]');
    expect(verdict.text()).toBe("Review: the code should change");
    expect(verdict.attributes("data-status")).toBe("failed");
    const decision = rows[0]!.get('[data-testid="development-change-decision"]');
    expect(decision.text()).toBe("Decision: tasks for the code");
    expect(decision.attributes("data-status")).toBe("blocked");
    expect(spoken(rows[1]!.get("p"))).toBe(
      words(`b0b0b0b · ${dated(SECOND.committed_at, "en")} · 1 file`),
    );
    expect(rows[1]!.get('[data-testid="development-change-verdict"]').text()).toBe(
      "Not reviewed yet",
    );
    expect(rows[1]!.get('[data-testid="development-change-decision"]').text()).toBe(
      "No decision yet",
    );
    expect(wrapper.text()).not.toContain("First screens");
    wrapper.unmount();
  });

  it("lists the open tasks with where they come from and the codes they name next to their titles", async () => {
    const wrapper = mountPanel(developmentApi());
    await flushPromises();

    expect(wrapper.get('[data-testid="development-tasks"] h3').text()).toBe(
      "Open tasks for the code (1)",
    );
    const item = wrapper.get('[data-testid="development-task"]');
    expect(item.get('[data-testid="development-task-code"]').text()).toBe("TSK-001");
    expect(spoken(item.get("p"))).toBe("TSK-001 · Show again the message of an empty day.");
    expect(item.get('[data-testid="development-task-origin"]').text()).toBe(
      "From Reception staff on the commit c0ffee1",
    );
    expect(item.findAll('[data-testid="development-subject"]').map(spoken)).toEqual([
      "REQ-003 · Guests are checked in quickly",
      "SCR-001 · Availability",
    ]);
    expect(wrapper.find('[data-testid="development-tasks-closed"]').exists()).toBe(false);
    wrapper.unmount();
  });

  it.each([
    [
      "en",
      [
        "From Reception staff on the commit c0ffee1",
        "From the decision on the commit c0ffee1",
        "From Reception staff on the acceptance tests, criterion AC-002",
        "From Reception staff on the acceptance tests, criteria AC-002, AC-005",
        "Written by you",
      ],
    ],
    [
      "it",
      [
        "Da Reception staff sul commit c0ffee1",
        "Dalla decisione sul commit c0ffee1",
        "Da Reception staff sulla verifica dei criteri, criterio AC-002",
        "Da Reception staff sulla verifica dei criteri, criteri AC-002, AC-005",
        "Scritto da te",
      ],
    ],
  ] as const)("says in %s where every task comes from", async (locale, origins) => {
    const every = [TWIN_TASK, VERDICT_TASK, TEST_TASK, TESTS_TASK, OWNER_TASK];
    const wrapper = mountPanel(
      developmentApi({
        alignment: async () => ({ ...ALIGNMENT, tasks: every }),
        tasks: async () => ({ items: every }),
      }),
      locale,
    );
    await flushPromises();

    const rows = wrapper.findAll('[data-testid="development-task"]');
    expect(rows.map((row) => row.get('[data-testid="development-task-code"]').text())).toEqual([
      "TSK-001",
      "TSK-002",
      "TSK-003",
      "TSK-004",
      "TSK-005",
    ]);
    expect(rows.map((row) => row.get('[data-testid="development-task-origin"]').text())).toEqual(
      origins,
    );
    expect(rows[2]!.findAll('[data-testid="development-subject"]').map(spoken)).toEqual([
      "REQ-003 · Guests are checked in quickly",
    ]);
    expect(rows[4]!.find('[data-testid="development-subject"]').exists()).toBe(false);
    wrapper.unmount();
  });

  it.each([
    ["en", ["DONE", "DONE", "DROPPED"], "Tasks closed so far: 2 done and 1 dropped."],
    ["en", ["DONE"], "Tasks closed so far: 1 done."],
    ["en", ["DROPPED", "DROPPED"], "Tasks closed so far: 2 dropped."],
    ["it", ["DONE", "DONE", "DROPPED"], "Compiti chiusi finora: 2 completati e 1 scartato."],
    ["it", ["DONE"], "Compiti chiusi finora: 1 completato."],
    ["it", ["DROPPED", "DROPPED"], "Compiti chiusi finora: 2 scartati."],
  ] as const)(
    "counts in %s the closed tasks %j in one closing sentence",
    async (locale, statuses, sentence) => {
      const closed = statuses.map((status, index) => task(`TSK-10${index}`, {}, status));
      const wrapper = mountPanel(
        developmentApi({ tasks: async () => ({ items: [TWIN_TASK, ...closed] }) }),
        locale,
      );
      await flushPromises();

      expect(wrapper.findAll('[data-testid="development-task"]')).toHaveLength(1);
      expect(wrapper.get('[data-testid="development-tasks-closed"]').text()).toBe(sentence);
      wrapper.unmount();
    },
  );

  it.each([
    [
      "en",
      "From the terminal, ut tasks adds, closes and drops the tasks, and ut code hands the open ones to your coding agent.",
    ],
    [
      "it",
      "Dal terminale, ut tasks aggiunge, chiude e scarta i compiti, e ut code affida quelli aperti al tuo agente di programmazione.",
    ],
  ] as const)("names ut tasks and ut code in %s", async (locale, sentence) => {
    const wrapper = mountPanel(developmentApi(), locale);
    await flushPromises();

    const terminal = wrapper.get('[data-testid="development-tasks-terminal"]');
    expect(spoken(terminal)).toBe(sentence);
    expect(terminal.findAll("code").map((item) => item.text())).toEqual(["ut tasks", "ut code"]);
    wrapper.unmount();
  });

  it("shows the tasks written by the owner before any commit is recorded", async () => {
    const api = developmentApi({
      alignment: async () => ({ ...EMPTY, tasks: [OWNER_TASK] }),
      changes: async () => changes(),
      tasks: async () => ({ items: [OWNER_TASK, task("TSK-006", {}, "DROPPED")] }),
    });
    const wrapper = mountPanel(api);
    await flushPromises();

    expect(wrapper.find('[data-testid="development-empty"]').exists()).toBe(true);
    expect(wrapper.find('[data-testid="development-pending"]').exists()).toBe(false);
    expect(wrapper.find('[data-testid="development-run"]').exists()).toBe(false);
    expect(wrapper.get('[data-testid="development-tasks"] h3').text()).toBe(
      "Open tasks for the code (1)",
    );
    expect(wrapper.get('[data-testid="development-task-origin"]').text()).toBe("Written by you");
    expect(wrapper.get('[data-testid="development-tasks-closed"]').text()).toBe(
      "Tasks closed so far: 1 dropped.",
    );
    wrapper.unmount();
  });

  it("falls back to what it showed before for a Studio of the previous sprint", async () => {
    const api = developmentApi({
      alignment: async () => ({ ...ALIGNMENT, tasks: [SPRINT_27_TASK] }),
      tasks: async () => {
        throw new CodeChangesApiError("The code change request failed", {
          status: 404,
          code: null,
          payload: { detail: "Not Found" },
        });
      },
    });
    const learning = learningApi(async () => null);
    const wrapper = mountPanel(api, "en", { learning });
    await flushPromises();

    const item = wrapper.get('[data-testid="development-task"]');
    expect(spoken(item.get("p"))).toBe("TSK-001 · Show again the message of an empty day.");
    expect(item.find('[data-testid="development-task-origin"]').exists()).toBe(false);
    expect(item.findAll('[data-testid="development-subject"]').map(spoken)).toEqual([
      "REQ-003 · Guests are checked in quickly",
      "SCR-001 · Availability",
    ]);
    expect(wrapper.find('[data-testid="development-tasks-closed"]').exists()).toBe(false);
    expect(wrapper.find('[data-testid="development-stale"]').exists()).toBe(false);
    expect(wrapper.find('[data-testid="development-change-stale"]').exists()).toBe(false);
    expect(wrapper.find('[data-testid="development-change-reference"]').exists()).toBe(false);
    expect(wrapper.find('[data-testid="learning-block"]').exists()).toBe(false);
    expect(wrapper.find('[data-testid="development-error"]').exists()).toBe(false);
    expect(wrapper.findAll('[data-testid="development-change"]')).toHaveLength(2);
    expect(wrapper.findAll('[data-testid="development-critique"]')).toHaveLength(2);
    wrapper.unmount();
  });

  it.each([
    [
      "en",
      1,
      "1 review was made against earlier versions of the requirements or of the design: ut verify --recheck has the twins review that commit again.",
      "To re-review",
      "Reviewed against requirements version 2 and design version 1 (DES-001)",
    ],
    [
      "en",
      2,
      "2 reviews were made against earlier versions of the requirements or of the design: ut verify --recheck has the twins review those commits again.",
      "To re-review",
      "Reviewed against requirements version 2 and design version 1 (DES-001)",
    ],
    [
      "it",
      1,
      "1 revisione è stata fatta su versioni precedenti dei requisiti o del design: ut verify --recheck fa riesaminare quel commit ai twin.",
      "Da riesaminare",
      "Rivisto rispetto ai requisiti versione 2 e al design versione 1 (DES-001)",
    ],
    [
      "it",
      2,
      "2 revisioni sono state fatte su versioni precedenti dei requisiti o del design: ut verify --recheck fa riesaminare quei commit ai twin.",
      "Da riesaminare",
      "Rivisto rispetto ai requisiti versione 2 e al design versione 1 (DES-001)",
    ],
  ] as const)(
    "marks in %s the commits whose review is stale and says that %i must be reviewed again",
    async (locale, count, sentence, chip, reference) => {
      const wrapper = mountPanel(
        developmentApi({
          alignment: async () => ({ ...ALIGNMENT, stale_reviews: count }),
          changes: async () => changes(STALE_NEWEST, FRESH_SECOND, ALIGNED),
        }),
        locale,
      );
      await flushPromises();

      const notice = wrapper.get(
        '[data-testid="development-pending"] [data-testid="development-stale"]',
      );
      expect(spoken(notice)).toBe(sentence);
      expect(notice.findAll("code").map((item) => item.text())).toEqual(["ut verify --recheck"]);
      const rows = wrapper.findAll('[data-testid="development-change"]');
      const stale = rows[0]!.get('[data-testid="development-change-stale"]');
      expect(stale.text()).toBe(chip);
      expect(stale.attributes("data-status")).toBe("blocked");
      expect(rows[0]!.get('[data-testid="development-change-reference"]').text()).toBe(reference);
      expect(rows[1]!.find('[data-testid="development-change-stale"]').exists()).toBe(false);
      expect(rows[1]!.find('[data-testid="development-change-reference"]').exists()).toBe(false);
      wrapper.unmount();
    },
  );

  it("says nothing about stale reviews when the Studio counts none", async () => {
    const wrapper = mountPanel(
      developmentApi({
        alignment: async () => ({ ...ALIGNMENT, stale_reviews: 0 }),
        changes: async () => changes(NEWEST, FRESH_SECOND, ALIGNED),
      }),
    );
    await flushPromises();

    expect(wrapper.find('[data-testid="development-stale"]').exists()).toBe(false);
    expect(wrapper.find('[data-testid="development-change-stale"]').exists()).toBe(false);
    wrapper.unmount();
  });

  it("shows what the twins learned inside the section, after the latest review", async () => {
    const wrapper = mountPanel(developmentApi(), "en", {
      learning: learningApi(async () => LEARNING),
    });
    await flushPromises();

    const block = wrapper.get('[data-testid="development-state"] [data-testid="learning-block"]');
    expect(block.get("h3").text()).toBe("What the twins learned");
    expect(block.get('[data-testid="learning-twin"] h4').text()).toBe("Reception staff");
    expect(block.get('[data-testid="learning-twin-label"]').text()).toBe("version 1.1");
    expect(block.findAll('[data-testid="learning-subject"]').map(spoken)).toEqual([
      "REQ-003 · Guests are checked in quickly",
      "SCR-001 · Availability",
    ]);
    const run = wrapper.get('[data-testid="development-run"]').element;
    expect(run.compareDocumentPosition(block.element) & Node.DOCUMENT_POSITION_FOLLOWING).toBe(
      Node.DOCUMENT_POSITION_FOLLOWING,
    );
    wrapper.unmount();
  });

  it("shows the latest run: one block per twin with the findings, then the verdict of the model", async () => {
    const wrapper = mountPanel(developmentApi());
    await flushPromises();

    const run = wrapper.get('[data-testid="development-run"]');
    expect(run.get("h3").text()).toBe("Latest review, commit c0ffee1");
    expect(spoken(run.get('[data-testid="development-run-meta"]'))).toBe(
      words(
        `${dated(RUN.reviewed_at, "en")} · checked against requirements version 2 and design version 2 (DES-001)`,
      ),
    );

    const critiques = run.findAll('[data-testid="development-critique"]');
    expect(critiques).toHaveLength(2);
    expect(critiques.map((critique) => critique.get("h4").text())).toEqual([
      "Reception staff",
      "Restaurant manager",
    ]);
    const concern = critiques[0]!.get('[data-testid="development-critique-verdict"]');
    expect(concern.text()).toBe("Some concerns");
    expect(concern.attributes("data-status")).toBe("blocked");
    expect(critiques[0]!.text()).toContain(
      "I can see the reservations, but an empty day now shows a blank page.",
    );
    expect(critiques[0]!.text()).toContain("AI proposal, not validated");
    const findings = critiques[0]!.findAll('[data-testid="development-finding"]');
    expect(findings).toHaveLength(2);
    expect(findings[0]!.get('[data-testid="development-finding-severity"]').text()).toBe("Major");
    expect(spoken(findings[0]!)).toContain(
      "Major An empty day shows nothing, so I think that the list failed.",
    );
    expect(findings[0]!.findAll('[data-testid="development-subject"]').map(spoken)).toEqual([
      "REQ-003 · Guests are checked in quickly",
      "SCR-001 · Availability",
      "src/reservations.js",
    ]);
    expect(findings[0]!.findAll('[data-testid="development-subject"]')[2]!.get("code").text()).toBe(
      "src/reservations.js",
    );
    expect(spoken(findings[0]!)).toContain(
      "Suggested action: Show a sentence when there is no reservation.",
    );
    expect(findings[1]!.get('[data-testid="development-finding-severity"]').text()).toBe("Minor");
    expect(findings[1]!.findAll('[data-testid="development-subject"]').map(spoken)).toEqual([
      "SCR-002 · Reservation",
    ]);
    expect(findings[1]!.text()).not.toContain("Suggested action");

    const fine = critiques[1]!.get('[data-testid="development-critique-verdict"]');
    expect(fine.text()).toBe("No concerns");
    expect(fine.attributes("data-status")).toBe("approved");
    const moderate = critiques[1]!.get('[data-testid="development-finding"]');
    expect(moderate.get('[data-testid="development-finding-severity"]').text()).toBe("Moderate");
    expect(moderate.findAll('[data-testid="development-subject"]').map(spoken)).toEqual([
      "REQ-009",
    ]);

    const verdict = run.get('[data-testid="development-verdict"]');
    expect(verdict.get("h4").text()).toBe("The model's verdict");
    expect(verdict.get('[data-testid="development-verdict-status"]').text()).toBe(
      "Review: the code should change",
    );
    expect(verdict.text()).toContain(
      "The code moves away from the approved requirements or design: the code should change.",
    );
    expect(verdict.text()).toContain("The empty state of the list was removed.");
    expect(verdict.findAll('[data-testid="development-subject"]').map(spoken)).toEqual([
      "REQ-003 · Guests are checked in quickly",
      "SCR-001 · Availability",
    ]);
    expect(verdict.findAll('[data-testid="development-code-task"]').map(spoken)).toEqual([
      "Show again the message of an empty day.",
      "Keep the short format of the dates.",
    ]);
    expect(spoken(verdict.get('[data-testid="development-code-tasks"]'))).toContain(
      "They become open tasks only when you decide so with ut verify.",
    );
    expect(verdict.find('[data-testid="development-design-request"]').exists()).toBe(false);
    expect(verdict.find('[data-testid="development-requirements-request"]').exists()).toBe(false);
    wrapper.unmount();
  });

  it("offers only the control that reads the section again, never one that starts a review or a decision", async () => {
    const wrapper = mountPanel(
      developmentApi({
        alignment: async () => ({ ...ALIGNMENT, stale_reviews: 1 }),
        changes: async () => changes(STALE_NEWEST, SECOND, ALIGNED),
      }),
      "en",
      { learning: learningApi(async () => LEARNING) },
    );
    await flushPromises();

    expect(wrapper.findAll("button").map((button) => button.attributes("data-testid"))).toEqual([
      "development-refresh",
      "step-technical-details-toggle",
    ]);
    const refresh = wrapper.get('[data-testid="development-refresh"]');
    expect(refresh.text()).toBe("Read again");
    expect(refresh.attributes("aria-describedby")).toBe("development-title");
    expect(wrapper.findAll("a")).toHaveLength(0);
    expect(wrapper.findAll("input, select, textarea")).toHaveLength(0);
    wrapper.unmount();
  });

  it.each([
    [
      "DESIGN_OUTDATED",
      "development-design-request",
      "Design change to request",
      "The change is a sound evolution: the design should get a new version.",
    ],
    [
      "REQUIREMENTS_OUTDATED",
      "development-requirements-request",
      "Requirements change to request",
      "The change is a sound evolution: the requirements should get a new version.",
    ],
  ] as const)("quotes the request of a %s verdict", async (status, testId, label, sentence) => {
    const request = "Add a screen that shows the guests waiting for a table.";
    const run: ChangeReviewRunPayload = {
      ...RUN,
      alignment: {
        ...RUN.alignment,
        status,
        design_request: status === "DESIGN_OUTDATED" ? request : null,
        requirements_request: status === "REQUIREMENTS_OUTDATED" ? request : null,
        code_tasks: [],
      },
    };
    const wrapper = mountPanel(developmentApi({ reviews: async () => ({ items: [run] }) }));
    await flushPromises();

    const verdict = wrapper.get('[data-testid="development-verdict"]');
    const quoted = verdict.get(`[data-testid="${testId}"]`);
    expect(quoted.get("p").text()).toBe(label);
    expect(quoted.get("blockquote").text()).toBe(request);
    expect(verdict.text()).toContain(sentence);
    expect(
      verdict.get('[data-testid="development-verdict-status"]').attributes("data-status"),
    ).toBe("blocked");
    expect(verdict.find('[data-testid="development-code-tasks"]').exists()).toBe(false);
    wrapper.unmount();
  });

  it("speaks Italian", async () => {
    const wrapper = mountPanel(developmentApi(), "it");
    await flushPromises();

    expect(wrapper.get("h2").text()).toBe("Sviluppo fuori dallo Studio");
    expect(spoken(wrapper.get('[data-testid="development-terminal"]'))).toBe(
      "Revisioni e decisioni si fanno dal terminale con ut verify: questa pagina ne mostra solo il risultato.",
    );
    expect(wrapper.get('[data-testid="development-reference-requirements"]').text()).toBe(
      "versione 2",
    );
    expect(wrapper.get('[data-testid="development-pending"] h3').text()).toBe(
      "Commit in attesa (2)",
    );
    const rows = wrapper.findAll('[data-testid="development-change"]');
    expect(spoken(rows[0]!.get("p"))).toBe(
      words(`c0ffee1 · ${dated(NEWEST.committed_at, "it")} · 2 file`),
    );
    expect(rows[0]!.get('[data-testid="development-change-verdict"]').text()).toBe(
      "Revisione: va cambiato il codice",
    );
    expect(rows[0]!.get('[data-testid="development-change-decision"]').text()).toBe(
      "Decisione: compiti per il codice",
    );
    expect(rows[1]!.get('[data-testid="development-change-verdict"]').text()).toBe(
      "Non ancora rivisto",
    );
    expect(wrapper.get('[data-testid="development-tasks"] h3').text()).toBe(
      "Compiti aperti per il codice (1)",
    );
    expect(wrapper.get('[data-testid="development-task-origin"]').text()).toBe(
      "Da Reception staff sul commit c0ffee1",
    );
    const run = wrapper.get('[data-testid="development-run"]');
    expect(run.get("h3").text()).toBe("Ultima revisione, commit c0ffee1");
    expect(spoken(run.get('[data-testid="development-run-meta"]'))).toBe(
      words(
        `${dated(RUN.reviewed_at, "it")} · confrontata con i requisiti versione 2 e il design versione 2 (DES-001)`,
      ),
    );
    expect(run.get('[data-testid="development-critique-verdict"]').text()).toBe("Qualche dubbio");
    expect(run.get('[data-testid="development-finding-severity"]').text()).toBe("Importante");
    expect(spoken(run.get('[data-testid="development-finding"]'))).toContain(
      "Azione suggerita: Show a sentence when there is no reservation.",
    );
    const verdict = run.get('[data-testid="development-verdict"]');
    expect(verdict.get("h4").text()).toBe("Il verdetto del modello");
    expect(verdict.text()).toContain(
      "Il codice si allontana dai requisiti o dal design approvati: va cambiato il codice.",
    );
    expect(spoken(verdict.get('[data-testid="development-code-tasks"]'))).toContain(
      "Compiti proposti per il codice",
    );
    expect(wrapper.get('[data-testid="development-refresh"]').text()).toBe("Rileggi");
    wrapper.unmount();
  });

  it.each([
    [
      "en",
      "No commit recorded yet. Record the first one with ut verify or ut watch.",
      "No commit aligned yet",
    ],
    [
      "it",
      "Nessun commit registrato. Registra il primo con ut verify o ut watch.",
      "Nessun commit ancora allineato",
    ],
  ] as const)("says in %s that no commit is recorded yet", async (locale, empty, aligned) => {
    const api = developmentApi({
      alignment: vi.fn<CodeChangesApi["alignment"]>(async () => EMPTY),
      changes: vi.fn<CodeChangesApi["changes"]>(async () => changes()),
      tasks: vi.fn<CodeChangesApi["tasks"]>(async () => ({ items: [] })),
    });
    const wrapper = mountPanel(api, locale);
    await flushPromises();

    const sentence = wrapper.get('[data-testid="development-empty"]');
    expect(spoken(sentence)).toBe(empty);
    expect(sentence.findAll("code").map((item) => item.text())).toEqual(["ut verify", "ut watch"]);
    expect(wrapper.get('[data-testid="development-aligned"]').text()).toBe(aligned);
    expect(wrapper.find('[data-testid="development-pending"]').exists()).toBe(false);
    expect(wrapper.find('[data-testid="development-tasks"]').exists()).toBe(false);
    expect(wrapper.find('[data-testid="development-run"]').exists()).toBe(false);
    expect(api.reviews).not.toHaveBeenCalled();
    wrapper.unmount();
  });

  it.each([
    ["en", "On this Studio the twins cannot review the code: connect a model."],
    ["it", "In questo Studio i twin non possono rivedere il codice: collega un modello."],
  ] as const)(
    "says in %s when the Studio has no model to review the code",
    async (locale, text) => {
      const wrapper = mountPanel(
        developmentApi({ alignment: async () => ({ ...ALIGNMENT, review_available: false }) }),
        locale,
      );
      await flushPromises();

      expect(wrapper.get('[data-testid="development-no-model"]').text()).toBe(text);
      expect(wrapper.findAll('[data-testid="development-change"]')).toHaveLength(2);
      wrapper.unmount();
    },
  );

  it("says when the requirements or the design are not approved", async () => {
    const api = developmentApi({
      alignment: async () => ({ ...EMPTY, reference: { requirements: null, design: null } }),
      changes: async () => changes(),
    });
    const english = mountPanel(api);
    await flushPromises();
    expect(english.get('[data-testid="development-reference-requirements"]').text()).toBe(
      "not approved yet",
    );
    expect(english.get('[data-testid="development-reference-design"]').text()).toBe(
      "not approved yet",
    );
    english.unmount();

    setActivePinia(createPinia());
    const italian = mountPanel(api, "it");
    await flushPromises();
    expect(italian.get('[data-testid="development-reference-requirements"]').text()).toBe(
      "non ancora approvati",
    );
    expect(italian.get('[data-testid="development-reference-design"]').text()).toBe(
      "non ancora approvato",
    );
    italian.unmount();
  });

  it("shows the code of the alternative alone when the design of the page is not loaded", async () => {
    useDesignStore().$patch({ projectId: "another-project" });
    const wrapper = mountPanel(developmentApi());
    await flushPromises();

    expect(spoken(wrapper.get('[data-testid="development-reference-design"]'))).toBe(
      "version 2 · DES-001",
    );
    expect(
      wrapper
        .get('[data-testid="development-task"]')
        .findAll('[data-testid="development-subject"]')
        .map(spoken),
    ).toEqual(["REQ-003 · Guests are checked in quickly", "SCR-001"]);
    wrapper.unmount();
  });

  it("says that no commit has been reviewed yet without asking for a run", async () => {
    const api = developmentApi({
      changes: vi.fn(async () => changes(SECOND, { ...ALIGNED, review: null })),
    });
    const wrapper = mountPanel(api);
    await flushPromises();

    const run = wrapper.get('[data-testid="development-run"]');
    expect(run.get("h3").text()).toBe("Latest review");
    expect(run.get('[data-testid="development-no-run"]').text()).toBe(
      "No commit has been reviewed yet.",
    );
    expect(wrapper.findAll('[data-testid="development-change"]')).toHaveLength(1);
    expect(api.reviews).not.toHaveBeenCalled();
    wrapper.unmount();
  });

  it("reads the whole section again with the control and announces the region politely", async () => {
    const newer: CodeChangePayload = {
      ...SECOND,
      commit: "d0d0d0d1d0d0d0d0d0d0d0d0d0d0d0d0d0d0d0d0",
      message: "Add the waiting list",
      review: null,
      decision: null,
    };
    let release: (value: AlignmentPayload) => void = () => undefined;
    const later = new Promise<AlignmentPayload>((resolve) => {
      release = resolve;
    });
    const alignment = vi
      .fn<CodeChangesApi["alignment"]>()
      .mockResolvedValueOnce(ALIGNMENT)
      .mockImplementationOnce(() => later);
    const reads = vi
      .fn<CodeChangesApi["changes"]>()
      .mockResolvedValueOnce(changes(NEWEST, SECOND, ALIGNED))
      .mockResolvedValueOnce(changes(newer, NEWEST, SECOND, ALIGNED));
    const api = developmentApi({ alignment, changes: reads });
    const learning = learningApi(async () => LEARNING);
    const jobs = jobsApi();
    const wrapper = mountPanel(api, "en", { learning, jobs });
    await flushPromises();

    const region = wrapper.get('[data-testid="development-state"]');
    expect(region.attributes("aria-live")).toBe("polite");
    expect(region.attributes("aria-busy")).toBeUndefined();
    expect(wrapper.findAll('[data-testid="development-change"]')).toHaveLength(2);

    await wrapper.get('[data-testid="development-refresh"]').trigger("click");

    expect(wrapper.get('[data-testid="development-refresh"]').attributes("disabled")).toBeDefined();
    expect(wrapper.get('[data-testid="development-state"]').attributes("aria-busy")).toBe("true");
    expect(wrapper.findAll('[data-testid="development-change"]')).toHaveLength(2);
    expect(wrapper.find('[data-testid="learning-block"]').exists()).toBe(true);

    release({ ...ALIGNMENT, pending_changes: 3, latest_change: newer });
    await flushPromises();

    expect(alignment).toHaveBeenCalledTimes(2);
    expect(reads).toHaveBeenCalledTimes(2);
    expect(api.tasks).toHaveBeenCalledTimes(2);
    expect(api.reviews).toHaveBeenCalledTimes(2);
    expect(learning.overview).toHaveBeenCalledTimes(2);
    expect(jobs.list).toHaveBeenCalledTimes(2);
    expect(wrapper.get('[data-testid="development-pending"] h3').text()).toBe(
      "Pending commits (3)",
    );
    expect(wrapper.get('[data-testid="development-change-title"]').text()).toBe(
      "Add the waiting list",
    );
    expect(
      wrapper.get('[data-testid="development-refresh"]').attributes("disabled"),
    ).toBeUndefined();
    wrapper.unmount();
  });

  it("says that it is loading until the Studio answers", async () => {
    const wrapper = mountPanel(
      developmentApi({ alignment: vi.fn(() => new Promise<never>(() => undefined)) }),
      "it",
    );
    await flushPromises();

    expect(wrapper.get('[data-testid="development-loading"]').text()).toBe(
      "Carico lo stato dello sviluppo…",
    );
    expect(wrapper.get('[data-testid="development-state"]').attributes("aria-busy")).toBe("true");
    expect(wrapper.get('[data-testid="development-refresh"]').attributes("disabled")).toBeDefined();
    expect(wrapper.find('[data-testid="development-technical-details"]').exists()).toBe(false);
    wrapper.unmount();
  });

  it("says that the latest run is loading while the Studio reads it", async () => {
    const wrapper = mountPanel(
      developmentApi({
        reviews: vi.fn(() => new Promise<ChangeReviewListPayload>(() => undefined)),
      }),
    );
    await flushPromises();

    expect(wrapper.get('[data-testid="development-run-loading"]').text()).toBe(
      "Loading the latest review…",
    );
    expect(wrapper.findAll('[data-testid="development-change"]')).toHaveLength(2);
    wrapper.unmount();
  });

  it("says when the Studio lists no run for a reviewed commit", async () => {
    const wrapper = mountPanel(developmentApi({ reviews: async () => ({ items: [] }) }));
    await flushPromises();

    expect(wrapper.get('[data-testid="development-run-loading"]').text()).toBe(
      "The latest review is not available.",
    );
    wrapper.unmount();
  });

  it("explains a failed read and recovers with the control that reads again", async () => {
    let fail = true;
    const api = developmentApi({
      alignment: vi.fn(async () => {
        if (fail) {
          throw new CodeChangesApiError("The code change request failed", {
            status: 404,
            code: "PROJECT_NOT_FOUND",
            payload: null,
          });
        }
        return ALIGNMENT;
      }),
    });
    const wrapper = mountPanel(api);
    await flushPromises();

    const error = wrapper.get('[data-testid="development-error"]');
    expect(error.attributes("role")).toBe("alert");
    expect(error.get("p").text()).toBe("The development state could not be loaded.");
    expect(error.get("code").text()).toBe("PROJECT_NOT_FOUND");
    expect(wrapper.find('[data-testid="development-loading"]').exists()).toBe(false);
    expect(wrapper.find('[data-testid="development-reference"]').exists()).toBe(false);

    fail = false;
    await wrapper.get('[data-testid="development-refresh"]').trigger("click");
    await flushPromises();

    expect(wrapper.find('[data-testid="development-error"]').exists()).toBe(false);
    expect(wrapper.findAll('[data-testid="development-change"]')).toHaveLength(2);
    wrapper.unmount();
  });

  it("explains a latest run that cannot be read and keeps the rest of the state", async () => {
    const wrapper = mountPanel(
      developmentApi({
        reviews: async () => {
          throw new CodeChangesApiError("The code change request failed", {
            status: 409,
            code: "CODE_CHANGE_AMBIGUOUS",
            payload: null,
          });
        },
      }),
      "it",
    );
    await flushPromises();

    const error = wrapper.get('[data-testid="development-run-error"]');
    expect(error.attributes("role")).toBe("alert");
    expect(error.get("p").text()).toBe("Non è stato possibile caricare l'ultima revisione.");
    expect(error.get("code").text()).toBe("CODE_CHANGE_AMBIGUOUS");
    expect(wrapper.findAll('[data-testid="development-change"]')).toHaveLength(2);
    expect(wrapper.findAll('[data-testid="development-task"]')).toHaveLength(1);
    wrapper.unmount();
  });

  it("puts the counts and the latest run in its own row of technical details", async () => {
    const wrapper = mountPanel(developmentApi());
    await flushPromises();

    const details = wrapper.get('[data-testid="development-technical-details"]');
    expect(wrapper.find('[data-testid="step-technical-details"]').exists()).toBe(false);
    await details.get('[data-testid="step-technical-details-toggle"]').trigger("click");

    const content = details.get('[data-testid="step-technical-details-content"]');
    expect(content.findAll("dt").map((item) => item.text())).toEqual([
      "Recorded commits",
      "Pending commits",
      "Open tasks",
      "Latest review",
    ]);
    expect(content.findAll("dd").map((item) => item.text())).toEqual(["3", "2", "1", RUN_ID]);
    wrapper.unmount();
  });

  it("reads the state of the new project when the project changes", async () => {
    const api = developmentApi();
    const learning = learningApi();
    const jobs = jobsApi();
    const wrapper = mountPanel(api, "en", { learning, jobs });
    await flushPromises();

    await wrapper.setProps({ projectId: SECOND_PROJECT_ID });
    await flushPromises();

    expect(api.alignment).toHaveBeenLastCalledWith(SECOND_PROJECT_ID, TOKEN);
    expect(api.changes).toHaveBeenLastCalledWith(SECOND_PROJECT_ID, TOKEN);
    expect(api.tasks).toHaveBeenLastCalledWith(SECOND_PROJECT_ID, TOKEN, "all");
    expect(api.reviews).toHaveBeenLastCalledWith(SECOND_PROJECT_ID, NEWEST_COMMIT, TOKEN);
    expect(learning.overview).toHaveBeenLastCalledWith(SECOND_PROJECT_ID, TOKEN);
    expect(jobs.list).toHaveBeenLastCalledWith(SECOND_PROJECT_ID, TOKEN, "RUNNING");
    expect(spoken(wrapper.get('[data-testid="development-reference-design"]'))).toBe(
      "version 2 · DES-001",
    );
    wrapper.unmount();
  });

  it("announces a review of a commit started from the terminal and reads the section again when it ends", async () => {
    vi.useFakeTimers();
    const api = developmentApi();
    const learning = learningApi(async () => LEARNING);
    const jobs = jobsApi(
      [generation("CODE_CHANGE_REVIEW")],
      [generation("CODE_CHANGE_REVIEW"), finished("CODE_CHANGE_REVIEW")],
    );
    const wrapper = mountPanel(api, "en", { learning, jobs });
    await vi.advanceTimersByTimeAsync(50);

    const notice = wrapper.get(
      '[data-testid="development-job"] [data-testid="generation-job-notice"]',
    );
    expect(notice.attributes("data-operation")).toBe("CODE_CHANGE_REVIEW");
    expect(notice.get('[role="status"]').text()).toBe(
      "The Studio is generating the twins' review of a commit.",
    );
    expect(wrapper.findAll("button").map((button) => button.attributes("data-testid"))).toEqual([
      "development-refresh",
      "step-technical-details-toggle",
    ]);
    expect(api.alignment).toHaveBeenCalledTimes(1);

    await vi.advanceTimersByTimeAsync(2000);
    expect(wrapper.find('[data-testid="development-job"]').exists()).toBe(true);
    expect(api.alignment).toHaveBeenCalledTimes(1);

    await vi.advanceTimersByTimeAsync(2050);

    expect(wrapper.find('[data-testid="development-job"]').exists()).toBe(false);
    expect(api.alignment).toHaveBeenCalledTimes(2);
    expect(api.changes).toHaveBeenCalledTimes(2);
    expect(api.tasks).toHaveBeenCalledTimes(2);
    expect(api.reviews).toHaveBeenCalledTimes(2);
    expect(learning.overview).toHaveBeenCalledTimes(2);
    expect(wrapper.find('[data-testid="generation-job-failure"]').exists()).toBe(false);
    wrapper.unmount();
  });

  it("announces in Italian what a twin is learning and reads the section again when the job is lost", async () => {
    vi.useFakeTimers();
    const api = developmentApi();
    const learning = learningApi(async () => LEARNING);
    const jobs = jobsApi([generation("TWIN_UPDATE")], []);
    jobs.job.mockRejectedValueOnce(
      new GenerationJobsApiError("GENERATION_JOB_NOT_FOUND", {
        status: 404,
        code: "GENERATION_JOB_NOT_FOUND",
        payload: null,
      }),
    );
    const wrapper = mountPanel(api, "it", { learning, jobs });
    await vi.advanceTimersByTimeAsync(50);

    expect(wrapper.get('[data-testid="development-job"] [role="status"]').text()).toBe(
      "Lo Studio sta generando la proposta di ciò che un twin ha imparato.",
    );

    await vi.advanceTimersByTimeAsync(2050);

    expect(wrapper.find('[data-testid="development-job"]').exists()).toBe(false);
    expect(wrapper.find('[data-testid="generation-job-failure"]').exists()).toBe(false);
    expect(learning.overview).toHaveBeenCalledTimes(2);
    expect(api.alignment).toHaveBeenCalledTimes(2);
    wrapper.unmount();
  });

  it("finds with the control a job started from the terminal after the page opened", async () => {
    vi.useFakeTimers();
    const api = developmentApi();
    const jobs = jobsApi([], [finished("TWIN_UPDATE")]);
    const wrapper = mountPanel(api, "en", { jobs });
    await vi.advanceTimersByTimeAsync(50);
    expect(wrapper.find('[data-testid="development-job"]').exists()).toBe(false);

    jobs.list.mockResolvedValueOnce([generation("TWIN_UPDATE")]);
    await wrapper.get('[data-testid="development-refresh"]').trigger("click");
    await vi.advanceTimersByTimeAsync(50);

    expect(jobs.list).toHaveBeenCalledTimes(2);
    expect(
      wrapper
        .get('[data-testid="development-job"] [data-testid="generation-job-notice"]')
        .attributes("data-operation"),
    ).toBe("TWIN_UPDATE");
    expect(api.alignment).toHaveBeenCalledTimes(2);

    await vi.advanceTimersByTimeAsync(2000);

    expect(wrapper.find('[data-testid="development-job"]').exists()).toBe(false);
    expect(api.alignment).toHaveBeenCalledTimes(3);
    wrapper.unmount();
  });

  it("announces an alignment of the knowledge started from the terminal and shows its run when it ends", async () => {
    vi.useFakeTimers();
    const alignment = alignmentApi();
    const jobs = jobsApi([generation("KNOWLEDGE_ALIGNMENT")], [finished("KNOWLEDGE_ALIGNMENT")]);
    const wrapper = mountPanel(developmentApi(), "en", { jobs, alignment });
    await vi.advanceTimersByTimeAsync(50);

    const notice = wrapper.get(
      '[data-testid="development-job"] [data-testid="generation-job-notice"]',
    );
    expect(notice.attributes("data-operation")).toBe("KNOWLEDGE_ALIGNMENT");
    expect(notice.get('[role="status"]').text()).toBe(
      "The Studio is generating the alignment of the knowledge to the code.",
    );
    expect(wrapper.find('[data-testid="development-knowledge-none"]').exists()).toBe(true);

    alignment.runs.mockResolvedValueOnce({ items: [KNOWLEDGE_RUN] });
    await vi.advanceTimersByTimeAsync(2050);

    expect(wrapper.find('[data-testid="development-job"]').exists()).toBe(false);
    expect(alignment.runs).toHaveBeenCalledTimes(2);
    expect(wrapper.get('[data-testid="development-knowledge-waiting"]').text()).toBe("1");
    wrapper.unmount();
  });

  it("reads the whole section again every 20 seconds while the page is visible", async () => {
    vi.useFakeTimers();
    const api = developmentApi();
    const learning = learningApi(async () => LEARNING);
    const jobs = jobsApi();
    const alignment = alignmentApi();
    const wrapper = mountPanel(api, "en", { learning, jobs, alignment });
    await vi.advanceTimersByTimeAsync(50);

    expect(api.alignment).toHaveBeenCalledTimes(1);
    expect(alignment.runs).toHaveBeenCalledTimes(1);
    expect(jobs.list).toHaveBeenCalledTimes(1);

    await vi.advanceTimersByTimeAsync(19900);

    expect(api.alignment).toHaveBeenCalledTimes(1);

    await vi.advanceTimersByTimeAsync(100);

    expect(api.alignment).toHaveBeenCalledTimes(2);
    expect(api.changes).toHaveBeenCalledTimes(2);
    expect(api.tasks).toHaveBeenCalledTimes(2);
    expect(api.reviews).toHaveBeenCalledTimes(2);
    expect(learning.overview).toHaveBeenCalledTimes(2);
    expect(alignment.runs).toHaveBeenCalledTimes(2);
    expect(jobs.list).toHaveBeenCalledTimes(2);

    await vi.advanceTimersByTimeAsync(20000);

    expect(api.alignment).toHaveBeenCalledTimes(3);
    expect(alignment.runs).toHaveBeenCalledTimes(3);
    expect(jobs.list).toHaveBeenCalledTimes(3);
    wrapper.unmount();
  });

  it("reads nothing while the page is hidden and reads the section again when the page comes back", async () => {
    vi.useFakeTimers();
    const visibility = vi.spyOn(document, "visibilityState", "get").mockReturnValue("hidden");
    const api = developmentApi();
    const jobs = jobsApi();
    const alignment = alignmentApi();
    const wrapper = mountPanel(api, "en", { jobs, alignment });
    await vi.advanceTimersByTimeAsync(60050);
    document.dispatchEvent(new Event("visibilitychange"));
    await vi.advanceTimersByTimeAsync(50);

    expect(api.alignment).toHaveBeenCalledTimes(1);
    expect(api.changes).toHaveBeenCalledTimes(1);
    expect(alignment.runs).toHaveBeenCalledTimes(1);
    expect(jobs.list).toHaveBeenCalledTimes(1);

    visibility.mockReturnValue("visible");
    document.dispatchEvent(new Event("visibilitychange"));
    await vi.advanceTimersByTimeAsync(50);

    expect(api.alignment).toHaveBeenCalledTimes(2);
    expect(alignment.runs).toHaveBeenCalledTimes(2);
    expect(jobs.list).toHaveBeenCalledTimes(2);
    wrapper.unmount();
  });

  it("skips a timed reading while the previous one still waits for the Studio", async () => {
    vi.useFakeTimers();
    const alignment = vi
      .fn<CodeChangesApi["alignment"]>()
      .mockResolvedValueOnce(ALIGNMENT)
      .mockImplementationOnce(() => new Promise<never>(() => undefined));
    const wrapper = mountPanel(developmentApi({ alignment }));
    await vi.advanceTimersByTimeAsync(20050);

    expect(alignment).toHaveBeenCalledTimes(2);
    expect(wrapper.get('[data-testid="development-refresh"]').attributes("disabled")).toBeDefined();

    await vi.advanceTimersByTimeAsync(40000);

    expect(alignment).toHaveBeenCalledTimes(2);
    wrapper.unmount();
  });

  it("stops reading the section again once it is closed", async () => {
    vi.useFakeTimers();
    const api = developmentApi();
    const jobs = jobsApi();
    const alignment = alignmentApi();
    const wrapper = mountPanel(api, "en", { jobs, alignment });
    await vi.advanceTimersByTimeAsync(50);

    wrapper.unmount();
    await vi.advanceTimersByTimeAsync(60000);
    document.dispatchEvent(new Event("visibilitychange"));
    await vi.advanceTimersByTimeAsync(50);

    expect(api.alignment).toHaveBeenCalledTimes(1);
    expect(alignment.runs).toHaveBeenCalledTimes(1);
    expect(jobs.list).toHaveBeenCalledTimes(1);
  });

  it("reads nothing on its own while its step is not shown and reads once as soon as it is shown again", async () => {
    vi.useFakeTimers();
    const api = developmentApi();
    const jobs = jobsApi();
    const alignment = alignmentApi();
    const wrapper = mountPanel(api, "en", { jobs, alignment, active: false });
    await vi.advanceTimersByTimeAsync(60050);
    document.dispatchEvent(new Event("visibilitychange"));
    await vi.advanceTimersByTimeAsync(50);

    expect(api.alignment).toHaveBeenCalledTimes(1);
    expect(alignment.runs).toHaveBeenCalledTimes(1);
    expect(jobs.list).toHaveBeenCalledTimes(1);

    await wrapper.setProps({ active: true });
    await vi.advanceTimersByTimeAsync(50);

    expect(api.alignment).toHaveBeenCalledTimes(2);
    expect(api.changes).toHaveBeenCalledTimes(2);
    expect(api.reviews).toHaveBeenCalledTimes(2);
    expect(alignment.runs).toHaveBeenCalledTimes(2);
    expect(jobs.list).toHaveBeenCalledTimes(2);

    await vi.advanceTimersByTimeAsync(19000);

    expect(api.alignment).toHaveBeenCalledTimes(2);

    await wrapper.setProps({ active: false });
    await vi.advanceTimersByTimeAsync(60000);

    expect(api.alignment).toHaveBeenCalledTimes(2);

    await wrapper.setProps({ active: true });
    await vi.advanceTimersByTimeAsync(50);

    expect(api.alignment).toHaveBeenCalledTimes(3);
    expect(alignment.runs).toHaveBeenCalledTimes(3);
    expect(jobs.list).toHaveBeenCalledTimes(3);
    wrapper.unmount();
  });

  it("waits for the next timed reading when its step is shown right after a reading, as while the project page opens", async () => {
    vi.useFakeTimers();
    const api = developmentApi();
    const wrapper = mountPanel(api, "en", { active: false });
    await vi.advanceTimersByTimeAsync(50);

    await wrapper.setProps({ active: true });
    await vi.advanceTimersByTimeAsync(50);

    expect(api.alignment).toHaveBeenCalledTimes(1);

    await vi.advanceTimersByTimeAsync(19900);

    expect(api.alignment).toHaveBeenCalledTimes(2);
    wrapper.unmount();
  });

  it("keeps the notice of a failed reading in place while the timed readings fail and clears it after one that succeeds", async () => {
    vi.useFakeTimers();
    let fail = true;
    const alignment = vi.fn<CodeChangesApi["alignment"]>(async () => {
      if (fail) {
        throw new TypeError("Failed to fetch");
      }
      return ALIGNMENT;
    });
    const wrapper = mountPanel(developmentApi({ alignment }));
    await vi.advanceTimersByTimeAsync(50);

    const notice = wrapper.get('[data-testid="development-error"]').element;
    const mutations: MutationRecord[] = [];
    const observer = new MutationObserver((records) => mutations.push(...records));
    observer.observe(wrapper.get('[data-testid="development-state"]').element, {
      childList: true,
      subtree: true,
      characterData: true,
    });
    await vi.advanceTimersByTimeAsync(20000);
    await vi.advanceTimersByTimeAsync(20000);
    mutations.push(...observer.takeRecords());
    observer.disconnect();

    expect(alignment).toHaveBeenCalledTimes(3);
    expect(wrapper.get('[data-testid="development-error"]').element).toBe(notice);
    expect(mutations).toEqual([]);
    expect(wrapper.find('[data-testid="development-loading"]').exists()).toBe(false);

    fail = false;
    await vi.advanceTimersByTimeAsync(20000);

    expect(alignment).toHaveBeenCalledTimes(4);
    expect(wrapper.find('[data-testid="development-error"]').exists()).toBe(false);
    expect(wrapper.findAll('[data-testid="development-change"]')).toHaveLength(2);
    wrapper.unmount();
  });

  it("still takes the notice away at once when the owner asks to read again with the control", async () => {
    const alignment = vi
      .fn<CodeChangesApi["alignment"]>()
      .mockRejectedValueOnce(new TypeError("Failed to fetch"))
      .mockImplementationOnce(() => new Promise<never>(() => undefined));
    const wrapper = mountPanel(developmentApi({ alignment }));
    await flushPromises();
    expect(wrapper.find('[data-testid="development-error"]').exists()).toBe(true);

    await wrapper.get('[data-testid="development-refresh"]').trigger("click");

    expect(alignment).toHaveBeenCalledTimes(2);
    expect(wrapper.find('[data-testid="development-error"]').exists()).toBe(false);
    expect(wrapper.get('[data-testid="development-loading"]').text()).toBe(
      "Loading the development state…",
    );
    wrapper.unmount();
  });

  it.each([
    [
      "en",
      {
        title: "Knowledge alignment",
        labels: ["Commits", "Date", "Proposals", "Waiting for a decision"],
        commits: "from a1a1a1a to c0ffee1",
        terminal:
          "Proposals are made from the terminal with ut align; you decide them here and in the sections. In the other direction, ut align --from-design brings the code up to a design that changed after the code was written.",
        push: "The hand-made changes of the knowledge folder go back to the Studio from the terminal with ut push: you approve the differences and a new version is born.",
      },
    ],
    [
      "it",
      {
        title: "Allineamento della conoscenza",
        labels: ["Commit", "Data", "Proposte", "In attesa di decisione"],
        commits: "da a1a1a1a a c0ffee1",
        terminal:
          "Le proposte si fanno dal terminale con ut align; qui e nelle sezioni le decidi. Nella direzione contraria, ut align --from-design porta il codice a un design cambiato dopo che il codice è stato scritto.",
        push: "Le modifiche fatte a mano nella cartella di conoscenza tornano nello Studio dal terminale con ut push: approvi le differenze e nasce una versione nuova.",
      },
    ],
  ] as const)(
    "shows in %s the latest alignment of the knowledge with the code after the latest review",
    async (locale, expected) => {
      const alignment = alignmentApi([EARLIER_KNOWLEDGE_RUN, KNOWLEDGE_RUN]);
      const wrapper = mountPanel(developmentApi(), locale, { alignment });
      await flushPromises();

      expect(alignment.runs).toHaveBeenCalledTimes(1);
      expect(alignment.runs).toHaveBeenCalledWith(PROJECT_ID, TOKEN);
      const block = wrapper.get('[data-testid="development-knowledge"]');
      expect(block.get("h3").text()).toBe(expected.title);
      expect(block.get('[data-testid="development-knowledge-summary"]').text()).toBe(
        KNOWLEDGE_RUN.summary,
      );
      const run = block.get('[data-testid="development-knowledge-run"]');
      expect(run.findAll("dt").map((item) => item.text())).toEqual(expected.labels);
      expect(spoken(block.get('[data-testid="development-knowledge-commits"]'))).toBe(
        expected.commits,
      );
      expect(spoken(block.get('[data-testid="development-knowledge-date"]'))).toBe(
        words(dated(KNOWLEDGE_RUN.created_at, locale)),
      );
      expect(block.get('[data-testid="development-knowledge-proposals"]').text()).toBe("3");
      expect(block.get('[data-testid="development-knowledge-waiting"]').text()).toBe("1");
      expect(block.find('[data-testid="development-knowledge-none"]').exists()).toBe(false);
      const terminal = block.get('[data-testid="development-knowledge-terminal"]');
      expect(spoken(terminal)).toBe(expected.terminal);
      expect(terminal.findAll("code").map((item) => item.text())).toEqual([
        "ut align",
        "ut align --from-design",
      ]);
      const push = block.get('[data-testid="development-knowledge-push"]');
      expect(spoken(push)).toBe(expected.push);
      expect(push.findAll("code").map((item) => item.text())).toEqual(["ut push"]);
      expect(terminal.element.nextElementSibling).toBe(push.element);
      const review = wrapper.get('[data-testid="development-run"]').element;
      expect(review.compareDocumentPosition(block.element) & Node.DOCUMENT_POSITION_FOLLOWING).toBe(
        Node.DOCUMENT_POSITION_FOLLOWING,
      );
      expect(wrapper.findAll("button").map((button) => button.attributes("data-testid"))).toEqual([
        "development-refresh",
        "step-technical-details-toggle",
      ]);
      await expectAccessible(wrapper.element);
      wrapper.unmount();
    },
  );

  it.each([
    ["en", "up to a1a1a1a"],
    ["it", "fino a a1a1a1a"],
  ] as const)(
    "says in %s up to which commit a first run read the code",
    async (locale, commits) => {
      const wrapper = mountPanel(developmentApi(), locale, {
        alignment: alignmentApi([EARLIER_KNOWLEDGE_RUN]),
      });
      await flushPromises();

      const block = wrapper.get('[data-testid="development-knowledge"]');
      expect(spoken(block.get('[data-testid="development-knowledge-commits"]'))).toBe(commits);
      expect(block.get('[data-testid="development-knowledge-proposals"]').text()).toBe("0");
      expect(block.get('[data-testid="development-knowledge-waiting"]').text()).toBe("0");
      wrapper.unmount();
    },
  );

  it.each([
    ["en", "The knowledge has not been compared with the code yet."],
    ["it", "La conoscenza non è ancora stata confrontata con il codice."],
  ] as const)(
    "says in %s that the knowledge was never compared with the code and still names ut align and ut push",
    async (locale, sentence) => {
      const wrapper = mountPanel(developmentApi(), locale);
      await flushPromises();

      const block = wrapper.get('[data-testid="development-knowledge"]');
      expect(block.get('[data-testid="development-knowledge-none"]').text()).toBe(sentence);
      expect(block.find('[data-testid="development-knowledge-run"]').exists()).toBe(false);
      expect(block.get('[data-testid="development-knowledge-terminal"] code').text()).toBe(
        "ut align",
      );
      expect(block.get('[data-testid="development-knowledge-push"] code').text()).toBe("ut push");
      wrapper.unmount();
    },
  );

  it("keeps the rest of the section when the runs of the alignment cannot be read", async () => {
    const alignment = alignmentApi();
    alignment.runs.mockRejectedValue(new TypeError("Failed to fetch"));
    const wrapper = mountPanel(developmentApi(), "en", { alignment });
    await flushPromises();

    expect(wrapper.findAll('[data-testid="development-change"]')).toHaveLength(2);
    expect(wrapper.find('[data-testid="development-knowledge-none"]').exists()).toBe(true);
    expect(wrapper.find('[data-testid="development-error"]').exists()).toBe(false);
    wrapper.unmount();
  });

  it("reads the runs of the alignment again with the control and for another project", async () => {
    const alignment = alignmentApi([KNOWLEDGE_RUN]);
    const wrapper = mountPanel(developmentApi(), "en", { alignment });
    await flushPromises();
    expect(alignment.runs).toHaveBeenCalledTimes(1);

    alignment.runs.mockResolvedValueOnce({ items: [{ ...KNOWLEDGE_RUN, waiting: 0 }] });
    await wrapper.get('[data-testid="development-refresh"]').trigger("click");
    await flushPromises();

    expect(alignment.runs).toHaveBeenCalledTimes(2);
    expect(wrapper.get('[data-testid="development-knowledge-waiting"]').text()).toBe("0");

    alignment.runs.mockResolvedValueOnce({ items: [] });
    await wrapper.setProps({ projectId: SECOND_PROJECT_ID });
    await flushPromises();

    expect(alignment.runs).toHaveBeenLastCalledWith(SECOND_PROJECT_ID, TOKEN);
    expect(wrapper.find('[data-testid="development-knowledge-none"]').exists()).toBe(true);
    wrapper.unmount();
  });

  it("has no axe violations with a full development state", async () => {
    const wrapper = mountPanel(developmentApi(), "it");
    await flushPromises();

    await expectAccessible(wrapper.element);
    wrapper.unmount();
  });

  it("has no axe violations with origins, stale reviews, closed tasks and what the twins learned", async () => {
    const every = [TWIN_TASK, VERDICT_TASK, TEST_TASK, OWNER_TASK];
    const wrapper = mountPanel(
      developmentApi({
        alignment: async () => ({ ...ALIGNMENT, stale_reviews: 1, tasks: every }),
        changes: async () => changes(STALE_NEWEST, FRESH_SECOND, ALIGNED),
        tasks: async () => ({ items: [...every, task("TSK-009", {}, "DONE")] }),
      }),
      "en",
      { learning: learningApi(async () => LEARNING) },
    );
    await flushPromises();

    await expectAccessible(wrapper.element);
    wrapper.unmount();
  });

  it("has no axe violations while a job started from the terminal runs", async () => {
    vi.useFakeTimers();
    const wrapper = mountPanel(developmentApi(), "en", {
      jobs: jobsApi([generation("CODE_CHANGE_REVIEW")], []),
    });
    await vi.advanceTimersByTimeAsync(50);
    expect(wrapper.find('[data-testid="development-job"]').exists()).toBe(true);
    vi.useRealTimers();

    await expectAccessible(wrapper.element);
    wrapper.unmount();
  });

  it("has no axe violations without commits and without a model", async () => {
    const wrapper = mountPanel(
      developmentApi({
        alignment: async () => ({ ...EMPTY, review_available: false }),
        changes: async () => changes(),
      }),
    );
    await flushPromises();

    await expectAccessible(wrapper.element);
    wrapper.unmount();
  });
});
