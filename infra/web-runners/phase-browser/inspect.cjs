/* Trusted browser evidence against an existing isolated application; never serves sources. */
"use strict";
const { createHash } = require("node:crypto");
const { createRequire } = require("node:module");
const MAX_INPUT = 65536, MAX_ARTIFACT = 2 * 1024 * 1024, MAX_OUTPUT = 32 * 1024 * 1024;
const VIEWPORTS = [{ name: "narrow", width: 390, height: 844 }, { name: "wide", width: 1280, height: 800 }];
const SHA = /^[0-9a-f]{64}$/, ID = /^[A-Za-z][A-Za-z0-9]*(?:[._-][A-Za-z0-9]+)*$/;
const ACTION_KEYS = new Set(["Enter", "Space", "Tab", "Escape", "ArrowLeft", "ArrowRight", "Home", "End"]);
function check(value, code) { if (!value) throw Error(code); }
function sha(value) { return createHash("sha256").update(value).digest("hex"); }
function sorted(value) {
  if (Array.isArray(value)) return value.map(sorted);
  if (value !== null && typeof value === "object") return Object.fromEntries(Object.keys(value).sort().map(k => [k, sorted(value[k])]));
  return value;
}
function canonical(value) { return JSON.stringify(sorted(value)); }
function shape(value, keys, code) {
  check(value && typeof value === "object" && !Array.isArray(value) &&
    canonical(Object.keys(value).sort()) === canonical([...keys].sort()), code);
}
function parseInput(bytes) {
  check(bytes.length > 0 && bytes.length <= MAX_INPUT, "INPUT_LIMIT");
  const text = new TextDecoder("utf-8", { fatal: true }).decode(bytes);
  const value = JSON.parse(text);
  check(canonical(value) === text.trim(), "INPUT_NOT_CANONICAL");
  return value;
}
function routePath(path) {
  if (typeof path !== "string" || !path || path.length > 512 || !path.startsWith("/") ||
      path.startsWith("//") || /[\\#\x00-\x20\x7f]/.test(path)) return false;
  try {
    const parsed = new URL(path, "http://127.0.0.1:4173");
    const decoded = decodeURIComponent(parsed.pathname);
    return parsed.pathname + parsed.search === path && !/[\\\x00-\x1f\x7f]/.test(decoded) &&
      !decoded.split("/").some(part => part === "." || part === "..");
  } catch { return false; }
}
function activation(action) { return action.kind === "click" || (action.kind === "press" && ["Enter", "Space"].includes(action.value)); }
function validateJob(job) {
  shape(job, ["schema_version", "operation_id", "execution_attempt_id", "request", "harness_sha256", "viewports", "interactions", "job_content_hash"], "JOB_SCHEMA");
  check(job.schema_version === 1 && typeof job.operation_id === "string" && /^[0-9a-f]{32}$/.test(job.operation_id) &&
    typeof job.execution_attempt_id === "string" && /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/.test(job.execution_attempt_id) &&
    typeof job.harness_sha256 === "string" && SHA.test(job.harness_sha256), "JOB_IDENTITY_INVALID");
  const { job_content_hash, ...body } = job;
  check(SHA.test(job_content_hash) && sha(canonical(body)) === job_content_hash, "JOB_HASH_MISMATCH");
  const request = job.request;
  shape(request, ["source_revision_content_hash", "source_tree_hash", "runner_image_digest", "base_url", "routes", "policy", "content_hash"], "REQUEST_SCHEMA");
  const { content_hash, ...requestBody } = request;
  check(SHA.test(content_hash) && sha(canonical(requestBody)) === content_hash, "REQUEST_HASH_MISMATCH");
  for (const name of ["source_revision_content_hash", "source_tree_hash", "runner_image_digest"]) check(typeof request[name] === "string" && SHA.test(request[name]), "REQUEST_IDENTITY_INVALID");
  const match = typeof request.base_url === "string" && /^http:\/\/(127\.0\.0\.1|localhost):([1-9][0-9]{0,4})\/?$/.exec(request.base_url);
  check(match && Number(match[2]) <= 65535, "ORIGIN_INVALID");
  const origin = new URL(request.base_url).origin;
  const policy = request.policy;
  const policyKeys = ["maximum_routes", "maximum_console_messages_per_route", "maximum_failed_requests_per_route", "maximum_accessibility_findings_per_route"];
  shape(policy, policyKeys, "POLICY_SCHEMA");
  for (const [name, maximum] of [[policyKeys[0], 5], [policyKeys[1], 100], [policyKeys[2], 100], [policyKeys[3], 200]]) {
    check(Number.isInteger(policy[name]) && policy[name] >= 1 && policy[name] <= maximum, "POLICY_LIMIT");
  }
  check(canonical(job.viewports) === canonical(VIEWPORTS), "VIEWPORTS_INVALID");
  check(Array.isArray(request.routes) && request.routes.length > 0 && request.routes.length <= policy.maximum_routes, "ROUTE_LIMIT");
  const routes = new Set(), ids = new Set();
  for (const route of request.routes) {
    shape(route, ["route_id", "path"], "ROUTE_SCHEMA");
    check(typeof route.route_id === "string" && route.route_id.length <= 160 && ID.test(route.route_id) &&
      routePath(route.path) && !routes.has(route.path) && !ids.has(route.route_id), "ROUTE_INVALID");
    routes.add(route.path); ids.add(route.route_id);
  }
  check(request.routes[0].path === "/" && request.routes[0].route_id === "root", "ROUTE_ROOT_REQUIRED");
  check(canonical(request.routes.slice(1)) === canonical(request.routes.slice(1).sort((a, b) =>
    a.route_id < b.route_id ? -1 : a.route_id > b.route_id ? 1 : a.path < b.path ? -1 : 1)), "ROUTE_ORDER_INVALID");
  check(Array.isArray(job.interactions) && job.interactions.length <= request.routes.length, "INTERACTION_LIMIT");
  const interactions = new Map();
  for (const plan of job.interactions) {
    shape(plan, ["route_id", "actions"], "INTERACTION_SCHEMA");
    check(ids.has(plan.route_id) && !interactions.has(plan.route_id) && Array.isArray(plan.actions) &&
      plan.actions.length >= 4 && plan.actions.length <= 8, "INTERACTION_INVALID");
    for (const action of plan.actions) {
      shape(action, ["kind", "selector", "value"], "ACTION_SCHEMA");
      check(["click", "fill", "press", "expect_text"].includes(action.kind) && typeof action.selector === "string" &&
        action.selector.length > 0 && action.selector.length <= 160 && !/[\x00-\x1f\x7f]/.test(action.selector), "ACTION_INVALID");
      check(action.kind === "click" ? action.value === null : typeof action.value === "string" &&
        action.value.length <= 1000 && !action.value.includes("\0"), "ACTION_VALUE_INVALID");
      if (action.kind === "press") check(ACTION_KEYS.has(action.value), "ACTION_KEY_INVALID");
    }
    check(plan.actions.some(a => a.kind === "click") && plan.actions.some(a => a.kind === "press" &&
      ["Enter", "Space"].includes(a.value)), "INTERACTION_COVERAGE_REQUIRED");
    for (let i = 0; i < plan.actions.length; i++) if (activation(plan.actions[i])) {
      let checked = false;
      for (let j = i + 1; j < plan.actions.length && !activation(plan.actions[j]); j++) checked ||= plan.actions[j].kind === "expect_text";
      check(checked, "INTERACTION_ASSERTION_REQUIRED");
    }
    interactions.set(plan.route_id, plan.actions);
  }
  return { job, origin, routes, interactions, policy };
}
function artifact(value, budget = null) {
  const bytes = Buffer.isBuffer(value) ? value : Buffer.from(value, "utf8");
  check(bytes.length > 0 && bytes.length <= MAX_ARTIFACT, "ARTIFACT_LIMIT");
  const result = { encoding: "base64", content: bytes.toString("base64"), size_bytes: bytes.length, sha256: sha(bytes) };
  if (budget) {
    const cost = Buffer.byteLength(JSON.stringify(result));
    check(cost <= budget.remaining, "OUTPUT_LIMIT"); budget.remaining -= cost;
  }
  return result;
}
function createEvents(policy) {
  const value = { console_messages: [], page_errors: [], failed_requests: [], blocked_requests: [], overflow: false };
  let remaining = 1536 * 1024 - 256;
  function text(raw, maximum = 2048) {
    let result = String(raw).replace(/\s+/g, " ").trim() || "[empty]";
    const bytes = Buffer.from(result);
    if (bytes.length > maximum) {
      value.overflow = true; result = bytes.subarray(0, maximum).toString("utf8");
      if (Buffer.byteLength(result) > maximum) result = result.slice(0, -1);
    }
    return result;
  }
  function append(name, item, maximum) {
    const cost = Buffer.byteLength(JSON.stringify(item)) + 1;
    if (value[name].length >= maximum || cost > remaining) { value.overflow = true; return; }
    remaining -= cost;
    value[name].push(item);
  }
  return { value,
    console(level, message, location) {
      const normalized = { debug: "DEBUG", info: "INFO", log: "INFO", warning: "WARNING", warn: "WARNING", error: "ERROR" }[level] || "INFO";
      append("console_messages", { level: normalized, message: text(message), location: location?.url ?
        text(`${location.url}:${location.lineNumber ?? 0}:${location.columnNumber ?? 0}`) : null }, policy.maximum_console_messages_per_route);
    },
    pageError(message) { append("page_errors", text(message), 100); },
    failed(method, path, failure) { append("failed_requests", { method: text(method, 16), path: text(path, 512), failure_text: text(failure) }, policy.maximum_failed_requests_per_route); },
    blocked(kind, target) { append("blocked_requests", { kind, target: text(target) }, 100); },
  };
}
function requestDecision(spec, target, main, redirected) {
  try {
    const url = new URL(target);
    if (url.origin !== spec.origin || url.protocol !== "http:" || url.username || url.password) return "EXTERNAL_REQUEST";
    if (redirected) return "REDIRECT";
    if (main && (!spec.routes.has(url.pathname + url.search) || url.hash)) return "UNDECLARED_NAVIGATION";
    return null;
  } catch { return "INVALID_URL"; }
}
async function bounded(promise, milliseconds, code) {
  let timer;
  try { return await Promise.race([promise, new Promise((_, reject) => { timer = setTimeout(() => reject(Error(code)), milliseconds); })]); }
  finally { clearTimeout(timer); }
}
async function actionResult(page, action, index) {
  const result = { index, kind: action.kind, status: "PASSED", observed_text: null, failure_code: null };
  try {
    const locator = page.locator(action.selector);
    if (action.kind === "click") await locator.click({ timeout: 1500 });
    else if (action.kind === "fill") await locator.fill(action.value, { timeout: 1500 });
    else if (action.kind === "press") await locator.press(action.value, { timeout: 1500 });
    else {
      const deadline = Date.now() + 1500;
      do {
        result.observed_text = await locator.innerText({ timeout: Math.max(1, deadline - Date.now()) });
        if (result.observed_text.length > 1000) {
          result.observed_text = result.observed_text.slice(0, 1000); throw Error("ASSERTION_TEXT_LIMIT");
        }
        if (result.observed_text === action.value) return result;
        await new Promise(resolve => setTimeout(resolve, 25));
      } while (Date.now() < deadline);
      result.status = "FAILED"; result.failure_code = "TEXT_ASSERTION_FAILED";
    }
  } catch (error) {
    result.status = "FAILED";
    result.failure_code = error.message === "ASSERTION_TEXT_LIMIT" ? "ASSERTION_TEXT_LIMIT" :
      action.kind === "expect_text" ? "TEXT_ASSERTION_READ_FAILED" : "ACTION_FAILED";
  }
  return result;
}
function notRun(action, index) { return { index, kind: action.kind, status: "NOT_RUN", observed_text: null, failure_code: null }; }
async function executeActions(page, actions) {
  const results = []; let failed = false;
  for (let i = 0; i < actions.length; i++) {
    const result = failed ? notRun(actions[i], i) : await actionResult(page, actions[i], i);
    results.push(result); failed ||= result.status === "FAILED";
  }
  return results;
}
async function isolatedContext(cdp, name) {
  const frame = (await cdp.send("Page.getFrameTree")).frameTree.frame.id;
  return (await cdp.send("Page.createIsolatedWorld", { frameId: frame, worldName: name, grantUniveralAccess: false })).executionContextId;
}
async function evaluate(cdp, contextId, expression, code, timeout = 5000) {
  const result = await bounded(cdp.send("Runtime.evaluate", { expression, contextId,
    awaitPromise: true, returnByValue: true, timeout }), timeout, code);
  check(!result.exceptionDetails && result.result, code);
  return result.result.value;
}
async function isolatedAxe(cdp, axe) {
  const contextId = await isolatedContext(cdp, "orchestwin.phase.axe");
  await evaluate(cdp, contextId, axe.source, "AXE_EXECUTION_FAILED");
  const body = await evaluate(cdp, contextId, `(async () => {
    const result = await axe.run(document);
    const text = JSON.stringify(result);
    if (new TextEncoder().encode(text).length > ${MAX_ARTIFACT}) throw Error('AXE_ARTIFACT_LIMIT');
    return text;
  })()`, "AXE_EXECUTION_FAILED");
  check(typeof body === "string" && Buffer.byteLength(body) <= MAX_ARTIFACT, "AXE_REPORT_INVALID");
  const data = JSON.parse(body);
  check(data.testEngine?.version === axe.version && Array.isArray(data.violations), "AXE_REPORT_INVALID");
  return body;
}
async function isolatedDom(cdp) {
  const contextId = await isolatedContext(cdp, "orchestwin.phase.dom");
  const body = await evaluate(cdp, contextId, `(() => {
    const html = (document.doctype ? '<!doctype html>\\n' : '') + document.documentElement.outerHTML;
    if (new TextEncoder().encode(html).length > ${MAX_ARTIFACT}) throw Error('DOM_ARTIFACT_LIMIT');
    const selector = 'button,input:not([type=hidden]),select,textarea,a[href],summary,[role=button],[role=link],[tabindex],[contenteditable=true]';
    const roots = [document]; let interactive_controls = 0, nodes = 0, opaque = false;
    while (roots.length && !opaque) {
      for (const element of roots.pop().querySelectorAll('*')) {
        if (++nodes > 100000 || ['iframe','frame','object','embed'].includes(element.localName) ||
            (element.localName.includes('-') && !element.shadowRoot)) { opaque = true; break; }
        if (element.shadowRoot) roots.push(element.shadowRoot);
        if (element.matches(selector) && !element.disabled && element.getAttribute('aria-disabled') !== 'true' &&
            element.getClientRects().length > 0 && getComputedStyle(element).visibility !== 'hidden' &&
            getComputedStyle(element).display !== 'none') interactive_controls++;
      }
    }
    if (opaque) interactive_controls = null;
    return JSON.stringify({html, interactive_controls});
  })()`, "DOM_CAPTURE_FAILED");
  const result = JSON.parse(body);
  check(typeof result.html === "string" && Buffer.byteLength(result.html) <= MAX_ARTIFACT &&
    (result.interactive_controls === null || Number.isSafeInteger(result.interactive_controls) && result.interactive_controls >= 0), "DOM_CAPTURE_FAILED");
  if (result.interactive_controls !== null) {
    try {
      const tree = await bounded(cdp.send("DOM.getDocument", { depth: -1, pierce: true }), 5000, "INTERACTION_INSPECTION_FAILED");
      const pending = [tree.root]; let nodes = 0;
      while (pending.length) {
        const node = pending.pop();
        check(node && Number.isInteger(node.nodeType) && ++nodes <= 100000, "INTERACTION_INSPECTION_FAILED");
        if (node.shadowRootType === "closed") { result.interactive_controls = null; break; }
        for (const key of ["children", "shadowRoots"]) {
          if (node[key] !== undefined) {
            check(Array.isArray(node[key]) && pending.length + node[key].length <= 100000, "INTERACTION_INSPECTION_FAILED");
            for (const child of node[key]) pending.push(child);
          }
        }
      }
    } catch { result.interactive_controls = null; }
  }
  return result;
}
function emptyScreen(spec, route, viewport, code = null) {
  return { route_id: route.route_id, path: route.path, viewport: viewport.name, width: viewport.width, height: viewport.height,
    final_path: null, http_status: null, interactive_controls: null, failure_codes: code ? [code] : [],
    actions: (spec.interactions.get(route.route_id) || []).map(notRun), interaction_status: "FAILED",
    screenshot: null, dom: null, axe: null, events: artifact(canonical(createEvents(spec.policy).value)), status: "FAILED" };
}
async function inspectScreen(context, spec, route, viewport, axe, budget = null) {
  const screen = emptyScreen(spec, route, viewport), events = createEvents(spec.policy), codes = new Set();
  Object.defineProperty(screen, "sandboxVerified", { value: false, writable: true });
  const fail = code => codes.add(code);
  let page, cdp;
  try {
    await context.route("**/*", async intercepted => {
      const request = intercepted.request();
      try {
        let frame = null;
        try { frame = request.frame(); } catch { /* Worker requests have no owning frame. */ }
        if (page && frame && frame.page() !== page) {
          events.blocked("POPUP", request.url()); await intercepted.abort("blockedbyclient"); return;
        }
        const main = request.isNavigationRequest() && (!page || !frame || frame === page.mainFrame());
        const decision = requestDecision(spec, request.url(), main, Boolean(request.redirectedFrom()));
        if (decision) { events.blocked(decision, request.url()); await intercepted.abort("blockedbyclient"); }
        else await intercepted.continue();
      } catch { fail("NETWORK_GUARD_FAILED"); await intercepted.abort("blockedbyclient").catch(() => {}); }
    });
    await context.routeWebSocket("**/*", socket => { events.blocked("WEB_SOCKET", socket.url()); socket.close(); });
    page = await context.newPage();
    page.setDefaultTimeout(1500);
    context.on("page", popup => { if (popup !== page) { events.blocked("POPUP", popup.url()); popup.close().catch(() => {}); } });
    page.on("pageerror", error => events.pageError(error.message));
    page.on("framenavigated", frame => {
      if (frame === page.mainFrame() && requestDecision(spec, frame.url(), true, false)) {
        events.blocked("UNDECLARED_NAVIGATION", frame.url()); fail("FINAL_NAVIGATION_INVALID");
      }
    });
    page.on("console", message => events.console(message.type(), message.text(), message.location()));
    page.on("download", download => { events.blocked("DOWNLOAD", download.url()); download.cancel().catch(() => {}); });
    page.on("dialog", dialog => { events.blocked("DIALOG", dialog.type()); dialog.dismiss().catch(() => {}); });
    page.on("requestfailed", request => {
      try { const url = new URL(request.url()); if (url.origin === spec.origin) events.failed(request.method(), url.pathname + url.search, request.failure()?.errorText || "REQUEST_FAILED"); }
      catch { fail("NETWORK_GUARD_FAILED"); }
    });
    page.on("response", response => {
      try {
        const url = new URL(response.url());
        if (response.status() >= 400 && url.origin === spec.origin) events.failed(response.request().method(), url.pathname + url.search, `HTTP_STATUS_${response.status()}`);
        if (response.status() >= 300 && response.status() < 400 && response.status() !== 304) events.blocked("REDIRECT", response.url());
      } catch { fail("NETWORK_GUARD_FAILED"); }
    });
    cdp = await context.newCDPSession(page);
    const switches = (await cdp.send("Browser.getBrowserCommandLine")).arguments;
    check(Array.isArray(switches) && !switches.some(arg => /^(--no-sandbox|--disable-namespace-sandbox|--disable-setuid-sandbox)(=|$)/.test(arg)), "CHROMIUM_SANDBOX_DISABLED");
    screen.sandboxVerified = true;
    let navigated = false;
    try {
      const response = await page.goto(spec.origin + route.path, { waitUntil: "load", timeout: 5000 });
      screen.http_status = response?.status() ?? null;
      check(screen.http_status === 200 && requestDecision(spec, page.url(), true, false) === null, "NAVIGATION_FAILED");
      navigated = true;
    } catch { fail("NAVIGATION_FAILED"); }
    let dom;
    try {
      dom = await isolatedDom(cdp); screen.interactive_controls = dom.interactive_controls;
      if (dom.interactive_controls === null) fail("INTERACTION_INSPECTION_FAILED");
    }
    catch { fail("DOM_CAPTURE_FAILED"); }
    const actions = spec.interactions.get(route.route_id);
    if (navigated && actions && screen.interactive_controls !== null) {
      screen.actions = await executeActions(page, actions);
      screen.interaction_status = screen.actions.every(action => action.status === "PASSED") ? "PASSED" : "FAILED";
      if (screen.interaction_status === "FAILED") fail("INTERACTION_FAILED");
    } else if (navigated && screen.interactive_controls === 0) screen.interaction_status = "NOT_APPLICABLE";
    else if (navigated && screen.interactive_controls > 0 && !actions) fail("INTERACTION_PLAN_REQUIRED");
    try {
      const final = new URL(page.url());
      check(requestDecision(spec, final.href, true, false) === null, "FINAL_NAVIGATION_INVALID");
      screen.final_path = final.pathname + final.search;
    } catch { fail("FINAL_NAVIGATION_INVALID"); }
    const captureUrl = page.url();
    try { screen.screenshot = artifact(await page.screenshot({ type: "png", fullPage: false, timeout: 5000 }), budget); }
    catch (error) { fail(error.message === "OUTPUT_LIMIT" ? "OUTPUT_LIMIT_EXCEEDED" : "SCREENSHOT_CAPTURE_FAILED"); }
    try {
      dom = await isolatedDom(cdp); screen.interactive_controls = dom.interactive_controls;
      screen.dom = artifact(dom.html, budget);
      if (dom.interactive_controls === null) {
        screen.interaction_status = "FAILED"; fail("INTERACTION_INSPECTION_FAILED");
      } else if (!actions && dom.interactive_controls > 0) {
        screen.interaction_status = "FAILED"; fail("INTERACTION_PLAN_REQUIRED");
      }
    }
    catch (error) { fail(error.message === "OUTPUT_LIMIT" ? "OUTPUT_LIMIT_EXCEEDED" : "DOM_CAPTURE_FAILED"); }
    try {
      const raw = await isolatedAxe(cdp, axe);
      if (JSON.parse(raw).violations.length > spec.policy.maximum_accessibility_findings_per_route) fail("ACCESSIBILITY_FINDING_LIMIT_EXCEEDED");
      screen.axe = artifact(raw, budget);
    } catch (error) { fail(error.message === "OUTPUT_LIMIT" ? "OUTPUT_LIMIT_EXCEEDED" : "AXE_EXECUTION_FAILED"); }
    if (page.url() !== captureUrl) fail("FINAL_NAVIGATION_INVALID");
  } catch (error) { fail(error.message === "CHROMIUM_SANDBOX_DISABLED" ? error.message : "BROWSER_SCREEN_FAILED"); }
  finally { if (cdp) await cdp.detach().catch(() => { fail("BROWSER_CLEANUP_FAILED"); }); }
  if (events.value.overflow) fail("EVENT_LIMIT_EXCEEDED");
  screen.events = artifact(canonical(events.value));
  screen.failure_codes = [...codes].sort();
  screen.status = screen.screenshot && screen.dom && screen.axe ? "COLLECTED" : "FAILED";
  return screen;
}
async function inspect(job) {
  check(process.getuid() === 65532, "RUNNER_UID_INVALID");
  const spec = validateJob(job), tools = createRequire("/opt/orchestwin/browser-automation/package.json");
  const { chromium } = tools("playwright"), axe = tools("axe-core"), version = tools("playwright/package.json").version;
  check(version === "1.62.1" && axe.version === "4.13.0", "TOOLCHAIN_MISMATCH");
  const report = { schema_version: 1, job_content_hash: job.job_content_hash, request_content_hash: job.request.content_hash,
    operation_id: job.operation_id, execution_attempt_id: job.execution_attempt_id, harness_sha256: job.harness_sha256,
    uid: process.getuid(), versions: { playwright: version, axe_core: axe.version, chromium: null },
    chromium_sandbox_requested: true, chromium_no_sandbox_flag_absent: true, transport_status: "COMPLETED", screens: [] };
  const count = job.request.routes.length * VIEWPORTS.length;
  // Reserve the bounded event payload and screen metadata even when binary captures exhaust their budget.
  const budget = { remaining: MAX_OUTPUT - count * (2 * 1024 * 1024 + 1024) - 262144 };
  let browser, expired = false;
  const watchdog = setTimeout(() => { expired = true; if (browser) browser.close().catch(() => {}); }, 120000);
  try {
    browser = await chromium.launch({ headless: true, chromiumSandbox: true, args: ["--enable-automation"], timeout: 20000 });
    report.versions.chromium = browser.version();
    for (const route of job.request.routes) for (const viewport of VIEWPORTS) {
      if (expired) { report.screens.push(emptyScreen(spec, route, viewport, "OVERALL_TIMEOUT")); continue; }
      let context, screen;
      try {
        context = await browser.newContext({ viewport: { width: viewport.width, height: viewport.height }, serviceWorkers: "block", acceptDownloads: false });
        screen = await inspectScreen(context, spec, route, viewport, axe, budget);
        report.chromium_no_sandbox_flag_absent &&= screen.sandboxVerified;
      } catch { screen = emptyScreen(spec, route, viewport, expired ? "OVERALL_TIMEOUT" : "BROWSER_SCREEN_FAILED"); report.chromium_no_sandbox_flag_absent = false; }
      finally {
        if (context) await context.close().catch(() => {
          if (screen) screen.failure_codes = [...new Set([...screen.failure_codes, "BROWSER_CLEANUP_FAILED"])].sort();
        });
      }
      report.screens.push(screen);
    }
  } finally { clearTimeout(watchdog); if (browser) await browser.close(); }
  check(Buffer.byteLength(JSON.stringify(report)) <= MAX_OUTPUT, "OUTPUT_LIMIT");
  return report;
}
async function readInput() {
  const chunks = []; let length = 0;
  for await (const chunk of process.stdin) { length += chunk.length; check(length <= MAX_INPUT, "INPUT_LIMIT"); chunks.push(chunk); }
  return parseInput(Buffer.concat(chunks));
}
if (require.main === module || typeof __filename !== "string" || __filename === "[eval]") {
  readInput().then(inspect).then(report => process.stdout.write(JSON.stringify(report))).catch(() => {
    process.stderr.write("PHASE_BROWSER_EXECUTOR_FAILED\n");
    process.stdout.write(JSON.stringify({ transport_status: "FAILED" })); process.exitCode = 1;
  });
}
module.exports = { canonical, parseInput, validateJob, artifact, createEvents, requestDecision,
  actionResult, executeActions, isolatedAxe, isolatedDom, inspectScreen, VIEWPORTS };
