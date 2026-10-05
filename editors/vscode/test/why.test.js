"use strict";

const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const { after, before, describe, it } = require("node:test");
const fixtures = require("./fixtures");
const { readProject } = require("../src/project");
const { renderPanel } = require("../src/view");
const { text } = require("../src/messages");
const { readWhyAnswer, validSelector } = require("../src/why");

function node(code, extra = {}) {
  return {
    key: `REQUIREMENT:${code}:3:hash:requirements`,
    code,
    kind: "REQUIREMENT",
    title: `Title ${code}`,
    display_status: "UNKNOWN",
    reference: {
      artifact_id: "requirement-id",
      version_number: 3,
      content_hash: "exact-hash",
    },
    current: true,
    rationale: null,
    citations: [],
    validation_required: false,
    gaps: [],
    declared_context: { perspectives: [] },
    ...extra,
  };
}

function answer(extra = {}) {
  return {
    kind: "orchestwin.why-answer",
    schema_version: 1,
    project_id: fixtures.PROJECT_ID,
    target: node("REQ-001"),
    summary: {
      upstream_count: 0,
      downstream_count: 0,
      complete_to_twin: false,
      complete_to_evidence: false,
      all_paths_complete: false,
      stop_reasons: [],
    },
    upstream: [],
    downstream: [],
    links: [],
    gaps: [],
    human_validation: [],
    declared_context: { perspectives: [] },
    limits: [],
    ...extra,
  };
}

function writeCatalog(root, nodes = [node("REQ-001")], extra = {}) {
  const manifest = fixtures.readJson(root, "orchestwin/orchestwin.json");
  manifest.why = { document: "traceability/why.json", schema_version: 1 };
  fixtures.writeJson(root, "orchestwin/orchestwin.json", manifest);
  fixtures.writeJson(root, "orchestwin/traceability/why.json", {
    kind: "orchestwin.why",
    schema_version: 1,
    project_id: fixtures.PROJECT_ID,
    nodes,
    links: [],
    omitted_sections: [],
    ...extra,
  });
}

