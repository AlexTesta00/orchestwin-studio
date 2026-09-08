"use strict";
const test = require("node:test");
const assert = require("node:assert/strict");
const { createHash } = require("node:crypto");
const { readFileSync } = require("node:fs");
const { runInNewContext } = require("node:vm");
const { payload, requireTrue } = require("./probe.cjs");

test("artifact envelope binds exact binary bytes", () => {
  const source = Buffer.from([0, 255, 17, 0]);
  const result = payload(source);
  assert.deepEqual(Buffer.from(result.content, "base64"), source);
  assert.equal(result.size_bytes, source.length);
  assert.equal(result.sha256, createHash("sha256").update(source).digest("hex"));
});
test("UTF-8 DOM text is preserved", () => {
  const text = "<html><p>è ✓</p></html>";
  const result = payload(text);
  assert.equal(Buffer.from(result.content, "base64").toString("utf8"), text);
});
test("oversized artifact is rejected instead of truncated", () => {
  assert.throws(() => payload(Buffer.alloc(2 * 1024 * 1024 + 1)), /ARTIFACT_TOO_LARGE/);
});
test("failed smoke condition throws", () => {
  assert.throws(() => requireTrue(false, "NOT_OBSERVED"), /NOT_OBSERVED/);
  assert.doesNotThrow(() => requireTrue(true, "unused"));
});

// Exercise the real run() up to its launch boundary, without Docker or Playwright.
// A captured launch is not evidence of browser execution or sandbox enforcement.
test("probe supplies the CDP prerequisite while preserving sandbox options", async () => {
  const launchStopped = new Error("LAUNCH_OPTIONS_CAPTURED");
  let captured;
  let launchCount = 0;
  let serverClosed = false;
  const server = {
    once() { return this; },
    listen(_port, _host, ready) { ready(); },
    close(done) { serverClosed = true; done(); },
  };
  function fixtureRequire(name) {
    if (name === "node:http") return { createServer: () => server };
    if (name === "playwright") {
      return { chromium: { launch: async options => {
        launchCount++;
        // Normalize the VM object's prototype for strict cross-context comparison.
        captured = JSON.parse(JSON.stringify(options));
        throw launchStopped;
      } } };
    }
    if (name === "playwright/package.json") return { version: "1.62.1" };
    if (name === "axe-core") return { version: "4.13.0" };
    return require(name);
  }
  const filename = require.resolve("./probe.cjs");
  const runProbe = runInNewContext(readFileSync(filename, "utf8") + "\nrun;", {
    require: fixtureRequire,
    module: { exports: {} },
    __dirname,
    Buffer,
    process: { argv: ["node", filename], getuid: () => 65532, version: process.version },
  }, { filename, timeout: 1000 });

  await assert.rejects(runProbe(), error => error === launchStopped);
  assert.equal(launchCount, 1, "a failed launch must not trigger an unsafe fallback");
  assert.equal(serverClosed, true, "the fixture server must be closed on failure");
  assert.deepEqual(captured, {
    headless: true,
    chromiumSandbox: true,
    timeout: 20000,
    args: ["--enable-automation"],
  });
});
