"use strict";

const fs = require("node:fs");
const os = require("node:os");
const path = require("node:path");

const PROJECT_ID = "5d6a1c2e-4b1f-4a55-9c7e-2f8e7a9b0c11";
const HEAD_WAITER = "2f2304d5-fb8c-4a95-bcbb-7799648ed4a1";
const SEASONAL = "504aa796-518c-4338-816b-56b1426375dd";
const ALIGNED_COMMIT = "1a1b1c1d1e1f1a1b1c1d1e1f1a1b1c1d1e1f1a1b";
const CLEAN_COMMIT = "2b2c2d2e2f2a2b2c2d2e2f2a2b2c2d2e2f2a2b2c";
const DRIFT_COMMIT = "3c3d3e3f3a3b3c3d3e3f3a3b3c3d3e3f3a3b3c3d";
const LATEST_RUN = "96c07236-9dcf-4fca-8e64-09eb460e42f0";
const EARLIER_RUN = "5f84633f-5646-4b32-b2a3-619f8c0bcb2b";
const RUN_FOLDER = "20260930-090400";
const DESIGN_POINT = ".orchestwin/code/design.json";
const STATEMENTS = Object.freeze({
  "AC-001":
    "With a bill of 50 and a tip of 10 percent, the result shows a tip of 5.00 and a total of 55.00.",
  "AC-002": "The tip is rounded to the cent, half up, and both amounts always show two decimals.",
  "AC-003":
    "With an empty bill, the page shows the message Enter the bill next to the field and no result.",
  "AC-004":
    "After New calculation the bill is empty and the percentage chosen before stays selected.",
  "AC-005": "The three buttons 5, 10 and 15 percent are reachable with the keyboard in this order.",
  "AC-006":
    "A waiter who never saw the page understands it without instructions within one minute.",
});

function makeTemporaryFolder() {
  return fs.mkdtempSync(path.join(os.tmpdir(), "orchestwin-panel-"));
}

function removeFolder(folder) {
  fs.rmSync(folder, { recursive: true, force: true });
}

function writeText(root, relative, content) {
  const file = path.join(root, ...relative.split("/"));
  fs.mkdirSync(path.dirname(file), { recursive: true });
  fs.writeFileSync(file, content, "utf8");
  return file;
}

function writeJson(root, relative, value) {
  return writeText(root, relative, `${JSON.stringify(value, null, 2)}\n`);
}

function readJson(root, relative) {
  return JSON.parse(fs.readFileSync(path.join(root, ...relative.split("/")), "utf8"));
}

function link(name) {
  return {
    schema_version: 1,
    studio: "http://127.0.0.1:8000",
    api_prefix: "/api/v1",
    project_id: PROJECT_ID,
    project_name: name,
    mode: "DESIGN_ONLY",
    language: "en",
    created_at: "2026-09-29T12:09:15+00:00",
    knowledge_folder: "orchestwin",
  };
}

function stageEntry(document, number) {
  return { document, version_number: number, gate: { status: "APPROVED" } };
}

function manifest(approved, shape) {
  const stages = {
    brief: stageEntry("brief/brief.json", 3),
    team: stageEntry("team/team.json", 1),
    twins: stageEntry("twins/twins.json", 1),
    requirements: stageEntry("requirements/requirements.json", 1),
    design: stageEntry("design/design.json", 5),
  };
  const document = {
    schema_version: 3,
    kind: "orchestwin.knowledge-folder",
    project: { id: PROJECT_ID, name: "Tip calculator for waiters", language: "en" },
    package: { version_number: 12, created_at: "2026-09-30T09:12:00+00:00" },
    progress: {
      approved,
      pending:
        ["brief", "team", "twins", "requirements", "design"].find(
          (stage) => !approved.includes(stage),
        ) ?? null,
      complete: approved.length === 5,
    },
    stages: Object.fromEntries(approved.map((stage) => [stage, stages[stage]])),
    state: {
      document: "state/state.json",
      text: "state/state.md",
      changes: approved.includes("design") ? 3 : 0,
      pending_changes: approved.includes("design") ? 2 : 0,
      aligned_commit: approved.includes("design") ? ALIGNED_COMMIT : null,
      open_tasks: approved.includes("design") ? 3 : 0,
    },
    feedback: {
      folder: "twins/feedback",
      changes: "twins/feedback/changes.json",
      tests: "twins/feedback/tests.json",
      test_runs: approved.includes("design") ? 2 : 0,
    },
    twins: approved.includes("twins")
      ? [
          { twin_id: HEAD_WAITER, name: "Head waiter", version_number: 1 },
          { twin_id: SEASONAL, name: "Seasonal waiters", version_number: 1 },
        ]
      : [],
  };
  if (shape === "new") {
    document.state.stale_reviews = approved.includes("design") ? 1 : 0;
    if (approved.includes("twins")) {
      document.feedback.learned = "twins/feedback/learned.json";
      document.feedback.learned_observations = 4;
    }
  }
  return document;
}

