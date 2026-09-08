"use strict";
const test = require("node:test");
const assert = require("node:assert/strict");
const { createHash } = require("node:crypto");
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
