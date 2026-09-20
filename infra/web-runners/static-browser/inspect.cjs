/* Generic bounded static-source inspection. User JavaScript runs only in Chromium. */
"use strict";
const { createHash } = require("node:crypto");
const { createRequire } = require("node:module");
const { createServer } = require("node:http");

const MAX_INPUT = 4 * 1024 * 1024;
const MAX_SOURCE = 1024 * 1024;
const VIEWPORTS = [{ name: "narrow", width: 390, height: 844 },
  { name: "wide", width: 1280, height: 800 }];
const TYPES = new Map([["html", "text/html"], ["css", "text/css"],
  ["js", "text/javascript"], ["mjs", "text/javascript"], ["json", "application/json"],
  ["svg", "image/svg+xml"]]);
function check(value, code) { if (!value) throw new Error(code); }
function sha(bytes) { return createHash("sha256").update(bytes).digest("hex"); }
function sorted(value) {
  if (Array.isArray(value)) return value.map(sorted);
  if (value !== null && typeof value === "object") {
    return Object.fromEntries(Object.keys(value).sort().map(key => [key, sorted(value[key])]));
  }
  return value;
}
function canonical(value) { return JSON.stringify(sorted(value)); }
function artifact(value) {
  const bytes = Buffer.isBuffer(value) ? value : Buffer.from(value, "utf8");
  check(bytes.length > 0 && bytes.length <= 2 * 1024 * 1024, "ARTIFACT_LIMIT");
  return { encoding: "base64", content: bytes.toString("base64"), size_bytes: bytes.length,
    sha256: sha(bytes) };
}
function validateJob(job) {
  check(job && job.schema_version === 1, "JOB_SCHEMA");
  const { job_content_hash, ...body } = job;
  check(sha(canonical(body)) === job_content_hash, "JOB_HASH_MISMATCH");
  check(Array.isArray(job.files) && job.files.length > 0 && job.files.length <= 100, "FILE_LIMIT");
  check(canonical(job.viewports) === canonical(VIEWPORTS), "VIEWPORTS_INVALID");
  const sources = new Map();
  const names = new Set();
  let total = 0;
  for (const file of job.files) {
    const path = file.path;
    check(typeof path === "string" && path.length > 0 && path.length <= 200 &&
      !path.startsWith("/") && !/[\\:\x00-\x1f]/.test(path) &&
      path.split("/").every(part => part && !part.startsWith(".") && !/[. ]$/.test(part)) &&
      !names.has(path.toLowerCase()), "FILE_PATH_INVALID");
    names.add(path.toLowerCase());
    const mediaType = TYPES.get(path.split(".").pop().toLowerCase());
    check(mediaType && mediaType === file.media_type, "FILE_TYPE_INVALID");
    const bytes = Buffer.from(file.content_base64, "base64");
    check(bytes.toString("base64") === file.content_base64 &&
      bytes.length === file.size_bytes && sha(bytes) === file.sha256, "FILE_BYTES_MISMATCH");
    total += bytes.length;
    check(total <= MAX_SOURCE, "SOURCE_LIMIT");
    sources.set("/" + path, { bytes, mediaType });
  }
  check(sources.has("/index.html"), "ROOT_MISSING");
  check(Array.isArray(job.scenarios) && job.scenarios.length > 0 && job.scenarios.length <= 2,
    "SCENARIO_LIMIT");
  const ids = new Set();
  for (const scenario of job.scenarios) {
    check(/^[a-z][a-z0-9-]{0,39}$/.test(scenario.id) && !ids.has(scenario.id), "SCENARIO_ID_INVALID");
    ids.add(scenario.id);
    check(scenario.route === "/" || (scenario.route.endsWith(".html") && sources.has(scenario.route)),
      "SCENARIO_ROUTE_INVALID");
    check(Array.isArray(scenario.actions) && scenario.actions.length > 0 &&
      scenario.actions.length <= 8 && scenario.actions.some(a => a.kind === "expect_text"),
      "ACTION_LIMIT");
    for (const action of scenario.actions) {
      check(["click", "press", "fill", "expect_text"].includes(action.kind) &&
        typeof action.selector === "string" && action.selector.length > 0 &&
        action.selector.length <= 160, "ACTION_INVALID");
      check(action.kind === "click" ? action.value === null :
        typeof action.value === "string" && action.value.length <= 1000, "ACTION_VALUE_INVALID");
      if (action.kind === "press") check(["Enter", "Space", "Tab", "Escape", "ArrowLeft",
        "ArrowRight", "Home", "End"].includes(action.value), "KEY_INVALID");
    }
  }
  return sources;
}
function staticHandler(sources) {
  return (request, response) => {
    if (!["GET", "HEAD"].includes(request.method)) { response.writeHead(405).end(); return; }
    let path;
    try { path = decodeURIComponent(new URL(request.url, "http://127.0.0.1").pathname); }
    catch { response.writeHead(400).end(); return; }
    if (path === "/favicon.ico" && !sources.has(path)) { response.writeHead(204).end(); return; }
    const item = sources.get(path === "/" ? "/index.html" : path);
    if (!item) { response.writeHead(404).end(); return; }
    response.writeHead(200, { "content-type": item.mediaType + "; charset=utf-8",
      "content-length": item.bytes.length, "x-content-type-options": "nosniff" });
    response.end(request.method === "HEAD" ? undefined : item.bytes);
  };
}
async function actionResult(page, action, index) {
  const result = { index, kind: action.kind, status: "PASSED", observed_text: null, failure_code: null };
  try {
    const locator = page.locator(action.selector);
    if (action.kind === "click") await locator.click();
    else if (action.kind === "fill") await locator.fill(action.value);
    else if (action.kind === "press") await locator.press(action.value);
    else {
      const until = Date.now() + 1500;
      do {
        result.observed_text = (await locator.innerText()).slice(0, 1001);
        if (result.observed_text === action.value) break;
        await new Promise(resolve => setTimeout(resolve, 50));
      } while (Date.now() < until);
      if (result.observed_text !== action.value) {
        result.status = "FAILED";
        result.failure_code = "TEXT_ASSERTION_FAILED";
      }
    }
  } catch {
    result.status = "FAILED";
    result.failure_code = action.kind === "expect_text" ? "TEXT_ASSERTION_READ_FAILED" : "ACTION_FAILED";
  }
  return result;
}
async function inspect(job) {
  check(process.getuid() === 65532, "RUNNER_UID_INVALID");
  const sources = validateJob(job);
  // Never resolve modules relative to submitted sources.
  const tools = createRequire("/opt/orchestwin/browser-automation/package.json");
  const { chromium } = tools("playwright");
  const axe = tools("axe-core");
  const version = tools("playwright/package.json").version;
  check(version === "1.62.1" && axe.version === "4.13.0", "TOOLCHAIN_MISMATCH");
  const server = createServer(staticHandler(sources));
  await new Promise((resolve, reject) => {
    server.once("error", reject); server.listen(4173, "127.0.0.1", resolve);
  });
  const origin = "http://127.0.0.1:4173";
  let browser;
  try {
    browser = await chromium.launch({ headless: true, chromiumSandbox: true,
      args: ["--enable-automation"], timeout: 20000 });
    const report = { schema_version: 1, job_content_hash: job.job_content_hash,
      uid: process.getuid(), transport_status: "COMPLETED", status: "PASSED",
      versions: { playwright: version, axe_core: axe.version, chromium: browser.version() },
      chromium_sandbox_requested: true, chromium_no_sandbox_flag_absent: false, screens: [] };
    for (const scenario of job.scenarios) {
      for (const viewport of VIEWPORTS) {
        const context = await browser.newContext({ viewport: { width: viewport.width, height: viewport.height },
          serviceWorkers: "block", acceptDownloads: false });
        let blocked = 0;
        const events = [];
        let overflow = false;
        function observe(type, message) {
          if (events.length >= 100) { overflow = true; return; }
          events.push({ type, message: String(message).slice(0, 1000) });
        }
        try {
          await context.route("**/*", async route => {
            if (new URL(route.request().url()).origin !== origin) {
              blocked++; await route.abort("blockedbyclient"); return;
            }
            await route.continue();
          });
          await context.routeWebSocket("**/*", route => { blocked++; route.close(); });
          const page = await context.newPage();
          page.setDefaultTimeout(2000);
          page.on("pageerror", error => observe("pageerror", error.message));
          page.on("console", value => observe("console:" + value.type(), value.text()));
          page.on("requestfailed", request => observe("requestfailed", request.failure()?.errorText));
          page.on("popup", popup => { blocked++; popup.close().catch(() => {}); });
          const cdp = await context.newCDPSession(page);
          try {
            const { arguments: switches } = await cdp.send("Browser.getBrowserCommandLine");
            check(!switches.some(arg => /^(--no-sandbox|--disable-namespace-sandbox)(=|$)/.test(arg)),
              "CHROMIUM_SANDBOX_DISABLED");
          } finally { await cdp.detach(); }
          report.chromium_no_sandbox_flag_absent = true;
          const response = await page.goto(origin + scenario.route, { waitUntil: "load", timeout: 10000 });
          check(response?.status() === 200 && page.url() === origin + scenario.route, "NAVIGATION_FAILED");
          const actions = [];
          let failed = false;
          for (let index = 0; index < scenario.actions.length; index++) {
            const action = scenario.actions[index];
            const result = failed ? { index, kind: action.kind, status: "NOT_RUN",
              observed_text: null, failure_code: null } : await actionResult(page, action, index);
            actions.push(result);
            failed ||= result.status === "FAILED";
          }
          const png = await page.screenshot({ type: "png", fullPage: false });
          const dom = await page.content();
          await page.addScriptTag({ content: axe.source });
          const accessibility = await page.evaluate(async () => window.axe.run(document));
          check(accessibility.testEngine.version === axe.version &&
            Array.isArray(accessibility.violations), "AXE_REPORT_INVALID");
          check(!overflow, "EVENT_LIMIT_EXCEEDED");
          failed ||= blocked > 0 || events.some(item => item.type === "pageerror");
          report.screens.push({ scenario_id: scenario.id, route: scenario.route,
            viewport: viewport.name, width: viewport.width, height: viewport.height,
            status: failed ? "FAILED" : "PASSED", actions, blocked_requests: blocked,
            screenshot: artifact(png), dom: artifact(dom), axe: artifact(JSON.stringify(accessibility)),
            events: artifact(JSON.stringify(events)) });
          if (failed) report.status = "FAILED";
        } finally { await context.close(); }
      }
    }
    return report;
  } finally {
    try { if (browser) await browser.close(); }
    finally { server.closeAllConnections(); await new Promise(resolve => server.close(resolve)); }
  }
}
async function readInput() {
  const chunks = []; let total = 0;
  for await (const chunk of process.stdin) {
    total += chunk.length; check(total <= MAX_INPUT, "INPUT_LIMIT"); chunks.push(chunk);
  }
  return JSON.parse(Buffer.concat(chunks).toString("utf8"));
}
if (require.main === module || typeof __filename !== "string" || __filename === "[eval]") {
  readInput().then(inspect).then(report => console.log(JSON.stringify(report))).catch(error => {
    // Input sources are never printed, even on malformed jobs or a failed browser launch.
    console.error(error.name === "Error" ? String(error.message).slice(0, 300) : "BROWSER_EXECUTOR_FAILED");
    console.log(JSON.stringify({ transport_status: "FAILED", status: "ERROR" }));
    process.exitCode = 1;
  });
}
module.exports = { canonical, artifact, validateJob, staticHandler, actionResult };