function reference(design) {
  return {
    requirements_version_number: 1,
    design_version_number: design,
    alternative_code: "DES-002",
  };
}

function review(runId, verdict, design, stale, shape) {
  const found = {
    run_id: runId,
    reviewed_at: "2026-09-30T08:52:10+00:00",
    verdict,
    summary: "Summary of the review.",
  };
  if (shape === "new") {
    found.reference = reference(design);
    found.stale = stale;
  }
  return found;
}

function change(commit, message, committedAt, reviewed, decision) {
  return {
    commit,
    parent: null,
    committed_at: committedAt,
    author: "Alex Testa",
    message,
    files: [{ path: "app.js", kind: "MODIFIED", added: 12, removed: 3 }],
    recorded_at: committedAt,
    review: reviewed,
    decision,
  };
}

function newTask(code, text, origin, status, criteria = []) {
  return {
    code,
    text,
    about: { requirements: ["REQ-001"], screens: ["SCR-002"], criteria },
    origin,
    from_commit: origin.commit,
    created_at: "2026-09-30T08:55:00+00:00",
    status,
    closed_at: status === "OPEN" ? null : "2026-09-30T09:00:00+00:00",
    note: status === "DROPPED" ? "No longer wanted." : null,
  };
}

function oldTask(code, text, commit, status) {
  return {
    code,
    text,
    about: { requirements: ["REQ-001"], screens: ["SCR-002"] },
    from_commit: commit,
    created_at: "2026-09-29T16:48:37+00:00",
    status,
  };
}

function origin(kind, values = {}) {
  return {
    kind,
    commit: values.commit ?? null,
    test_run_id: values.testRunId ?? null,
    twin_id: values.twinId ?? null,
    twin_name: values.twinName ?? null,
    finding: values.finding ?? null,
  };
}

function tasks(shape) {
  if (shape === "old") {
    return [
      oldTask(
        "TSK-001",
        "Show every amount with two decimals and the comma.",
        ALIGNED_COMMIT,
        "DONE",
      ),
      oldTask(
        "TSK-002",
        "Keep the chosen percentage selected after New calculation, as in the approved design.",
        CLEAN_COMMIT,
        "OPEN",
      ),
      oldTask(
        "TSK-003",
        "Bring back the separate result view with the total in very large digits.",
        DRIFT_COMMIT,
        "OPEN",
      ),
    ];
  }
  return [
    newTask(
      "TSK-001",
      "Show every amount with two decimals and the comma.",
      origin("CODE_CHANGE", { commit: ALIGNED_COMMIT }),
      "DONE",
    ),
    newTask(
      "TSK-002",
      "Keep the chosen percentage selected after New calculation, as in the approved design.",
      origin("CODE_CHANGE", {
        commit: CLEAN_COMMIT,
        twinId: HEAD_WAITER,
        twinName: "Head waiter",
        finding: "The percentage is lost after New calculation.",
      }),
      "OPEN",
    ),
    newTask(
      "TSK-003",
      "Show the message Enter the bill next to the empty field instead of an empty result.",
      origin("TEST_RUN", {
        testRunId: LATEST_RUN,
        twinId: SEASONAL,
        twinName: "Seasonal waiters",
        finding: "With an empty bill the page shows an empty result.",
      }),
      "OPEN",
      ["AC-003"],
    ),
    newTask(
      "TSK-004",
      "Try the page on a 360 pixel phone before the season.",
      origin("OWNER"),
      "OPEN",
    ),
    newTask("TSK-005", "Add a dark theme.", origin("OWNER"), "DROPPED"),
  ];
}

