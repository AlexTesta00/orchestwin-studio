"use strict";

const assert = require("node:assert/strict");
const path = require("node:path");
const { test } = require("node:test");
const fixtures = require("./fixtures");
const { readProject } = require("../src/project");
const { renderPanel } = require("../src/view");

test("reads exact evidence citations and escapes them in the panel without original bodies", () => {
  const base = fixtures.makeTemporaryFolder();
  try {
    const root = fixtures.writeCompleteProject(
      path.join(base, "evidence"),
      "new",
    );
    const manifest = fixtures.readJson(root, "orchestwin/orchestwin.json");
    manifest.research_evidence = {
      document: "twins/evidence.json",
      text: "twins/evidence.md",
    };
    fixtures.writeJson(root, "orchestwin/orchestwin.json", manifest);
    fixtures.writeJson(root, "orchestwin/twins/evidence.json", {
      kind: "orchestwin.research-evidence",
      schema_version: 1,
      project_id: fixtures.PROJECT_ID,
      evidence: [
        {
          id: "synthetic-source",
          version: 2,
          code: "EVD-001",
          title: "Synthetic source",
          limitations: "No real participants",
        },
      ],
      citations: [
        {
          twin_id: fixtures.HEAD_WAITER,
          twin_version: 3,
          field: "goals",
          effect: "SUPPORTS",
          status: "ACTIVE",
          citation: {
            source_id: "synthetic-source",
            source_version: 2,
            quote: "Literal <script>test</script>\nquote",
            start_line: 2,
            end_line: 3,
          },
        },
      ],
    });
    const state = readProject(root);
    const twin = state.twins.items.find(
      (item) => item.id === fixtures.HEAD_WAITER,
    );
    assert.equal(
      twin.evidence[0].quote,
      "Literal <script>test</script>\nquote",
    );
    assert.equal(twin.evidence[0].version, 2);
    for (const language of ["en", "it"]) {
      const html = renderPanel(state, {
        language,
        nonce: "0123456789abcdef0123456789abcdef",
        cspSource: "https://example.invalid",
        timeZone: "UTC",
      });
      assert.ok(html.includes("EVD-001 v2"));
      assert.ok(html.includes("&lt;script&gt;test&lt;/script&gt;"));
      assert.ok(!html.includes("<script>test</script>"));
      assert.ok(html.includes("No real participants"));
    }
  } finally {
    fixtures.removeFolder(base);
  }
});
