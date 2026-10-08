"use strict";

const assert = require("node:assert/strict");
const path = require("node:path");
const { after, before, describe, it } = require("node:test");
const fixtures = require("./fixtures");
const { ALIGNMENT_FILE, readAlignment } = require("../src/alignment");

const RUN_ID = "0c1d2e3f-4a5b-4c6d-8e7f-9a0b1c2d3e4f";
const LATEST = Object.freeze({
  schema_version: 1,
  run_id: RUN_ID,
  finished_at: "2026-10-06T10:20:00+00:00",
  from_commit: fixtures.ALIGNED_COMMIT,
  to_commit: fixtures.DRIFT_COMMIT,
  proposals: 5,
  waiting: 2,
  applied: 2,
  skipped: 1,
});

describe("readAlignment", () => {
  let base;

  before(() => {
    base = fixtures.makeTemporaryFolder();
  });

  after(() => {
    fixtures.removeFolder(base);
  });

  it("reads the file that ut align writes", () => {
    assert.equal(ALIGNMENT_FILE, ".orchestwin/align/latest.json");
    const root = fixtures.writeCompleteProject(path.join(base, "latest"), "new");
    fixtures.writeJson(root, ALIGNMENT_FILE, LATEST);
    const alignment = readAlignment(root);
    assert.deepEqual(alignment, {
      runId: RUN_ID,
      finishedAt: "2026-10-06T10:20:00+00:00",
      fromCommit: fixtures.ALIGNED_COMMIT,
      toCommit: fixtures.DRIFT_COMMIT,
      proposals: 5,
      waiting: 2,
      applied: 2,
      skipped: 1,
    });
    assert.deepEqual(JSON.parse(JSON.stringify(alignment)), alignment);
  });

  it("gives null without a folder, without the file and with a broken file", () => {
    for (const folder of [null, undefined, "", "   ", 3]) {
      assert.equal(readAlignment(folder), null);
    }
    assert.equal(readAlignment(path.join(base, "missing")), null);
    const broken = path.join(base, "broken");
    fixtures.writeText(broken, ALIGNMENT_FILE, '{ "run_id": ');
    assert.equal(readAlignment(broken), null);
    const list = path.join(base, "list");
    fixtures.writeJson(list, ALIGNMENT_FILE, [LATEST]);
    assert.equal(readAlignment(list), null);
    const word = path.join(base, "word");
    fixtures.writeJson(word, ALIGNMENT_FILE, "latest");
    assert.equal(readAlignment(word), null);
  });

  it("keeps what the file holds, counts lists and reads past a byte order mark", () => {
    const root = path.join(base, "partial");
    const content = JSON.stringify({
      schema_version: 1,
      run_id: "   ",
      to_commit: fixtures.DRIFT_COMMIT,
      proposals: [{ code: "ALN-001" }, { code: "ALN-002" }],
      waiting: -1,
      applied: "2",
      skipped: 1.5,
    });
    fixtures.writeText(root, ALIGNMENT_FILE, `﻿${content}\n`);
    assert.deepEqual(readAlignment(root), {
      runId: null,
      finishedAt: null,
      fromCommit: null,
      toCommit: fixtures.DRIFT_COMMIT,
      proposals: 2,
      waiting: 0,
      applied: 0,
      skipped: 0,
    });
  });

  it("reads nothing else than the file of the latest run", () => {
    const root = path.join(base, "other");
    fixtures.writeJson(root, ".orchestwin/align/0c1d2e3f.json", LATEST);
    assert.equal(readAlignment(root), null);
  });
});