function projectState(shape) {
  return {
    schema_version: 3,
    kind: "orchestwin.project-state",
    project_id: PROJECT_ID,
    reference: {
      requirements: { version_id: "r1", version_number: 1, content_hash: "a".repeat(64) },
      design: {
        version_id: "d5",
        version_number: 5,
        content_hash: "b".repeat(64),
        alternative_code: "DES-002",
      },
    },
    aligned: {
      commit: ALIGNED_COMMIT,
      decided_at: "2026-09-29T16:13:26+00:00",
      requirements_version_number: 1,
      design_version_number: 4,
    },
    changes: [
      change(
        DRIFT_COMMIT,
        "feat: split the bill between the guests\n\nA field Guests divides the total.",
        "2026-09-30T08:40:00+00:00",
        review("run-drift", "CODE_DRIFT", 4, true, shape),
        null,
      ),
      change(
        CLEAN_COMMIT,
        "fix: two decimals and the comma in every amount",
        "2026-09-30T08:20:00+00:00",
        review("run-clean", "ALIGNED", 5, false, shape),
        { kind: "CODE_TASKS", decided_at: "2026-09-30T08:55:00+00:00", note: null },
      ),
      change(
        ALIGNED_COMMIT,
        "feat: fields, checks and the result view",
        "2026-09-29T16:10:19+00:00",
        review("run-aligned", "ALIGNED", 4, true, shape),
        { kind: "ALIGNED", decided_at: "2026-09-29T16:13:26+00:00", note: null },
      ),
    ],
    tasks: tasks(shape),
  };
}

function critique(twinId, twinName, verdict, findings = []) {
  return {
    twin_id: twinId,
    twin_name: twinName,
    verdict,
    summary: "What the twin thinks.",
    findings,
  };
}

function changeRuns() {
  return {
    schema_version: 3,
    kind: "orchestwin.change-reviews",
    project_id: PROJECT_ID,
    runs: [
      {
        id: "run-drift",
        commit: DRIFT_COMMIT,
        reviewed_at: "2026-09-30T08:52:10+00:00",
        locale: "en-US",
        reference: reference(4),
        critiques: [
          critique(HEAD_WAITER, "Head waiter", "DRIFT"),
          critique(SEASONAL, "Seasonal waiters", "CONCERN"),
        ],
        alignment: { status: "CODE_DRIFT", summary: "The code moves away." },
        cost_microusd: 412000,
      },
      {
        id: "run-clean",
        commit: CLEAN_COMMIT,
        reviewed_at: "2026-09-30T08:30:00+00:00",
        locale: "en-US",
        reference: reference(5),
        critiques: [
          critique(HEAD_WAITER, "Head waiter", "FINE"),
          critique(SEASONAL, "Seasonal waiters", "FINE"),
        ],
        alignment: { status: "ALIGNED", summary: "In line." },
        cost_microusd: 398000,
      },
    ],
  };
}

function criteria(statuses) {
  return Object.entries(statuses).map(([code, status]) => ({
    code,
    status,
    paths: status === "NOT_COVERED" ? [] : [`TP-00${code.slice(-1)}`],
  }));
}

