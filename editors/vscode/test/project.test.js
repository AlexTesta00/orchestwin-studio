"use strict";

const assert = require("node:assert/strict");
const path = require("node:path");
const { after, before, describe, it } = require("node:test");
const fixtures = require("./fixtures");
const { isStale, readProject } = require("../src/project");

const ALL_STAGES = ["brief", "team", "twins", "requirements", "design"];

describe("readProject", () => {
  let base;

  before(() => {
    base = fixtures.makeTemporaryFolder();
  });

  after(() => {
    fixtures.removeFolder(base);
  });

  describe("a complete project in the shapes of this sprint", () => {
    let root;
    let state;

    before(() => {
      root = fixtures.writeCompleteProject(path.join(base, "complete"), "new");
      state = readProject(root);
    });

    it("is linked, names the project and reads every file without a notice", () => {
      assert.equal(state.root, root);
      assert.equal(state.linked, true);
      assert.deepEqual(state.project, {
        id: fixtures.PROJECT_ID,
        name: "Tip calculator",
        language: "en",
        mode: "DESIGN_ONLY",
        knowledgeFolder: "orchestwin",
      });
      assert.deepEqual(state.notices, []);
    });

    it("reads the version of the knowledge folder and the approved steps", () => {
      assert.deepEqual(state.folder, {
        available: true,
        problem: null,
        path: "orchestwin",
        name: "Tip calculator for waiters",
        language: "en",
        version: 12,
        publishedAt: "2026-09-30T09:12:00+00:00",
        approved: ALL_STAGES,
        pending: null,
        complete: true,
      });
      assert.deepEqual(state.reference, { requirements: 1, design: 5, alternative: "DES-002" });
    });

    it("counts the pending commits and only their stale reviews", () => {
      const development = state.development;
      assert.equal(development.available, true);
      assert.deepEqual(development.aligned, {
        commit: fixtures.ALIGNED_COMMIT,
        decidedAt: "2026-09-29T16:13:26+00:00",
        design: 4,
      });
      assert.equal(development.alignedDesign, 4);
      assert.equal(development.recorded, 3);
      assert.equal(development.pending, 2);
      assert.equal(development.staleKnown, true);
      assert.equal(development.stale, 1);
      assert.deepEqual(development.staleCommits, [fixtures.DRIFT_COMMIT]);
      assert.deepEqual(development.latest, {
        commit: fixtures.DRIFT_COMMIT,
        subject: "feat: split the bill between the guests",
        committedAt: "2026-09-30T08:40:00+00:00",
        verdict: "CODE_DRIFT",
        reviewedAt: "2026-09-30T08:52:10+00:00",
        stale: true,
        decision: null,
      });
    });

    it("reads the open tasks with the three origins", () => {
      const tasks = state.tasks;
      assert.equal(tasks.available, true);
      assert.equal(tasks.done, 1);
      assert.equal(tasks.dropped, 1);
      assert.deepEqual(
        tasks.open.map((task) => [task.code, task.origin.kind, task.origin.twinName]),
        [
          ["TSK-002", "CODE_CHANGE", "Head waiter"],
          ["TSK-003", "TEST_RUN", "Seasonal waiters"],
          ["TSK-004", "OWNER", null],
        ],
      );
      assert.equal(tasks.open[0].origin.commit, fixtures.CLEAN_COMMIT);
      assert.equal(tasks.open[1].origin.testRunId, fixtures.LATEST_RUN);
      assert.deepEqual(tasks.open[1].criteria, ["AC-003"]);
      assert.equal(tasks.open[2].origin.commit, null);
      assert.equal(
        tasks.open[0].text,
        "Keep the chosen percentage selected after New calculation, as in the approved design.",
      );
    });

    it("reads the latest test run with its failed and blocked criteria", () => {
      const tests = state.tests;
      assert.equal(tests.available, true);
      assert.equal(tests.runs, 2);
      const run = tests.latest;
      assert.equal(run.id, fixtures.LATEST_RUN);
      assert.equal(run.source, "FOLDER");
      assert.equal(run.finishedAt, "2026-09-30T09:05:40+00:00");
      assert.deepEqual(run.browsers, [
        { name: "chrome", version: "151.0.7922.76" },
        { name: "firefox", version: "157.0" },
      ]);
      assert.deepEqual(run.summary, { passed: 3, failed: 1, blocked: 1, notCovered: 1, notRun: 0 });
      assert.deepEqual(run.problems, [
        { code: "AC-003", status: "FAILED", statement: fixtures.STATEMENTS["AC-003"] },
        { code: "AC-004", status: "BLOCKED", statement: fixtures.STATEMENTS["AC-004"] },
      ]);
      assert.equal(run.reviewed, true);
      assert.equal(run.reviewedAt, "2026-09-30T09:06:30+00:00");
      assert.deepEqual(
        run.critiques.map((critique) => [critique.twinName, critique.verdict]),
        [
          ["Head waiter", "CONCERN"],
          ["Seasonal waiters", "DRIFT"],
        ],
      );
      assert.equal(run.stale, false);
    });

    it("finds the report that latest.json names", () => {
      assert.equal(
        state.tests.report,
        path.join(root, ".orchestwin", "tests", fixtures.RUN_FOLDER, "report.html"),
      );
    });

    it("reads what every twin learned and its latest verdicts", () => {
      const twins = state.twins;
      assert.equal(twins.available, true);
      assert.equal(twins.learning, true);
      const [head, seasonal] = twins.items;
      assert.equal(head.name, "Head waiter");
      assert.equal(head.label, "1.3");
      assert.equal(head.profileVersion, 1);
      assert.equal(head.developmentVersion, 3);
      assert.equal(head.learned, 4);
      assert.deepEqual(
        head.observations.map((observation) => [observation.code, observation.source]),
        [
          ["OBS-005", "OWNER"],
          ["OBS-004", "TWIN_CRITIQUE"],
          ["OBS-002", "TWIN_CRITIQUE"],
        ],
      );
      assert.deepEqual(head.commit, {
        verdict: "DRIFT",
        commit: fixtures.DRIFT_COMMIT,
        reviewedAt: "2026-09-30T08:52:10+00:00",
      });
      assert.equal(head.test.verdict, "CONCERN");
      assert.equal(head.test.runId, fixtures.LATEST_RUN);
      assert.equal(seasonal.label, "1.0");
      assert.equal(seasonal.learned, 0);
      assert.deepEqual(seasonal.observations, []);
      assert.equal(seasonal.commit.verdict, "CONCERN");
      assert.equal(seasonal.test.verdict, "DRIFT");
    });

    it("reads the latest run of the coding agent and the state of the agents", () => {
      assert.deepEqual(state.code, {
        startedAt: "2026-09-30T08:10:00+00:00",
        finishedAt: "2026-09-30T08:31:00+00:00",
        agent: "claude",
        exitStatus: 0,
        changedFiles: 3,
      });
      assert.deepEqual(state.agents, { file: ".vscode/mcp.json", status: "MISSING" });
    });

    it("is a plain object that JSON keeps as it is", () => {
      assert.deepEqual(JSON.parse(JSON.stringify(state)), state);
    });
  });

  describe("a complete project in the shapes of sprint 27", () => {
    let state;

    before(() => {
      state = readProject(fixtures.writeCompleteProject(path.join(base, "old"), "old"));
    });

    it("reads the folder without the flags of stale reviews", () => {
      assert.equal(state.folder.complete, true);
      assert.deepEqual(state.notices, []);
      assert.equal(state.development.pending, 2);
      assert.equal(state.development.staleKnown, false);
      assert.equal(state.development.stale, 0);
      assert.deepEqual(state.development.staleCommits, []);
      assert.equal(state.development.latest.stale, false);
      assert.equal(state.development.aligned.design, 4);
    });

    it("reads the tasks without origin as tasks of the verdict on their commit", () => {
      assert.equal(state.tasks.done, 1);
      assert.equal(state.tasks.dropped, 0);
      assert.deepEqual(
        state.tasks.open.map((task) => [task.code, task.origin]),
        [
          [
            "TSK-002",
            { kind: "CODE_CHANGE", commit: fixtures.CLEAN_COMMIT, testRunId: null, twinName: null },
          ],
          [
            "TSK-003",
            { kind: "CODE_CHANGE", commit: fixtures.DRIFT_COMMIT, testRunId: null, twinName: null },
          ],
        ],
      );
    });

    it("labels the twins with the profile version when learned.json is missing", () => {
      assert.equal(state.twins.learning, false);
      assert.deepEqual(
        state.twins.items.map((twin) => [
          twin.name,
          twin.label,
          twin.learned,
          twin.developmentVersion,
        ]),
        [
          ["Head waiter", "1.0", 0, null],
          ["Seasonal waiters", "1.0", 0, null],
        ],
      );
      assert.equal(state.twins.items[0].commit.verdict, "DRIFT");
      assert.equal(state.code, null);
      assert.equal(state.tests.latest.id, fixtures.LATEST_RUN);
    });
  });

  describe("a partial folder with only the brief approved", () => {
    let state;

    before(() => {
      state = readProject(fixtures.writePartialProject(path.join(base, "partial")));
    });

    it("reads the approved steps and the next one", () => {
      assert.equal(state.linked, true);
      assert.equal(state.folder.available, true);
      assert.deepEqual(state.folder.approved, ["brief"]);
      assert.equal(state.folder.pending, "team");
      assert.equal(state.folder.complete, false);
      assert.deepEqual(state.reference, { requirements: null, design: null, alternative: null });
      assert.deepEqual(state.notices, []);
    });

    it("has an empty development, no test run and no twins yet", () => {
      assert.equal(state.development.available, true);
      assert.equal(state.development.pending, 0);
      assert.equal(state.development.aligned, null);
      assert.equal(state.development.latest, null);
      assert.deepEqual(state.tasks.open, []);
      assert.equal(state.tests.available, true);
      assert.equal(state.tests.latest, null);
      assert.equal(state.tests.report, null);
      assert.equal(state.twins.available, false);
      assert.equal(state.twins.problem, "MISSING");
    });
  });

  describe("a folder without .orchestwin", () => {
    it("is not linked and reads nothing else", () => {
      const root = fixtures.writeUnlinkedFolder(path.join(base, "unlinked"));
      const state = readProject(root);
      assert.equal(state.root, root);
      assert.equal(state.linked, false);
      assert.equal(state.project, null);
      assert.equal(state.folder.available, false);
      assert.deepEqual(state.notices, []);
      assert.equal(state.development.available, false);
      assert.equal(state.tests.latest, null);
    });

    it("gives an empty state without a root", () => {
      for (const root of [null, undefined, "", "   "]) {
        const state = readProject(root);
        assert.equal(state.root, null);
        assert.equal(state.linked, false);
      }
    });
  });

  describe("broken files", () => {
    it("names a file that is not valid JSON and reads the other parts", () => {
      const state = readProject(fixtures.writeBrokenProject(path.join(base, "broken")));
      assert.deepEqual(state.notices, [
        { file: "orchestwin/state/state.json", problem: "INVALID_JSON" },
      ]);
      assert.equal(state.folder.available, true);
      assert.equal(state.development.available, false);
      assert.equal(state.development.problem, "INVALID");
      assert.equal(state.development.aligned, null);
      assert.equal(state.development.alignedDesign, null);
      assert.equal(state.tasks.available, false);
      assert.equal(state.tests.latest.id, fixtures.LATEST_RUN);
      assert.equal(state.twins.items.length, 2);
      assert.deepEqual(state.reference, { requirements: null, design: null, alternative: null });
    });

    it("names a document that holds something else than an object", () => {
      const root = fixtures.writeCompleteProject(path.join(base, "array"), "new");
      fixtures.writeJson(root, "orchestwin/twins/feedback/tests.json", [1, 2, 3]);
      const state = readProject(root);
      assert.deepEqual(state.notices, [
        { file: "orchestwin/twins/feedback/tests.json", problem: "UNEXPECTED" },
      ]);
      assert.equal(state.tests.available, false);
      assert.equal(state.tests.problem, "UNEXPECTED");
    });

    it("treats a broken link as a folder that is not linked", () => {
      const root = path.join(base, "broken-link");
      fixtures.writeText(root, ".orchestwin/project.json", "{");
      const state = readProject(root);
      assert.equal(state.linked, false);
      assert.deepEqual(state.notices, [
        { file: ".orchestwin/project.json", problem: "INVALID_JSON" },
      ]);
    });

    it("reports a missing manifest as a missing folder", () => {
      const root = path.join(base, "no-folder");
      fixtures.writeJson(root, ".orchestwin/project.json", fixtures.link("Tip calculator"));
      const state = readProject(root);
      assert.equal(state.linked, true);
      assert.equal(state.folder.available, false);
      assert.equal(state.folder.problem, "MISSING");
      assert.equal(state.development.problem, "MISSING");
      assert.deepEqual(state.notices, []);
    });
  });

  describe("the local files of ut", () => {
    it("reads a run that is not in the knowledge folder yet from its run.json", () => {
      const root = fixtures.writeCompleteProject(path.join(base, "local-run"), "new");
      const runId = "0f0e0d0c-0b0a-4908-8706-050403020100";
      fixtures.writeJson(root, ".orchestwin/tests/latest.json", {
        schema_version: 1,
        run_id: runId,
        folder: "20260930-101500",
        report: "20260930-101500/report.html",
        finished_at: "2026-09-30T10:16:00+00:00",
      });
      fixtures.writeJson(root, ".orchestwin/tests/20260930-101500/run.json", {
        id: runId,
        finished_at: "2026-09-30T10:16:00+00:00",
        browsers: [{ name: "firefox", version: "157.0" }],
        summary: { passed: 6, failed: 0, blocked: 0, not_covered: 0, not_run: 0 },
        criteria: [],
        critiques: [],
        reviewed_at: null,
      });
      const state = readProject(root);
      assert.equal(state.tests.latest.id, runId);
      assert.equal(state.tests.latest.source, "LOCAL");
      assert.equal(state.tests.latest.reviewed, false);
      assert.equal(state.tests.runs, 2);
      assert.equal(state.tests.report, null);
    });

    it("ignores a report outside the folder of the tests", () => {
      const root = fixtures.writeCompleteProject(path.join(base, "escape"), "new");
      fixtures.writeText(root, "outside.html", "<p>outside</p>\n");
      fixtures.writeJson(root, ".orchestwin/tests/latest.json", {
        schema_version: 1,
        run_id: fixtures.LATEST_RUN,
        folder: fixtures.RUN_FOLDER,
        report: "../../outside.html",
      });
      assert.equal(readProject(root).tests.report, null);
    });

    it("follows the knowledge folder named by the link", () => {
      const root = path.join(base, "renamed");
      fixtures.writeCompleteProject(root, "new");
      const link = fixtures.readJson(root, ".orchestwin/project.json");
      fixtures.writeJson(root, ".orchestwin/project.json", {
        ...link,
        knowledge_folder: "knowledge",
      });
      fixtures.writeJson(
        root,
        "knowledge/orchestwin.json",
        fixtures.readJson(root, "orchestwin/orchestwin.json"),
      );
      const state = readProject(root);
      assert.equal(state.project.knowledgeFolder, "knowledge");
      assert.equal(state.folder.version, 12);
      assert.equal(state.development.problem, "MISSING");
    });

    it("keeps only what the latest run of the coding agent holds", () => {
      const root = fixtures.writeCompleteProject(path.join(base, "code"), "new");
      fixtures.writeJson(root, ".orchestwin/code/latest.json", {
        started_at: "2026-09-30T08:10:00+00:00",
        agent: { name: "Claude Code" },
        exit_status: 3,
      });
      assert.deepEqual(readProject(root).code, {
        startedAt: "2026-09-30T08:10:00+00:00",
        finishedAt: null,
        agent: "Claude Code",
        exitStatus: 3,
        changedFiles: null,
      });
    });
  });

  describe("the design version of the aligned point", () => {
    const STATE_FILE = "orchestwin/state/state.json";

    function alignedWith(name, value) {
      const root = fixtures.writeCompleteProject(path.join(base, name), "new");
      const document = fixtures.readJson(root, STATE_FILE);
      if (value === undefined) {
        delete document.aligned.design_version_number;
      } else {
        document.aligned.design_version_number = value;
      }
      fixtures.writeJson(root, STATE_FILE, document);
      const state = readProject(root);
      assert.deepEqual(state.notices, [], name);
      return state.development.aligned;
    }

    it("reads the design version that the aligned point records", () => {
      assert.deepEqual(alignedWith("aligned-design", 6), {
        commit: fixtures.ALIGNED_COMMIT,
        decidedAt: "2026-09-29T16:13:26+00:00",
        design: 6,
      });
    });

    it("leaves the design version empty when it is missing or not a number", () => {
      for (const [name, value] of [
        ["aligned-missing", undefined],
        ["aligned-null", null],
        ["aligned-text", "6"],
        ["aligned-fraction", 2.5],
        ["aligned-negative", -1],
        ["aligned-flag", true],
      ]) {
        const aligned = alignedWith(name, value);
        assert.equal(aligned.commit, fixtures.ALIGNED_COMMIT, name);
        assert.equal(aligned.design, null, name);
      }
    });

    function readWith(name, write) {
      const root = fixtures.writeCompleteProject(path.join(base, name), "new");
      write(root);
      return readProject(root);
    }

    it("takes the higher design version between the aligned point and the latest run of the agent", () => {
      const higher = readWith("point-higher", (root) => fixtures.writeDesignPoint(root, 7));
      assert.equal(higher.development.aligned.design, 4);
      assert.equal(higher.development.alignedDesign, 7);
      assert.deepEqual(higher.notices, []);
      const lower = readWith("point-lower", (root) => fixtures.writeDesignPoint(root, 3));
      assert.equal(lower.development.alignedDesign, 4);
      const missing = readWith("point-missing", () => {});
      assert.equal(missing.development.alignedDesign, 4);
      assert.deepEqual(missing.notices, []);
    });

    it("ignores a design point that is not valid and names one that cannot be read", () => {
      for (const [name, version, values] of [
        ["point-zero", 0, {}],
        ["point-text", "7", {}],
        ["point-flag", true, {}],
        ["point-fraction", 6.5, {}],
        ["point-without-version", undefined, {}],
        ["point-schema", 7, { schema_version: 2 }],
        ["point-schema-flag", 7, { schema_version: true }],
      ]) {
        const state = readWith(name, (root) => fixtures.writeDesignPoint(root, version, values));
        assert.equal(state.development.alignedDesign, 4, name);
        assert.deepEqual(state.notices, [], name);
      }
      for (const [name, write, problem] of [
        ["point-broken", (root) => fixtures.writeText(root, fixtures.DESIGN_POINT, "{ "), "INVALID_JSON"],
        ["point-list", (root) => fixtures.writeJson(root, fixtures.DESIGN_POINT, [7]), "UNEXPECTED"],
      ]) {
        const state = readWith(name, write);
        assert.equal(state.development.alignedDesign, 4, name);
        assert.deepEqual(state.notices, [{ file: ".orchestwin/code/design.json", problem }], name);
      }
    });

    it("compares with the design point alone while no commit is aligned", () => {
      const withoutAligned = (root) => {
        const document = fixtures.readJson(root, STATE_FILE);
        document.aligned = null;
        fixtures.writeJson(root, STATE_FILE, document);
      };
      const alone = readWith("point-alone", (root) => {
        withoutAligned(root);
        fixtures.writeDesignPoint(root, 6);
      });
      assert.equal(alone.development.aligned, null);
      assert.equal(alone.development.alignedDesign, 6);
      assert.equal(alone.development.pending, 3);
      assert.equal(readWith("point-none", withoutAligned).development.alignedDesign, null);
      const zero = readWith("point-zero-alone", (root) => {
        withoutAligned(root);
        fixtures.writeDesignPoint(root, 0);
      });
      assert.equal(zero.development.alignedDesign, null);
    });
  });

  describe("the visual direction of the chosen alternative", () => {
    const DESIGN_FILE = "orchestwin/design/design.json";

    function designDocument(versionNumber, names) {
      return {
        id: "8f0c1d2e-3a4b-4c5d-8e6f-7a8b9c0d1e2f",
        project_id: fixtures.PROJECT_ID,
        version_number: versionNumber,
        package: {
          owner_selected_alternative_id: "alternative-2",
          alternatives: names.map((name, index) => {
            const visual = { product_name: "Tip calculator" };
            if (name !== null) {
              visual.direction = {
                name,
                concept: "A printed bill, with the total in large figures and ruled groups.",
                rules: [
                  "The total is the largest figure of every screen.",
                  "Thin rules separate the groups.",
                  "Colour marks the main action only.",
                ],
                axes: {
                  layout: "EDITORIAL",
                  shape: "SQUARE_RULES",
                  type: "DISPLAY",
                  colour: "INK",
                  density: "SPACIOUS",
                },
                typicality: 12,
                candidates: 5,
                vocabulary_version: 1,
              };
            }
            return {
              id: `alternative-${index + 1}`,
              code: `DES-00${index + 1}`,
              title: `Alternative ${index + 1}`,
              visual_language: visual,
            };
          }),
        },
      };
    }

    function projectWith(name, document) {
      const root = fixtures.writeCompleteProject(path.join(base, name), "new");
      if (typeof document === "string") {
        fixtures.writeText(root, DESIGN_FILE, document);
      } else if (document !== undefined) {
        fixtures.writeJson(root, DESIGN_FILE, document);
      }
      return readProject(root);
    }

    it("names the direction of the alternative that the reference names", () => {
      const state = projectWith("directed", designDocument(5, ["Soft bands", "Printed register"]));
      assert.deepEqual(state.reference, {
        requirements: 1,
        design: 5,
        alternative: "DES-002",
        direction: "Printed register",
      });
      assert.deepEqual(state.notices, []);
      assert.deepEqual(JSON.parse(JSON.stringify(state)), state);
    });

    it("adds nothing when the chosen alternative or its design version has no direction", () => {
      for (const [name, document] of [
        ["other-alternative", designDocument(5, ["Soft bands", null])],
        ["no-direction", designDocument(5, [null, null])],
        ["older-version", designDocument(4, ["Soft bands", "Printed register"])],
        ["no-design", undefined],
      ]) {
        const state = projectWith(name, document);
        assert.deepEqual(state.reference, { requirements: 1, design: 5, alternative: "DES-002" }, name);
        assert.ok(!Object.hasOwn(state.reference, "direction"), name);
        assert.deepEqual(state.notices, [], name);
      }
    });

    it("names a design document that is not valid JSON and reads the other parts", () => {
      const state = projectWith("broken-design", '{ "package": ');
      assert.deepEqual(state.notices, [{ file: DESIGN_FILE, problem: "INVALID_JSON" }]);
      assert.deepEqual(state.reference, { requirements: 1, design: 5, alternative: "DES-002" });
      assert.equal(state.development.available, true);
      assert.equal(state.tasks.open.length, 3);
    });

    it("reads no design document while no design is approved", () => {
      const root = fixtures.writePartialProject(path.join(base, "partial-design"));
      fixtures.writeText(root, DESIGN_FILE, '{ "package": ');
      const state = readProject(root);
      assert.deepEqual(state.reference, { requirements: null, design: null, alternative: null });
      assert.deepEqual(state.notices, []);
    });
  });

  describe("isStale", () => {
    const current = {
      requirements_version_number: 1,
      design_version_number: 5,
      alternative_code: "DES-002",
    };

    it("is true when one of the three values differs", () => {
      assert.equal(isStale({ ...current }, current), false);
      assert.equal(isStale({ ...current, design_version_number: 4 }, current), true);
      assert.equal(isStale({ ...current, requirements_version_number: 2 }, current), true);
      assert.equal(isStale({ ...current, alternative_code: "DES-001" }, current), true);
    });

    it("is false without a current reference or without a reference", () => {
      assert.equal(isStale({ ...current, design_version_number: 4 }, null), false);
      assert.equal(isStale(undefined, current), false);
    });
  });
});