describe("portable why in the editor", () => {
  let base;
  let counter = 0;
  before(() => {
    base = fixtures.makeTemporaryFolder();
  });
  after(() => {
    fixtures.removeFolder(base);
  });
  function project() {
    counter += 1;
    return fixtures.writeCompleteProject(
      path.join(base, `why ${counter}`),
      "new",
    );
  }

  it("offers exact context selectors for repeated codes and historical versions", () => {
    const root = project();
    const older = node("ELM-001", {
      key: "ELEMENT:one:1:old:alternative-one",
      current: false,
      reference: {
        artifact_id: "element-one",
        version_number: 1,
        content_hash: "old",
      },
    });
    const other = node("ELM-001", { key: "ELEMENT:two:2:new:alternative-two" });
    writeCatalog(root, [older, other]);
    const state = readProject(root);
    assert.equal(state.why.available, true);
    assert.deepEqual(
      state.why.items.map((item) => item.key),
      [older.key, other.key],
    );
    for (const language of ["it", "en"]) {
      const html = renderPanel(state, { language, nonce: "test" });
      assert.ok(html.includes(`value="${older.key}"`));
      assert.ok(html.includes(`value="${other.key}"`));
      assert.ok(html.includes(text(language, "why.historical")));
      assert.ok(html.includes('label for="why-selector"'));
      assert.ok(html.includes('label for="why-code"'));
    }
  });

  it("keeps legacy folders usable without inventing a catalog", () => {
    const state = readProject(project());
    assert.equal(state.why.problem, "MISSING");
    const html = renderPanel(state, { language: "it", nonce: "test" });
    assert.ok(html.includes(text("it", "why.legacy")));
    assert.ok(html.includes('id="why-form"'));
  });

  it("rejects foreign projects, duplicate keys and redirected manifest paths", () => {
    for (const extra of [
      { project_id: "foreign-project" },
      { nodes: [node("REQ-001"), node("REQ-001")] },
    ]) {
      const root = project();
      writeCatalog(root, undefined, extra);
      assert.equal(readProject(root).why.problem, "INVALID");
    }
    const root = project();
    const manifest = fixtures.readJson(root, "orchestwin/orchestwin.json");
    manifest.why = { document: "../../foreign.json", schema_version: 1 };
    fixtures.writeJson(root, "orchestwin/orchestwin.json", manifest);
    assert.equal(readProject(root).why.problem, "INVALID");
  });

  it("rejects a catalog folder junction outside the linked knowledge folder", () => {
    const root = project();
    const outside = path.join(base, "outside");
    fs.mkdirSync(outside);
    fixtures.writeJson(outside, "why.json", {
      kind: "orchestwin.why",
      schema_version: 1,
      project_id: fixtures.PROJECT_ID,
      nodes: [node("REQ-001")],
    });
    const manifest = fixtures.readJson(root, "orchestwin/orchestwin.json");
    manifest.why = { document: "traceability/why.json", schema_version: 1 };
    fixtures.writeJson(root, "orchestwin/orchestwin.json", manifest);
    fs.symlinkSync(
      outside,
      path.join(root, "orchestwin", "traceability"),
      "junction",
    );
    assert.equal(readProject(root).why.problem, "INVALID");
  });

  it("delegates explanation and verification to ut without a shell, login or network", async () => {
    const root = project();
    const expected = answer();
    let calls = 0;
    const result = await readWhyAnswer(
      root,
      '"C:/Tools with spaces/ut.exe"',
      "REQ-001",
      fixtures.PROJECT_ID,
      (program, args, options, finish) => {
        calls += 1;
        assert.equal(program, "C:/Tools with spaces/ut.exe");
        assert.deepEqual(args, ["why", "REQ-001", "--offline", "--json"]);
        assert.equal(options.cwd, root);
        assert.equal(options.shell, false);
        assert.equal(options.windowsHide, true);
        assert.equal(options.timeout, 30000);
        finish(null, JSON.stringify(expected), "Offline snapshot\n");
      },
    );
    assert.equal(calls, 1);
    assert.deepEqual(result, { status: "OK", answer: expected });
  });

  it("rejects shell metacharacters before invoking any program", async () => {
    for (const code of [
      "REQ-001;calc",
      "$(whoami)",
      "REQ-001\n",
      "REQ-001 more",
      "",
      null,
      "x".repeat(2049),
    ]) {
      assert.equal(validSelector(code), false);
      const result = await readWhyAnswer(
        base,
        "ut",
        code,
        fixtures.PROJECT_ID,
        () => {
          throw new Error("must not execute");
        },
      );
      assert.equal(result.status, "WHY_CODE_INVALID");
    }
    assert.equal(validSelector("UT-12345678-v3:persona.needs"), true);
  });

  it("returns explicit ambiguity candidates and does not expose stderr contents", async () => {
    const keys = [
      "ELEMENT:one:1:hash:alternative-one",
      "ELEMENT:two:1:hash:alternative-two",
    ];
    const result = await readWhyAnswer(
      base,
      "ut",
      "ELM-001",
      fixtures.PROJECT_ID,
      (_program, _args, _options, finish) => {
        finish(
          { code: 2 },
          "",
          `private diagnostic\n${JSON.stringify({ error: { code: "WHY_CODE_AMBIGUOUS", candidates: [...keys, "bad;command"] } })}\n`,
        );
      },
    );
    assert.deepEqual(result, {
      status: "WHY_CODE_AMBIGUOUS",
      answer: null,
      candidates: keys,
    });
    assert.ok(!JSON.stringify(result).includes("private diagnostic"));
  });

  it("rejects malformed or foreign CLI answers", async () => {
    for (const payload of [
      "not json",
      "null",
      "[]",
      JSON.stringify(answer({ project_id: "foreign-project" })),
      JSON.stringify(answer({ links: null })),
      JSON.stringify(answer({ links: [null] })),
      JSON.stringify({ kind: "orchestwin.why" }),
    ]) {
      const result = await readWhyAnswer(
        base,
        "ut",
        "REQ-001",
        fixtures.PROJECT_ID,
        (_program, _args, _options, finish) => finish(null, payload, ""),
      );
      assert.equal(result.answer, null);
      assert.ok(["INVALID", "FAILED"].includes(result.status));
    }
  });

  it("renders preserved quotes, model rationale, exact references and epistemic states in both languages", () => {
    const root = project();
    const quote = "Literal <script>bad()</script>\nsecond line & <tag>";
    const claim = node("UT-12345678-v3:user_twin.goals", {
      key: "USER_TWIN_CLAIM:twin:3:twinhash:goals",
      kind: "USER_TWIN_CLAIM",
      title: "Goal claim",
      display_status: "CONTESTED",
      current: false,
      rationale: {
        text: "Generated <img src=x onerror=bad()>",
        origin: "MODEL",
        version_number: 3,
        content_hash: "rationale-hash",
      },
      citations: [
        {
          field: "goals",
          effect: "SUPPORTS",
          status: "RETIRED",
          applicable: false,
          source: {
            title: "Source title",
            limitations: "Synthetic fixture; no real participants",
            status: "RETIRED",
          },
          citation: {
            source_id: "source-id",
            source_version: 2,
            content_hash: "source-hash",
            quote,
            start: 4,
            end: 4 + quote.length,
            start_line: 2,
            end_line: 3,
          },
        },
      ],
      validation_required: true,
    });
    const evidence = answer({
      target: claim,
      upstream: [
        node("NED-001", { display_status: "HYPOTHESIZED" }),
        node("UT-12345678-v3", { display_status: "EVIDENCED" }),
      ],
      downstream: [
        node("REQ-002", { display_status: "INFERRED" }),
        node("REQ-003"),
      ],
      summary: {
        upstream_count: 2,
        downstream_count: 2,
        complete_to_twin: true,
        complete_to_evidence: false,
        all_paths_complete: false,
        stop_reasons: ["SOURCE_RETIRED"],
      },
      human_validation: [claim],
      gaps: [
        {
          code: "SOURCE_RETIRED",
          node_key: claim.key,
          related_code: "EVD-001",
          stage: "evidence",
        },
      ],
      limits: ["SOURCE_RETIRED"],
    });
    for (const language of ["en", "it"]) {
      const html = renderPanel(readProject(root), {
        language,
        nonce: "test",
        why: { code: claim.key, answer: evidence },
      });
      for (const key of [
        "why.title",
        "why.upstream",
        "why.downstream",
        "why.model",
        "why.validation",
        "why.gaps",
        "why.retired",
        ...[
          "EVIDENCED",
          "INFERRED",
          "HYPOTHESIZED",
          "CONTESTED",
          "UNKNOWN",
        ].map((status) => `why.${status}`),
      ]) {
        assert.ok(html.includes(text(language, key)), `${language}: ${key}`);
      }
      for (const value of [
        "exact-hash",
        "source-hash",
        "rationale-hash",
        "L2–L3",
        "&lt;script&gt;bad()&lt;/script&gt;\nsecond line &amp; &lt;tag&gt;",
        "&lt;img src=x onerror=bad()&gt;",
      ]) {
        assert.ok(html.includes(value), value);
      }
      assert.ok(!html.includes("<script>bad()</script>"));
      assert.ok(!html.includes("<img src=x"));
      assert.ok(html.includes('data-command="why" data-code='));
      assert.ok(html.includes("default-src 'none'"));
    }
    assert.equal(claim.citations[0].citation.quote, quote);
  });

  it("shows generation perspectives as context and keeps unmotivated owner choices explicit", () => {
    const root = project();
    const context = {
      perspectives: [{ key: "ACCESSIBILITY", title: "Accessibility" }],
      team_reference: {
        artifact_id: "exact-team",
        version_number: 2,
        content_hash: "team-hash",
      },
    };
    const result = answer({
      target: node("REQ-010", { rationale: null, declared_context: context }),
      declared_context: context,
      gaps: [
        {
          code: "MISSING_NEED",
          node_key: "req",
          related_code: null,
          stage: "requirements",
        },
      ],
    });
    const html = renderPanel(readProject(root), {
      language: "it",
      nonce: "test",
      why: { answer: result },
    });
    assert.ok(html.includes(text("it", "why.context")));
    assert.ok(html.includes("Accessibility"));
    assert.ok(html.includes("team-hash"));
    assert.ok(html.includes(text("it", "why.noRationale")));
    assert.ok(!html.includes(text("it", "why.model")));
    const finding = node("UTF-001", {
      kind: "SYNTHETIC_FINDING",
      display_status: "INFERRED",
      validation_required: true,
      declared_context: {
        model_config_ref: "model-ref",
        prompt_version_ref: "prompt-v2",
      },
    });
    const synthetic = renderPanel(readProject(root), {
      language: "en",
      nonce: "test",
      why: { answer: answer({ target: finding, human_validation: [finding] }) },
    });
    assert.ok(synthetic.includes(text("en", "why.synthetic")));
    assert.ok(synthetic.includes("model-ref"));
    assert.ok(synthetic.includes("prompt-v2"));
  });

  it("starts with a brief rationale and keeps the complete rationale and mockup references in closed details", () => {
    const root = project();
    const rationale = "r".repeat(240) + " full rationale tail";
    const result = answer({
      target: node("ELM-001", {
        rationale: {
          text: rationale,
          origin: "MODEL",
          version_number: 3,
          content_hash: "rationale-hash",
        },
        declared_context: {
          base_reference: {
            artifact_id: "exact-base",
            version_number: 2,
            content_hash: "base-hash",
          },
          audit_reference: {
            generation_id: "exact-generation",
            content_hash: "audit-hash",
            request_content_hash: "request-hash",
          },
          mockup: {
            prototype_id: "prototype",
            alternative_id: "alternative-one",
            screen_code: "SCR-001",
            source: "LATEST",
            document_hashes: { "screen.html": "document-hash" },
          },
        },
      }),
    });
    const html = renderPanel(readProject(root), {
      language: "en",
      nonce: "test",
      why: { answer: result },
    });
    const heading = `<details><summary>${text("en", "why.details")}</summary>`;
    assert.ok(html.includes(heading));
    const synopsis = html.slice(0, html.indexOf(heading));
    assert.ok(synopsis.includes("r".repeat(240) + "…"));
    assert.ok(!synopsis.includes("full rationale tail"));
    const details = html.slice(html.indexOf(heading));
    for (const expected of [
      rationale,
      "base-hash",
      "audit-hash",
      "request-hash",
      "document-hash",
      "exact-generation",
    ]) {
      assert.ok(details.includes(expected), expected);
    }
  });

  it("shows exact claim values and preserves unknown and abstained observations", () => {
    const root = project();
    for (const [value, included, excluded] of [
      [
        { kind: "TEXT", text: "Exact <claim>\nsecond line" },
        ["Exact &lt;claim&gt;\nsecond line"],
        ["<claim>"],
      ],
      [
        { kind: "ITEMS", items: ["First & item", "Second <item>"] },
        ["First &amp; item", "Second &lt;item&gt;"],
        ["Second <item>"],
      ],
      [
        { kind: "UNKNOWN", text: "must not appear" },
        [text("it", "why.UNKNOWN")],
        ["must not appear"],
      ],
      [
        {
          kind: "ABSTAINED",
          reason: "Reason <literal>",
          text: "must not appear",
        },
        [text("it", "why.abstained"), "Reason &lt;literal&gt;"],
        ["must not appear"],
      ],
    ]) {
      const result = answer({
        target: node("UT-12345678-v3:user_twin.goals", {
          kind: "USER_TWIN_CLAIM",
          display_status: "UNKNOWN",
          declared_context: { observation_value: value },
        }),
      });
      const html = renderPanel(readProject(root), {
        language: "it",
        nonce: "test",
        why: { answer: result },
      });
      for (const expected of included) {
        assert.ok(html.includes(expected), expected);
      }
      for (const forbidden of excluded) {
        assert.ok(!html.includes(forbidden), forbidden);
      }
    }
  });

  it("keeps an unavailable original text as a limit when the shared engine says the chain is complete", () => {
    const result = answer({
      summary: { upstream_count: 0, downstream_count: 0, complete_to_twin: true, complete_to_evidence: true, all_paths_complete: true, stop_reasons: [] },
      gaps: [{ code: "SOURCE_TEXT_UNAVAILABLE", node_key: "source", related_code: "EVD-001", stage: "evidence" }],
      limits: ["SOURCE_TEXT_UNAVAILABLE"],
    });
    const html = renderPanel(readProject(project()), { language: "en", nonce: "test", why: { answer: result } });
    assert.ok(!html.includes(`<h3>${text("en", "why.gaps")}</h3>`));
    assert.ok(html.includes(text("en", "why.gap.SOURCE_TEXT_UNAVAILABLE")));
    assert.ok(html.includes(`<h3>${text("en", "why.limits")}</h3>`));
  });
});

module.exports = { answer, node, writeCatalog };