function testRuns() {
  return {
    schema_version: 3,
    kind: "orchestwin.test-reviews",
    project_id: PROJECT_ID,
    runs: [
      {
        id: LATEST_RUN,
        started_at: "2026-09-30T09:04:00+00:00",
        finished_at: "2026-09-30T09:05:40+00:00",
        recorded_at: "2026-09-30T09:05:41+00:00",
        application: { kind: "STATIC", address: "." },
        browsers: [
          { name: "chrome", version: "151.0.7922.76" },
          { name: "firefox", version: "157.0" },
        ],
        reference: reference(5),
        summary: { passed: 3, failed: 1, blocked: 1, not_covered: 1, not_run: 0 },
        criteria: criteria({
          "AC-001": "PASSED",
          "AC-002": "PASSED",
          "AC-003": "FAILED",
          "AC-004": "BLOCKED",
          "AC-005": "PASSED",
          "AC-006": "NOT_COVERED",
        }),
        not_covered: [{ criterion: "AC-006", reason: "It needs a person." }],
        results: [],
        critiques: [
          critique(HEAD_WAITER, "Head waiter", "CONCERN"),
          critique(SEASONAL, "Seasonal waiters", "DRIFT"),
        ],
        reviewed_at: "2026-09-30T09:06:30+00:00",
        cost_microusd: 541504,
      },
      {
        id: EARLIER_RUN,
        started_at: "2026-09-29T22:36:34+00:00",
        finished_at: "2026-09-29T22:37:43+00:00",
        recorded_at: "2026-09-29T22:37:44+00:00",
        application: { kind: "STATIC", address: "." },
        browsers: [{ name: "chrome", version: "151.0.7922.76" }],
        reference: reference(4),
        summary: { passed: 5, failed: 0, blocked: 0, not_covered: 1, not_run: 0 },
        criteria: [],
        not_covered: [],
        results: [],
        critiques: [
          critique(HEAD_WAITER, "Head waiter", "FINE"),
          critique(SEASONAL, "Seasonal waiters", "FINE"),
        ],
        reviewed_at: "2026-09-29T22:38:49+00:00",
        cost_microusd: 300000,
      },
    ],
  };
}

function observation(code, statement, source, version, approvedAt) {
  return {
    code,
    statement,
    basis: source === "OWNER" ? null : "Seen in the critiques of the commits.",
    source,
    about: { requirement: "REQ-002", screen: null },
    contradicts_profile: null,
    added_in_version: version,
    approved_at: approvedAt,
    update_id: null,
  };
}

function learning() {
  return {
    schema_version: 3,
    kind: "orchestwin.twin-learning",
    project_id: PROJECT_ID,
    twins: [
      {
        twin_id: HEAD_WAITER,
        twin_name: "Head waiter",
        profile_version_number: 1,
        development_version_number: 3,
        label: "1.3",
        observations: [
          observation(
            "OBS-001",
            "Reads the total from a distance while talking to the guests.",
            "TWIN_CRITIQUE",
            1,
            "2026-09-29T18:00:00+00:00",
          ),
          observation(
            "OBS-002",
            "Wants the percentage kept between two tables of the same evening.",
            "TWIN_CRITIQUE",
            1,
            "2026-09-29T18:00:00+00:00",
          ),
          observation(
            "OBS-004",
            "Does not trust a result that jumps under the fields while typing.",
            "TWIN_CRITIQUE",
            2,
            "2026-09-30T08:00:00+00:00",
          ),
          observation(
            "OBS-005",
            "Asks the waiters to check the tip before showing it to the guests.",
            "OWNER",
            3,
            "2026-09-30T09:30:00+00:00",
          ),
        ],
        retired: [
          {
            code: "OBS-003",
            statement: "Prefers a printed table.",
            retired_in_version: 2,
            retired_at: "2026-09-30T07:00:00+00:00",
            reason: null,
          },
        ],
      },
      {
        twin_id: SEASONAL,
        twin_name: "Seasonal waiters",
        profile_version_number: 1,
        development_version_number: 0,
        label: "1.0",
        observations: [],
        retired: [],
      },
    ],
  };
}

function twinsDocument() {
  return {
    id: "9b5c829a-00b4-4b67-90d1-1bb4ebcfac63",
    project_id: PROJECT_ID,
    version_number: 1,
    snapshot: {
      schema_version: 1,
      project_id: PROJECT_ID,
      twin_versions: [
        { twin_id: HEAD_WAITER, version_number: 1, profile: { name: "Head waiter" } },
        { twin_id: SEASONAL, version_number: 1, profile: { name: "Seasonal waiters" } },
      ],
    },
  };
}

