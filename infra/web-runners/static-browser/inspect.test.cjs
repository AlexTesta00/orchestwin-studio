"use strict";
const test = require("node:test");
const assert = require("node:assert/strict");
const { createHash } = require("node:crypto");
const { createServer } = require("node:http");
const { canonical, artifact, validateJob, staticHandler, actionResult } = require("./inspect.cjs");
const digest = value => createHash("sha256").update(value).digest("hex");
function job() {
  const bytes = Buffer.from("<!doctype html><html><button>Hello</button></html>");
  const value = { schema_version: 1,
    viewports: [{ name: "narrow", width: 390, height: 844 }, { name: "wide", width: 1280, height: 800 }],
    files: [{ path: "index.html", content_base64: bytes.toString("base64"), size_bytes: bytes.length,
      sha256: digest(bytes), media_type: "text/html" }],
    scenarios: [{ id: "test", route: "/", actions: [{ kind: "expect_text", selector: "button", value: "Hello" }] }] };
  return sign(value);
}
function sign(value) { delete value.job_content_hash; value.job_content_hash = digest(canonical(value)); return value; }
test("job hash is bound to all declared actions and source bytes", () => {
  const value = job(); assert.equal(validateJob(value).size, 1);
  value.scenarios[0].actions[0].value = "changed";
  assert.throws(() => validateJob(value), /JOB_HASH/);
});
test("bytes cannot contradict their content-addressed entry", () => {
  const value = job(); value.files[0].content_base64 = Buffer.from("different").toString("base64");
  assert.throws(() => validateJob(sign(value)), /FILE_BYTES/);
});
test("no arbitrary browser evaluation action is accepted", () => {
  const value = job(); value.scenarios[0].actions.push({ kind: "evaluate", selector: "body", value: "process.exit()" });
  assert.throws(() => validateJob(sign(value)), /ACTION_INVALID/);
});
test("source paths cannot address the host filesystem", () => {
  const value = job(); value.files[0].path = "../../secret.html";
  assert.throws(() => validateJob(sign(value)), /FILE_PATH/);
});
test("duplicate and hidden file paths are rejected", () => {
  const value = job(); value.files.push({ ...value.files[0] });
  assert.throws(() => validateJob(sign(value)), /FILE_PATH/);
  value.files = [{ ...value.files[0], path: ".private/file.html" }];
  assert.throws(() => validateJob(sign(value)), /FILE_PATH/);
});
test("artifact envelopes preserve exact binary bytes", () => {
  const data = Buffer.from([0, 255, 19]); const wrapped = artifact(data);
  assert.deepEqual(Buffer.from(wrapped.content, "base64"), data);
  assert.equal(wrapped.sha256, digest(data));
  assert.throws(() => artifact(Buffer.alloc(2 * 1024 * 1024 + 1)), /ARTIFACT_LIMIT/);
});
test("real static HTTP handler serves only submitted in-memory files", async () => {
  const sources = validateJob(job());
  const server = createServer(staticHandler(sources));
  await new Promise(resolve => server.listen(0, "127.0.0.1", resolve));
  const base = "http://127.0.0.1:" + server.address().port;
  try {
    assert.equal((await fetch(base + "/")).status, 200);
    assert.equal((await fetch(base + "/%ZZ")).status, 400);
    assert.equal((await fetch(base + "/.env")).status, 404);
    assert.equal((await fetch(base + "/etc/passwd")).status, 404);
    assert.equal((await fetch(base + "/", { method: "POST" })).status, 405);
    const head = await fetch(base + "/", { method: "HEAD" });
    assert.equal(head.status, 200); assert.equal(await head.text(), "");
  } finally {
    server.closeAllConnections(); await new Promise(resolve => server.close(resolve));
  }
});
test("declared actions operate through the locator port without eval", async () => {
  const calls = [];
  const locator = { click: async () => calls.push("click"), fill: async value => calls.push(value),
    press: async value => calls.push(value), innerText: async () => "Hello" };
  const page = { locator: () => locator };
  for (const action of [{ kind: "fill", selector: "input", value: "Ada" },
    { kind: "click", selector: "button", value: null }, { kind: "press", selector: "button", value: "Enter" },
    { kind: "expect_text", selector: "h1", value: "Hello" }]) {
    assert.equal((await actionResult(page, action, 0)).status, "PASSED");
  }
  assert.deepEqual(calls, ["Ada", "click", "Enter"]);
});
test("a failed assertion stays failed instead of being skipped", async () => {
  const page = { locator: () => ({ innerText: async () => "Other" }) };
  const result = await actionResult(page, { kind: "expect_text", selector: "h1", value: "Hello" }, 1);
  assert.equal(result.status, "FAILED"); assert.equal(result.failure_code, "TEXT_ASSERTION_FAILED");
});
test("a missing locator cannot count as the deliberate assertion mismatch", async () => {
  const page = { locator: () => ({ innerText: async () => { throw new Error("locator unavailable"); } }) };
  const result = await actionResult(page, { kind: "expect_text", selector: "#missing", value: "Expected" }, 0);
  assert.equal(result.status, "FAILED");
  assert.equal(result.failure_code, "TEXT_ASSERTION_READ_FAILED");
});
