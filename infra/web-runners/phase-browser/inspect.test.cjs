"use strict";
const test = require("node:test");
const assert = require("node:assert/strict");
const { runInNewContext } = require("node:vm");
const { createHash } = require("node:crypto");
const { canonical, parseInput, validateJob, artifact, createEvents, requestDecision,
  actionResult, executeActions, isolatedAxe, isolatedDom, inspectScreen, VIEWPORTS } = require("./inspect.cjs");
const sha = value => createHash("sha256").update(value).digest("hex");
function sign(job) {
  delete job.request.content_hash;
  job.request.content_hash = sha(canonical(job.request));
  delete job.job_content_hash;
  job.job_content_hash = sha(canonical(job));
  return job;
}
function job() {
  return sign({ schema_version: 1, operation_id: "a".repeat(32),
    execution_attempt_id: "12345678-1234-4123-8123-123456789abc", harness_sha256: "b".repeat(64),
    request: { source_revision_content_hash: "c".repeat(64), source_tree_hash: "d".repeat(64),
      runner_image_digest: "e".repeat(64), base_url: "http://127.0.0.1:4173",
      routes: [{ route_id: "root", path: "/" }], policy: { maximum_routes: 5,
        maximum_console_messages_per_route: 100, maximum_failed_requests_per_route: 100,
        maximum_accessibility_findings_per_route: 200 } },
    viewports: VIEWPORTS, interactions: [] });
}
function actions() {
  return [{ kind: "click", selector: "button", value: null },
    { kind: "expect_text", selector: "output", value: "1" },
    { kind: "press", selector: "button", value: "Enter" },
    { kind: "expect_text", selector: "output", value: "2" }];
}
test("strict input rejects malformed UTF8, duplicate keys and over-budget input", () => {
  assert.deepEqual(parseInput(Buffer.from(canonical(job()))), job());
  for (const input of [Buffer.from([0xff]), Buffer.from('{"x":1,"x":2}'), Buffer.alloc(65537)]) {
    assert.throws(() => parseInput(input));
  }
});
test("all execution-sensitive fields are hash bound", () => {
  const value = job(); assert.equal(validateJob(value).origin, value.request.base_url);
  value.operation_id = "f".repeat(32); assert.throws(() => validateJob(value), /JOB_HASH/);
  const other = job(); other.request.content_hash = "0".repeat(64);
  delete other.job_content_hash; other.job_content_hash = sha(canonical(other));
  assert.throws(() => validateJob(other), /REQUEST_HASH/);
});
test("unknown fields and false integer values fail closed", () => {
  for (const mutate of [j => j.extra = true, j => j.schema_version = true,
    j => j.request.policy.maximum_routes = 6, j => j.request.policy.maximum_console_messages_per_route = 101,
    j => j.request.policy.maximum_accessibility_findings_per_route = true,
    j => j.viewports = [{ name: "wide", width: 1280, height: 800 }]]) {
    const value = job(); mutate(value); assert.throws(() => validateJob(sign(value)));
  }
});
test("string identity fields cannot coerce arrays into valid digests", () => {
  for (const mutate of [j => j.operation_id = [j.operation_id],
    j => j.execution_attempt_id = [j.execution_attempt_id], j => j.harness_sha256 = [j.harness_sha256],
    j => j.request.source_tree_hash = [j.request.source_tree_hash]]) {
    const value = job(); mutate(value); assert.throws(() => validateJob(sign(value)), /IDENTITY/);
  }
});
test("only canonical local route paths and root-first max-five grid are accepted", () => {
  for (const path of ["//evil.test/", "/../secret", "/%2e%2e/secret", "/a\\b", "/%0a", "/x#fragment"]) {
    const value = job(); value.request.routes.push({ route_id: "other", path });
    assert.throws(() => validateJob(sign(value)), /ROUTE/);
  }
  const value = job(); value.request.base_url = "http://example.com:4173";
  assert.throws(() => validateJob(sign(value)), /ORIGIN/);
});
test("interaction plans require independently checked pointer and keyboard operations", () => {
  const value = job(); value.interactions = [{ route_id: "root", actions: actions() }];
  assert.equal(validateJob(sign(value)).interactions.size, 1);
  for (const bad of [actions().slice(0, 2), [actions()[0], actions()[2], actions()[3]],
    [...actions(), { kind: "evaluate", selector: "body", value: "evil" }]]) {
    value.interactions[0].actions = bad;
    assert.throws(() => validateJob(sign(value)), /INTERACTION|ACTION/);
  }
});
test("artifact envelopes retain binary content and reject overflow", () => {
  const bytes = Buffer.from([0, 255, 7]); const value = artifact(bytes);
  assert.deepEqual(Buffer.from(value.content, "base64"), bytes);
  assert.equal(value.sha256, sha(bytes));
  assert.throws(() => artifact(Buffer.alloc(2 * 1024 * 1024 + 1)), /ARTIFACT_LIMIT/);
});
test("events preserve errors and make truncation an explicit overflow", () => {
  const events = createEvents(job().request.policy);
  events.console("error", "failure", { url: "http://127.0.0.1:4173/", lineNumber: 2, columnNumber: 3 });
  events.pageError("uncaught");
  for (let i = 0; i < 101; i++) events.failed("GET", "/x", "connection lost");
  assert.equal(events.value.console_messages[0].level, "ERROR");
  assert.deepEqual(events.value.page_errors, ["uncaught"]);
  assert.equal(events.value.failed_requests.length, 100);
  assert.equal(events.value.overflow, true);
  const large = createEvents(job().request.policy); large.pageError("x".repeat(2049));
  assert.equal(large.value.overflow, true);
});
test("event byte budget bounds escaped text across every category", () => {
  const events = createEvents(job().request.policy);
  for (let i = 0; i < 100; i++) {
    events.console("error", "\\".repeat(2048), { url: "\\".repeat(2048) });
    events.pageError("\\".repeat(2048));
    events.failed("GET", "/" + "x".repeat(511), "\\".repeat(2048));
    events.blocked("EXTERNAL_REQUEST", "\\".repeat(2048));
  }
  assert.ok(Buffer.byteLength(canonical(events.value)) <= 1536 * 1024);
  assert.equal(events.value.overflow, true);
});
test("request policy allows static assets but blocks external, redirect and undeclared navigation", () => {
  const spec = validateJob(job());
  assert.equal(requestDecision(spec, "http://127.0.0.1:4173/app.js", false, false), null);
  assert.equal(requestDecision(spec, "http://127.0.0.1:4173/", true, false), null);
  for (const [url, main, redirect] of [["https://example.com/", false, false],
    ["file:///tmp/secret", true, false], ["http://127.0.0.1:4173/admin", true, false],
    ["http://127.0.0.1:4173/", true, true]]) {
    assert.ok(requestDecision(spec, url, main, redirect));
  }
});
test("failed assertion stops all following actions without inventing success", async () => {
  const page = { locator: () => ({ click: async () => {}, innerText: async () => "wrong",
    press: async () => assert.fail("must not press after failed assertion") }) };
  const result = await executeActions(page, actions());
  assert.deepEqual(result.map(item => item.status), ["PASSED", "FAILED", "NOT_RUN", "NOT_RUN"]);
  assert.equal(result[1].failure_code, "TEXT_ASSERTION_FAILED");
});
test("locator absence is distinct from observed assertion mismatch", async () => {
  const page = { locator: () => ({ innerText: async () => { throw Error("missing"); } }) };
  assert.equal((await actionResult(page, actions()[1], 0)).failure_code, "TEXT_ASSERTION_READ_FAILED");
});
test("axe runs in isolated execution context and preserves violations", async () => {
  const calls = [];
  const axe = { version: "4.13.0", source: "trusted axe source" };
  const body = JSON.stringify({ testEngine: { version: axe.version }, violations: [{ id: "label" }] });
  const cdp = { send: async (method, params) => {
    calls.push([method, params]);
    if (method === "Page.getFrameTree") return { frameTree: { frame: { id: "frame" } } };
    if (method === "Page.createIsolatedWorld") return { executionContextId: 42 };
    if (params.expression === axe.source) return { result: {} };
    return { result: { value: body } };
  } };
  assert.deepEqual(JSON.parse(await isolatedAxe(cdp, axe)), JSON.parse(body));
  assert.equal(calls[1][1].grantUniveralAccess, false);
  assert.ok(calls.filter(([method]) => method === "Runtime.evaluate").every(([, p]) => p.contextId === 42));
});
test("axe exception cannot become an empty successful report", async () => {
  const cdp = { send: async method => method === "Page.getFrameTree" ?
    { frameTree: { frame: { id: "frame" } } } : method === "Page.createIsolatedWorld" ?
      { executionContextId: 3 } : { exceptionDetails: { text: "injection failed" } } };
  await assert.rejects(isolatedAxe(cdp, { source: "trusted", version: "4.13.0" }), /AXE/);
});
function fakeContext({ interactive = false, navigateFails = false, axeFails = false } = {}) {
  const handlers = {}; let closed = false;
  const page = { setDefaultTimeout() {}, on(name, fn) { handlers[name] = fn; },
    url: () => "http://127.0.0.1:4173/", mainFrame: () => "main",
    goto: async () => { if (navigateFails) throw Error("navigation"); return { status: () => 200 }; },
    screenshot: async () => Buffer.from("png"),
    locator: () => ({ click: async () => {}, press: async () => {}, innerText: async () => "1" }) };
  const cdp = { send: async (method, params) => {
    if (method === "Browser.getBrowserCommandLine") return { arguments: ["--enable-automation"] };
    if (method === "Page.getFrameTree") return { frameTree: { frame: { id: "frame" } } };
    if (method === "Page.createIsolatedWorld") return { executionContextId: 42 };
    if (method === "DOM.getDocument") return { root: { nodeType: 9, children: [] } };
    if (params?.expression === "trusted") return { result: {} };
    if (params?.expression.includes("axe.run")) {
      if (axeFails) return { exceptionDetails: { text: "failed" } };
      return { result: { value: JSON.stringify({ testEngine: { version: "4.13.0" }, violations: [] }) } };
    }
    return { result: { value: JSON.stringify({ html: "<!doctype html><html><body>ok</body></html>", interactive_controls: interactive ? 1 : 0 }) } };
  }, detach: async () => {} };
  return { page, handlers, get closed() { return closed; },
    route: async () => {}, routeWebSocket: async () => {}, on() {}, newPage: async () => page,
    newCDPSession: async () => cdp, close: async () => { closed = true; } };
}
test("interactive DOM without plan fails while preserving screenshot DOM and axe", async () => {
  const context = fakeContext({ interactive: true });
  const result = await inspectScreen(context, validateJob(job()), job().request.routes[0], VIEWPORTS[0],
    { source: "trusted", version: "4.13.0" });
  assert.equal(result.status, "COLLECTED");
  assert.equal(result.interaction_status, "FAILED");
  assert.ok(result.failure_codes.includes("INTERACTION_PLAN_REQUIRED"));
  assert.ok(result.screenshot && result.dom && result.axe && result.events);
});
test("navigation and axe failures are explicit while recoverable artifacts survive", async () => {
  for (const options of [{ navigateFails: true }, { axeFails: true }]) {
    const context = fakeContext(options);
    const result = await inspectScreen(context, validateJob(job()), job().request.routes[0], VIEWPORTS[0],
      { source: "trusted", version: "4.13.0" });
    assert.ok(result.failure_codes.length > 0);
    assert.ok(result.events);
    if (options.axeFails) { assert.equal(result.axe, null); assert.equal(result.status, "FAILED"); }
  }
});
test("controls appearing during capture cannot retain NOT_APPLICABLE", async () => {
  const context = fakeContext(); const original = context.newCDPSession; let count = 0;
  context.newCDPSession = async page => {
    const cdp = await original(page); const send = cdp.send;
    cdp.send = async (method, params) => {
      if (params?.expression?.includes("document.documentElement")) return { result: { value:
        JSON.stringify({ html: "<html><body><button>ready</button></body></html>", interactive_controls: count++ === 0 ? 0 : 1 }) } };
      return send(method, params);
    }; return cdp;
  };
  const result = await inspectScreen(context, validateJob(job()), job().request.routes[0], VIEWPORTS[0], { source: "trusted", version: "4.13.0" });
  assert.equal(result.interactive_controls, 1);
  assert.equal(result.interaction_status, "FAILED");
  assert.ok(result.failure_codes.includes("INTERACTION_PLAN_REQUIRED"));
});
test("popup main document is blocked before request continuation", async () => {
  const context = fakeContext(); let intercept, aborted = false;
  context.route = async (_, callback) => { intercept = callback; };
  context.page.goto = async () => {
    await intercept({ request: () => ({ url: () => "http://127.0.0.1:4173/",
      frame: () => ({ page: () => ({}) }), isNavigationRequest: () => true, redirectedFrom: () => null }),
    abort: async () => { aborted = true; }, continue: async () => assert.fail("popup request continued") });
    return { status: () => 200 };
  };
  const result = await inspectScreen(context, validateJob(job()), job().request.routes[0], VIEWPORTS[0], { source: "trusted", version: "4.13.0" });
  assert.equal(aborted, true);
  const events = JSON.parse(Buffer.from(result.events.content, "base64"));
  assert.equal(events.blocked_requests[0].kind, "POPUP");
});
function domElement(tag, { control = false, shadowRoot = null, hidden = false, disabled = false } = {}) {
  return { localName: tag, tagName: tag.toUpperCase(), shadowRoot, disabled,
    matches: () => control, getAttribute: () => null, getClientRects: () => hidden ? [] : [{}] };
}
function domRoot(elements) {
  return { querySelectorAll: selector => selector === "*" ? elements : elements.filter(element => element.matches(selector)) };
}
async function inspectDomFixture(elements, documentTree = { nodeType: 9, children: [] }) {
  const document = { ...domRoot(elements), doctype: {}, documentElement: { outerHTML: "<html><body>fixture</body></html>" } };
  const cdp = { send: async (method, params) => {
    if (method === "Page.getFrameTree") return { frameTree: { frame: { id: "frame" } } };
    if (method === "Page.createIsolatedWorld") return { executionContextId: 42 };
    if (method === "DOM.getDocument") {
      assert.deepEqual(params, { depth: -1, pierce: true });
      if (documentTree instanceof Error) throw documentTree;
      return { root: documentTree };
    }
    return { result: { value: runInNewContext(params.expression, { document, TextEncoder,
      getComputedStyle: () => ({ visibility: "visible", display: "block" }) }) } };
  } };
  return isolatedDom(cdp);
}
test("DOM control inspection descends through nested open shadow roots", async () => {
  const nested = domElement("x-inner", { shadowRoot: domRoot([domElement("button", { control: true })]) });
  const outer = domElement("x-outer", { shadowRoot: domRoot([nested, domElement("input", { control: true, disabled: true })]) });
  const result = await inspectDomFixture([domElement("p"), outer]);
  assert.equal(result.interactive_controls, 1);
  assert.ok(result.html.includes("<html>"));
});
test("opaque frames and closed custom-element surfaces remain unobserved", async () => {
  for (const tag of ["iframe", "frame", "object", "embed", "x-closed"]) {
    const result = await inspectDomFixture([domElement(tag)]);
    assert.equal(result.interactive_controls, null, tag);
    assert.ok(result.html.includes("<html>"));
  }
});
test("ordinary static DOM remains noninteractive without requiring a plan", async () => {
  assert.equal((await inspectDomFixture([domElement("main"), domElement("p")])).interactive_controls, 0);
});
test("closed shadow root on an ordinary div cannot be declared noninteractive", async () => {
  const tree = { nodeType: 9, children: [{ nodeType: 1, nodeName: "DIV", shadowRoots: [
    { nodeType: 11, shadowRootType: "closed", children: [{ nodeType: 1, nodeName: "BUTTON" }] }
  ] }] };
  const result = await inspectDomFixture([domElement("div")], tree);
  assert.equal(result.interactive_controls, null);
  assert.ok(result.html.includes("<html>"));
});
test("native user-agent shadow roots do not hide observed input controls", async () => {
  const tree = { nodeType: 9, children: [{ nodeType: 1, nodeName: "INPUT", shadowRoots: [
    { nodeType: 11, shadowRootType: "user-agent", children: [] }
  ] }] };
  assert.equal((await inspectDomFixture([domElement("input", { control: true })], tree)).interactive_controls, 1);
});
test("failed privileged DOM inspection retains HTML without claiming noninteractive", async () => {
  const result = await inspectDomFixture([domElement("div")], Error("CDP unavailable"));
  assert.equal(result.interactive_controls, null);
  assert.ok(result.html.includes("<html>"));
});
test("unobservable interactive surfaces fail explicitly and cannot execute a misleading plan", async () => {
  const context = fakeContext(); const original = context.newCDPSession;
  context.page.locator = () => assert.fail("interaction must not run on an uninspected surface");
  context.newCDPSession = async page => {
    const cdp = await original(page), send = cdp.send;
    cdp.send = async (method, params) => params?.expression?.includes("document.documentElement") ?
      { result: { value: JSON.stringify({ html: "<html><iframe></iframe></html>", interactive_controls: null }) } } : send(method, params);
    return cdp;
  };
  const value = job(); value.interactions = [{ route_id: "root", actions: actions() }];
  const result = await inspectScreen(context, validateJob(sign(value)), value.request.routes[0], VIEWPORTS[0], { source: "trusted", version: "4.13.0" });
  assert.equal(result.interactive_controls, null);
  assert.equal(result.interaction_status, "FAILED");
  assert.deepEqual(result.actions.map(action => action.status), ["NOT_RUN", "NOT_RUN", "NOT_RUN", "NOT_RUN"]);
  assert.ok(result.failure_codes.includes("INTERACTION_INSPECTION_FAILED"));
  assert.ok(result.dom && result.screenshot && result.axe);
});