function requirementsDocument() {
  return {
    id: "d2e7b238-c10c-48f5-869e-9af3a321cdc9",
    project_id: PROJECT_ID,
    version_number: 1,
    specification: {
      requirements: [],
      acceptance_criteria: Object.entries(STATEMENTS).map(([code, statement]) => ({
        code,
        statement,
        verification_method: "AUTOMATED_TEST",
      })),
    },
  };
}

function writeCompleteProject(root, shape = "new") {
  const approved = ["brief", "team", "twins", "requirements", "design"];
  writeJson(root, ".orchestwin/project.json", link("Tip calculator"));
  writeJson(root, "orchestwin/orchestwin.json", manifest(approved, shape));
  writeJson(root, "orchestwin/state/state.json", projectState(shape));
  writeJson(root, "orchestwin/twins/twins.json", twinsDocument());
  writeJson(root, "orchestwin/twins/feedback/changes.json", changeRuns());
  writeJson(root, "orchestwin/twins/feedback/tests.json", testRuns());
  writeJson(root, "orchestwin/requirements/requirements.json", requirementsDocument());
  writeJson(root, ".orchestwin/tests/latest.json", {
    schema_version: 1,
    run_id: LATEST_RUN,
    folder: RUN_FOLDER,
    report: `${RUN_FOLDER}/report.html`,
    finished_at: "2026-09-30T09:05:40+00:00",
  });
  writeText(
    root,
    `.orchestwin/tests/${RUN_FOLDER}/report.html`,
    "<!DOCTYPE html>\n<title>Report</title>\n",
  );
  if (shape === "new") {
    writeJson(root, "orchestwin/twins/feedback/learned.json", learning());
    writeJson(root, ".orchestwin/code/latest.json", {
      schema_version: 1,
      folder: "20260930-081000",
      started_at: "2026-09-30T08:10:00+00:00",
      finished_at: "2026-09-30T08:31:00+00:00",
      agent: "claude",
      exit_status: 0,
      changed_files: ["app.js", "index.html", "styles.css"],
    });
  }
  return root;
}

function writeDesignPoint(root, version, values = {}) {
  return writeJson(root, DESIGN_POINT, {
    schema_version: 1,
    design_version_number: version,
    recorded_at: "2026-10-06T21:30:00+00:00",
    folder: "20261006-212000",
    reason: "DESIGN_RUN",
    ...values,
  });
}

function writePartialProject(root) {
  writeJson(root, ".orchestwin/project.json", link("Tip calculator"));
  writeJson(root, "orchestwin/orchestwin.json", manifest(["brief"], "new"));
  writeJson(root, "orchestwin/state/state.json", {
    schema_version: 3,
    kind: "orchestwin.project-state",
    project_id: PROJECT_ID,
    reference: { requirements: null, design: null },
    aligned: null,
    changes: [],
    tasks: [],
  });
  writeJson(root, "orchestwin/twins/feedback/changes.json", {
    schema_version: 3,
    kind: "orchestwin.change-reviews",
    project_id: PROJECT_ID,
    runs: [],
  });
  return root;
}

function writeBrokenProject(root) {
  writeCompleteProject(root, "new");
  writeText(root, "orchestwin/state/state.json", '{ "schema_version": 3, "changes": [');
  return root;
}

function writeUnlinkedFolder(root) {
  writeText(root, "notes.txt", "A folder that is not an OrchesTwin project.\n");
  return root;
}

module.exports = {
  ALIGNED_COMMIT,
  CLEAN_COMMIT,
  DESIGN_POINT,
  DRIFT_COMMIT,
  EARLIER_RUN,
  HEAD_WAITER,
  LATEST_RUN,
  PROJECT_ID,
  RUN_FOLDER,
  SEASONAL,
  STATEMENTS,
  link,
  makeTemporaryFolder,
  readJson,
  removeFolder,
  writeBrokenProject,
  writeCompleteProject,
  writeDesignPoint,
  writeJson,
  writePartialProject,
  writeText,
  writeUnlinkedFolder,
};
