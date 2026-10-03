"use strict";

const assert = require("node:assert/strict");
const crypto = require("node:crypto");
const path = require("node:path");
const { after, before, describe, it } = require("node:test");
const fixtures = require("./fixtures");
const { readProject } = require("../src/project");
const { renderPanel } = require("../src/view");
const { text } = require("../src/messages");
const { LIMITS, canonical, readWorkflowInputs } = require("../src/workflow-inputs");

function hashed(record) {
  return { ...record, content_hash: crypto.createHash("sha256").update(canonical(record), "utf8").digest("hex") };
}

function writeRecords(root, change = () => {}) {
  const decision = hashed({ id: "26a781d3-45fd-490c-bd2b-ff541e517e70", project_id: fixtures.PROJECT_ID, sequence: 1, target: "EVIDENCE", action: "DECLARE_MISSING", reason: '<script>alert("note")</script> No observations.', base_context: {}, recorded_at: "2026-10-03T18:00:00+00:00" });
  const prototype = hashed({ id: "f62ad576-9b6c-4c06-85e1-9aee518689b0", code: "PRT-001", project_id: fixtures.PROJECT_ID, version_number: 1, based_on_version_number: null, definition_reference: { artifact_id: "e7aa4ad9-2e40-498b-9d4e-3798af8084d7", version_number: 1, content_hash: "a".repeat(64) }, title: "Library loans", declared_origin: '<img src=x onerror="alert(1)"> Figma', visual_choices: { archetype: "GUIDED_STEPS" }, mockup: { mockup: { design_alternative_id: "f62ad576-9b6c-4c06-85e1-9aee518689b0" }, requirement_ids_by_code: {} }, created_at: "2026-10-03T18:00:00+00:00" });
  const reference = { artifact_id: prototype.id, version_number: 1, content_hash: prototype.content_hash, gate_status: "APPROVED" };
  const manifest = fixtures.readJson(root, "orchestwin/orchestwin.json");
  manifest.workflow_inputs = { schema_version: 1, decisions_document: "workflow/decisions.json", prototypes_document: "design/provided-prototypes.json", limits: [...LIMITS], approved_prototype: reference };
  const data = { manifest, decisions: { decisions: [decision] }, prototypes: { prototypes: [prototype], approved_prototype: reference } };
  change(data);
  fixtures.writeJson(root, "orchestwin/orchestwin.json", data.manifest);
  fixtures.writeJson(root, "orchestwin/workflow/decisions.json", data.decisions);
  fixtures.writeJson(root, "orchestwin/design/provided-prototypes.json", data.prototypes);
  return data;
}

describe("sprint 36 workflow inputs in the editor", () => {
  let base;
  let count = 0;
  before(() => { base = fixtures.makeTemporaryFolder(); });
  after(() => { fixtures.removeFolder(base); });
  function project() { count += 1; return fixtures.writeCompleteProject(path.join(base, `workflow ${count}`), "new"); }

  it("keeps the old project shape and panel when records are absent", () => {
    const root = project();
    const state = readProject(root);
    assert.equal(Object.hasOwn(state, "workflowInputs"), false);
    assert.equal(renderPanel(state, { language: "en" }).includes('id="workflow-inputs"'), false);
  });

  for (const language of ["it", "en"]) {
    it(`shows supplied origin, declared gaps, exact hashes, limits and filters in ${language}`, () => {
      const root = project();
      const data = writeRecords(root);
      const state = readProject(root);
      assert.equal(state.workflowInputs.available, true);
      const html = renderPanel(state, { language });
      assert.ok(html.includes(text(language, "workflow.missing")));
      assert.ok(html.includes(text(language, "workflow.origin")));
      assert.ok(html.includes(data.prototypes.prototypes[0].content_hash));
      assert.ok(html.includes('id="workflow-filter"'));
      assert.ok(html.includes('value="gaps"'));
      assert.ok(html.includes('value="owner"'));
      for (const code of LIMITS) {
        assert.ok(html.includes(code));
        assert.ok(html.includes(text(language, `workflow.limit.${code}`)));
      }
      assert.equal(html.includes('<img src=x onerror="alert(1)">'), false);
      assert.equal(html.includes('<script>alert("note")</script>'), false);
    });
  }

  it("rejects a modified record even when JSON and manifest remain readable", () => {
    const root = project();
    writeRecords(root, (data) => { data.decisions.decisions[0].reason = "Modified"; });
    const state = readProject(root);
    assert.equal(state.workflowInputs.available, false);
    assert.ok(renderPanel(state, { language: "en" }).includes(text("en", "workflow.invalid")));
  });

  it("rejects a record of another project with a valid hash", () => {
    const root = project();
    writeRecords(root, (data) => {
      const copy = { ...data.decisions.decisions[0], project_id: "foreign" };
      delete copy.content_hash;
      data.decisions.decisions[0] = hashed(copy);
    });
    assert.equal(readProject(root).workflowInputs.available, false);
  });

  it("rejects forged approval and changed limits", () => {
    for (const change of [
      (data) => { data.manifest.workflow_inputs.approved_prototype.content_hash = "b".repeat(64); },
      (data) => { data.manifest.workflow_inputs.limits = []; },
    ]) {
      const root = project();
      writeRecords(root, change);
      assert.equal(readProject(root).workflowInputs.available, false);
    }
  });

  it("never reads a changed workflow document path", () => {
    const root = project();
    writeRecords(root, (data) => { data.manifest.workflow_inputs.decisions_document = "../outside.json"; });
    assert.equal(readProject(root).workflowInputs.available, false);
  });

  it("rejects undeclared files instead of silently treating them as legacy", () => {
    const root = project();
    const data = writeRecords(root);
    delete data.manifest.workflow_inputs;
    assert.equal(readWorkflowInputs(root, "orchestwin", data.manifest, fixtures.PROJECT_ID).available, false);
  });

  it("preserves Unicode spelling in canonical hashes", () => {
    assert.notEqual(hashed({ reason: "é" }).content_hash, hashed({ reason: "e\u0301" }).content_hash);
  });
});