for (const [schemaVersion, withJourneys] of [[1, false], [2, false], [2, true]]) {
  it(`reads criteria and current references from Definition schema ${schemaVersion}, journeys ${withJourneys}`, () => {
    const base = fixtures.makeTemporaryFolder();
    try {
      const root = fixtures.writeCompleteProject(path.join(base, "definition"), "new");
      const file = "orchestwin/requirements/requirements.json";
      const document = fixtures.readJson(root, file);
      document.specification.schema_version = schemaVersion;
      if (schemaVersion === 2) {
        document.specification.needs = [{ id: "need", code: "NED-001", title: "Settle the bill", scenario_ids: ["scenario"] }];
        document.specification.scenarios = [{ id: "scenario", code: "SCN-001", context: "At the table", goal: "Settle the bill" }];
      }
      if (withJourneys) {
        document.specification.journeys = [{
          id: "journey", code: "JRN-001", title: "Settle the bill", scenario_id: "scenario",
          phases: [{ title: "Review the bill", action: "Read the shares", touchpoint: null, criticalities: [], need_ids: ["need"] }],
          sources: [{ kind: "OWNER_INPUT", source_id: "fixture", source_version: null, content_hash: null, locator: null }],
        }];
      }
      fixtures.writeJson(root, file, document);
      const state = readProject(root);
      assert.deepEqual(state.notices, []);
      assert.deepEqual(state.reference, { requirements: 1, design: 5, alternative: "DES-002" });
      assert.equal(state.tests.latest.stale, false);
      assert.deepEqual(state.tests.latest.problems.map((item) => item.statement), [fixtures.STATEMENTS["AC-003"], fixtures.STATEMENTS["AC-004"]]);
      assert.equal(state.twins.items.length, 2);
    } finally {
      fixtures.removeFolder(base);
    }
  });
}
