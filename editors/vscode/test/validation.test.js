"use strict";

const assert = require("node:assert/strict");
const path = require("node:path");
const { after, before, describe, it } = require("node:test");
const fixtures = require("./fixtures");
const data = require("./validation-fixtures");
const { readValidation, readWalkthrough } = require("../src/validation");
const { readProject } = require("../src/project");
const { escapeHtml, renderPanel } = require("../src/view");
const { MESSAGES, text } = require("../src/messages");

describe("read-only validation in the editor", () => {
  let root;
  before(() => {
    root = fixtures.writeCompleteProject(path.join(fixtures.makeTemporaryFolder(), "validation"));
  });
  after(() => fixtures.removeFolder(path.dirname(root)));

  it("reads verified offline data through ut without shell, network or login", async () => {
    const expected = data.overview();
    const result = await readValidation(root, '"C:/Tools with spaces/ut.exe"', fixtures.PROJECT_ID, {}, (program, args, options, finish) => {
      assert.equal(program, "C:/Tools with spaces/ut.exe");
      assert.deepEqual(args, ["validation", "--offline", "--json"]);
      assert.equal(options.cwd, root);
      assert.equal(options.shell, false);
      assert.equal(options.windowsHide, true);
      assert.equal(options.timeout, 30000);
      finish(null, JSON.stringify(expected), "");
    });
    assert.deepEqual(result, { status: "OK", answer: expected, source: "OFFLINE" });
  });

  it("preserves the source distinction for explicit Studio reads and the existing offline fallback", async () => {
    for (const [stderr, source] of [["", "STUDIO"], ["Verified local Dossier (NOT_SIGNED_IN); its data may predate Studio.", "OFFLINE"], ["Dossier locale verificato (STUDIO_UNREACHABLE); i dati possono essere precedenti a Studio.", "OFFLINE"]]) {
      const result = await readValidation(root, "ut", fixtures.PROJECT_ID, { offline: false }, (_program, args, _options, finish) => {
        assert.deepEqual(args, ["validation", "--json"]);
        finish(null, JSON.stringify(data.overview()), stderr);
      });
      assert.equal(result.source, source);
    }
  });

  it("reads large full-reference validation overviews with a finite stdout limit", async () => {
    const design = Array.from({ length: 331 }, (_, index) => data.node(`ALT-${index + 1}`, "DESIGN_ALTERNATIVE"));
    const base = data.overview();
    const candidates = Array.from({ length: 47 }, (_, index) => ({
      ...base.candidates[0],
      ...data.node(`UT-claim-${index + 1}`, "USER_TWIN_CLAIM"),
      design_references: design,
    }));
    const stdout = JSON.stringify({ ...base, candidate_count: candidates.length, candidates }, null, 2);
    const bytes = Buffer.byteLength(stdout, "utf8");
    assert.ok(bytes > 4 * 1024 * 1024);
    for (const offline of [true, false]) {
      const result = await readValidation(root, "ut", fixtures.PROJECT_ID, { offline }, (_program, _args, options, finish) => {
        assert.ok(Number.isFinite(options.maxBuffer));
        assert.ok(options.maxBuffer <= 32 * 1024 * 1024);
        if (bytes > options.maxBuffer) {
          finish({ code: "ERR_CHILD_PROCESS_STDIO_MAXBUFFER" }, "", "");
        } else {
          finish(null, stdout, "");
        }
      });
      assert.equal(result.status, "OK");
      assert.equal(result.source, offline ? "OFFLINE" : "STUDIO");
      assert.equal(result.answer.candidate_count, 47);
      assert.equal(result.answer.candidates[46].design_references.length, 331);
      assert.equal(result.answer.candidates[46].design_references[330].key, design[330].key);
    }
  });

  it("reads a filtered scenario walkthrough with exact existing selectors", async () => {
    const expected = data.walkthrough();
    const scenario = expected.scenario.key;
    const result = await readWalkthrough(root, "ut", scenario, fixtures.PROJECT_ID, { alternative: "alternative-id", documentHash: data.HASH }, (_program, args, options, finish) => {
      assert.deepEqual(args, ["validation", "walkthrough", scenario, "--alternative", "alternative-id", "--document-hash", data.HASH, "--offline", "--json"]);
      assert.equal(options.shell, false);
      finish(null, JSON.stringify(expected), "");
    });
    assert.deepEqual(result, { status: "OK", answer: expected, source: "OFFLINE" });
  });

  it("rejects command and option injection before starting ut", async () => {
    for (const [scenario, options] of [["SCN-001;calc", {}], ["$(bad)", {}], ["--help", {}], ["SCN-001", { alternative: "--help" }], ["SCN-001", { alternative: "x;calc" }], ["SCN-001", { documentHash: "not-a-hash" }], [null, {}]]) {
      const result = await readWalkthrough(root, "ut", scenario, fixtures.PROJECT_ID, options, () => assert.fail("must not execute"));
      assert.equal(result.status, "VALIDATION_INPUT_INVALID");
    }
  });

  it("rejects malformed or foreign validation documents and inconsistent counts", async () => {
    for (const payload of ["null", "[]", "not JSON", JSON.stringify(data.overview({ project_id: "foreign" })), JSON.stringify(data.overview({ candidate_count: 7 })), JSON.stringify(data.overview({ hypotheses: [null] })), JSON.stringify(data.overview({ candidates: [{ key: "bad;command", title: "bad" }] })), JSON.stringify(data.overview({ outcomes: [data.outcome({ session_kind: "OWNER_CONFIRMED" })] }))]) {
      const result = await readValidation(root, "ut", fixtures.PROJECT_ID, {}, (_program, _args, _options, finish) => finish(null, payload, "private diagnostic"));
      assert.equal(result.status, "INVALID");
      assert.equal(result.answer, null);
    }
    for (const payload of [data.walkthrough({ project_id: "foreign" }), data.walkthrough({ scenario: data.node("REQ-001", "REQUIREMENT") }), data.walkthrough({ anchor_candidates: [data.node("ELM-001", "PROTOTYPE_ELEMENT", { key: "bad;command" })] }), data.walkthrough({ steps: [null] })]) {
      const result = await readWalkthrough(root, "ut", "SCN-001", fixtures.PROJECT_ID, {}, (_program, _args, _options, finish) => finish(null, JSON.stringify(payload), ""));
      assert.equal(result.status, "INVALID");
    }
  });

  it("returns known errors without publishing diagnostics and handles absent programs", async () => {
    for (const [error, stderr, status] of [[{ code: 2 }, 'private SQL diagnostic\n{"error":{"code":"FOLDER_NOT_VERIFIED"}}', "FOLDER_NOT_VERIFIED"], [{ code: 2 }, '{"error":{"code":"PRIVATE_ACCOUNT_VALUE"}}', "FAILED"], [{ code: "ENOENT" }, "secret path", "UNAVAILABLE"]]) {
      const result = await readValidation(root, "ut", fixtures.PROJECT_ID, {}, (_program, _args, _options, finish) => finish(error, "", stderr));
      assert.deepEqual(result, { status, answer: null });
    }
    assert.equal((await readValidation(root, "ut", fixtures.PROJECT_ID, {}, () => { throw new Error("private diagnostic"); })).status, "FAILED");
  });

  it("keeps candidates in closed requested details and preserves retired history without promoting synthetic results", () => {
    const answer = data.overview();
    for (const language of ["it", "en"]) {
      const html = renderPanel(readProject(root), { language, nonce: "test", validation: { status: "OK", source: "OFFLINE", answer } });
      assert.ok(html.includes(text(language, "validation.candidates")));
      assert.ok(html.includes('<details id="validation-candidates"><summary>'));
      assert.ok(!html.includes('<details id="validation-candidates" open'));
      for (const key of ["readOnly", "candidateNote", "retired", "sourceWithoutText", "state.TO_VERIFY", "session.SYNTHETIC_EXERCISE", "noPromotion", "omitted"]) {
        assert.ok(html.includes(escapeHtml(text(language, `validation.${key}`))), key);
      }
      assert.ok(html.includes("Owner question &lt;literal&gt;"));
      assert.ok(html.includes("Exact &lt;script&gt;bad()&lt;/script&gt;\nquoted &amp; text"));
      assert.ok(html.includes(data.SOURCE_HASH));
      assert.ok(html.includes("L2–L3 · 7:50"));
      assert.ok(!html.includes("<script>bad()"));
      assert.ok(!/data-command="(?:save|record|revise|create)/.test(html));
    }
  });

  it("preserves previous hypothesis versions, disjoint human and synthetic outcomes and disagreement", () => {
    const old = data.hypothesis({ version_number: 1, current: false, state: "CONFIRMED", question: "Earlier question", outcomes: [] });
    const current = data.hypothesis({ state: "CONTESTED", conflicting_outcomes: true, partial_evidence: true, outcomes: [data.outcome({ session_kind: "HUMAN_SESSION", effective_status: "ACTIVE" }), data.outcome()] });
    const answer = data.overview({ hypotheses: [old, current], empirical_summary: { human_session_outcomes: 1, synthetic_exercise_outcomes: 0 } });
    for (const language of ["it", "en"]) {
      const html = renderPanel(readProject(root), { language, nonce: "test", validation: { answer } });
      for (const key of ["previous", "state.CONTESTED", "partial", "session.HUMAN_SESSION", "session.SYNTHETIC_EXERCISE"]) {
        assert.ok(html.includes(escapeHtml(text(language, `validation.${key}`))), key);
      }
      assert.ok(html.includes("Earlier question"));
      assert.ok(html.includes("HYP-001 · v1"));
      assert.ok(html.includes("HYP-001 · v2"));
    }
  });

  it("shows exact original walkthrough steps, scenario candidates and explicit missing step links", () => {
    const answer = data.walkthrough();
    for (const language of ["it", "en"]) {
      const html = renderPanel(readProject(root), { language, nonce: "test", walkthrough: { status: "OK", source: "OFFLINE", code: "SCN-001", answer } });
      assert.ok(html.includes("Original step &amp; text"));
      assert.ok(html.includes("Original expected outcome"));
      assert.ok(html.includes("SCR-001"));
      assert.ok(html.includes(data.HASH));
      for (const key of ["anchorNote", "linkToComplete", "softwareLimit", "questionOrTask"]) {
        assert.ok(html.includes(escapeHtml(text(language, `validation.${key}`))), key);
      }
      assert.ok(!html.includes("<iframe"));
      assert.ok(html.includes('label for="validation-scenario"'));
      assert.ok(html.includes('label for="validation-document-hash"'));
    }
  });

  it("offers Perché? only for exact references available in the local catalog", () => {
    const state = readProject(root);
    const origin = data.node("UT-claim", "USER_TWIN_CLAIM");
    state.why.items = [origin, data.node("SCN-001")];
    const html = renderPanel(state, { language: "it", nonce: "test", validation: { answer: data.overview() }, walkthrough: { answer: data.walkthrough() } });
    assert.ok(html.includes(`data-command="why" data-code="${origin.key}"`));
    assert.ok(!html.includes(`data-command="why" data-code="${data.node("ALT-001", "DESIGN_ALTERNATIVE").key}"`));
    assert.ok(html.includes(`value="${data.node("SCN-001").key}"`));
  });

  it("defines every validation label in both locales without exposing raw message keys", () => {
    const keys = Object.keys(MESSAGES.en).filter((key) => key.startsWith("validation."));
    assert.ok(keys.length > 40);
    for (const key of keys) {
      assert.ok(Object.hasOwn(MESSAGES.it, key), key);
      assert.notEqual(text("it", key), key);
      assert.notEqual(text("en", key), key);
    }
  });

  it("reads hypothesis and outcome provenance in Perché? without turning an outcome into claim support", () => {
    const source = { id: "source-id", version: 2, title: "Exact source", status: "RETIRED", limitations: "Synthetic software fixture" };
    const record = data.outcome();
    const target = data.node("HVO-001", "VALIDATION_OUTCOME", { title: "REFUTED", current: false, display_status: "UNKNOWN", citations: [{ citation: record.citation, source, status: "RETIRED", session_kind: "SYNTHETIC_EXERCISE" }], declared_context: { outcome: record, effective_status: "RETIRED" } });
    const answer = { target, summary: { upstream_count: 0, downstream_count: 0, complete_to_twin: false, complete_to_evidence: false, all_paths_complete: false }, upstream: [], downstream: [], links: [], gaps: [], human_validation: [], limits: [], declared_context: target.declared_context };
    for (const language of ["it", "en"]) {
      const html = renderPanel(readProject(root), { language, nonce: "test", why: { answer } });
      assert.ok(html.includes(text(language, "validation.state.REFUTED")));
      assert.ok(html.includes(text(language, "validation.retired")));
      assert.ok(html.includes(text(language, "validation.session.SYNTHETIC_EXERCISE")));
      assert.ok(html.includes("Exact &lt;script&gt;bad()&lt;/script&gt;"));
      assert.ok(!html.includes("SUPPORTS"));
      assert.ok(!html.includes("HUMAN_VALIDATED"));
    }
  });
});
