/* Trusted infrastructure fixture only; never a formal case or a generic URL runner. */
"use strict";
const { createServer } = require("node:http");
const { readFileSync } = require("node:fs");
const { createHash } = require("node:crypto");
const { join } = require("node:path");

function payload(input) {
  const content = Buffer.isBuffer(input) ? input : Buffer.from(input, "utf8");
  if (content.length > 2 * 1024 * 1024) throw new Error("ARTIFACT_TOO_LARGE");
  return { encoding: "base64", content: content.toString("base64"),
    size_bytes: content.length, sha256: createHash("sha256").update(content).digest("hex") };
}
function requireTrue(value, code) {
  if (!value) throw new Error(code);
}
async function run() {
  requireTrue(process.argv.length === 2, "NO_EXTERNAL_INPUT_ACCEPTED");
  requireTrue(process.getuid() === 65532, "UNEXPECTED_UID");
  const { chromium } = require("playwright");
  const axe = require("axe-core");
  const playwrightVersion = require("playwright/package.json").version;
  requireTrue(playwrightVersion === "1.62.1" && axe.version === "4.13.0", "VERSION_MISMATCH");
  const fixture = readFileSync(join(__dirname, "fixture.html"));
  const negative = Buffer.from('<!doctype html><html lang="en"><head><title>Axe negative control</title></head>' +
    '<body><main><h1>Negative control</h1><button id="unlabelled"></button></main></body></html>');
  const server = createServer((request, response) => {
    if (request.method !== "GET" || !["/", "/negative"].includes(request.url)) {
      response.writeHead(404).end(); return;
    }
    const body = request.url === "/" ? fixture : negative;
    response.writeHead(200, { "content-type": "text/html; charset=utf-8", "content-length": body.length });
    response.end(body);
  });
  await new Promise((resolve, reject) => {
    server.once("error", reject);
    server.listen(4173, "127.0.0.1", resolve);
  });
  const events = [];
  let eventsOverflowed = false;
  function event(type, value) {
    if (events.length >= 100) { eventsOverflowed = true; return; }
    events.push({ type, value: String(value).slice(0, 2048) });
  }
  let browser;
  const report = { schema_version: 1, probe_kind: "TRUSTED_BROWSER_INFRASTRUCTURE_FIXTURE",
    status: "FAILED", uid: process.getuid(), versions: { playwright: playwrightVersion,
      axe_core: axe.version, node: process.version }, checks: {}, screens: [] };
  try {
    // No no-sandbox fallback: unsupported namespace/seccomp configuration must fail.
    browser = await chromium.launch({
      headless: true,
      chromiumSandbox: true,
      timeout: 20000,
      // Browser.getBrowserCommandLine requires this explicit Chromium switch.
      args: ["--enable-automation"],
    });
    report.versions.chromium = browser.version();
    report.checks.browser_launched = true;
    report.checks.chromium_sandbox_requested = true;
    const origin = "http://127.0.0.1:4173";
    for (const [name, width, height] of [["narrow", 390, 844], ["wide", 1280, 800]]) {
      const context = await browser.newContext({ viewport: { width, height },
        serviceWorkers: "block", acceptDownloads: false });
      try {
        let blocked = 0;
        await context.route("**/*", async route => {
          if (new URL(route.request().url()).origin !== origin) {
            blocked++; await route.abort("blockedbyclient"); return;
          }
          await route.continue();
        });
        const page = await context.newPage();
        page.setDefaultTimeout(5000);
        page.on("console", value => event("console:" + value.type(), value.text()));
        page.on("pageerror", error => event("pageerror", error.message));
        page.on("requestfailed", request => event("requestfailed", request.url()));
        const cdp = await context.newCDPSession(page);
        const { arguments: switches } = await cdp.send("Browser.getBrowserCommandLine");
        requireTrue(!switches.includes("--no-sandbox") &&
          !switches.includes("--disable-namespace-sandbox"), "CHROMIUM_SANDBOX_DISABLED");
        report.checks.chromium_no_sandbox_flag_absent = true;
        await cdp.detach();
        const response = await page.goto(origin + "/", { waitUntil: "load", timeout: 10000 });
        requireTrue(response.status() === 200 && page.url() === origin + "/", "LOCAL_NAVIGATION_FAILED");
        await page.locator("#activate").click();
        const pointer = await page.locator("#result").innerText();
        requireTrue(pointer === "Activations: 1", "POINTER_FAILED");
        await page.locator("#activate").focus();
        await page.keyboard.press("Enter");
        const keyboard = await page.locator("#result").innerText();
        requireTrue(keyboard === "Activations: 2", "KEYBOARD_FAILED");
        const externalRejected = await page.evaluate(async () => {
          try { await fetch("https://orchestwin-network-probe.invalid/"); return false; }
          catch { return true; }
        });
        requireTrue(externalRejected && blocked === 1, "EXTERNAL_REQUEST_NOT_BLOCKED");
        const screenshot = await page.screenshot({ type: "png", fullPage: false });
        const dom = await page.content();
        await page.addScriptTag({ content: axe.source });
        const accessibility = await page.evaluate(async () => window.axe.run(document));
        requireTrue(accessibility.testEngine.version === axe.version &&
          Array.isArray(accessibility.violations), "AXE_DID_NOT_EXECUTE");
        report.screens.push({ name, width, height, pointer, keyboard, blocked_requests: blocked,
          screenshot: payload(screenshot), dom: payload(dom), axe: payload(JSON.stringify(accessibility)) });
      } finally { await context.close(); }
    }
    const negativeContext = await browser.newContext({ serviceWorkers: "block", acceptDownloads: false });
    try {
      await negativeContext.route("**/*", async route => {
        if (new URL(route.request().url()).origin !== origin) { await route.abort(); return; }
        await route.continue();
      });
      const page = await negativeContext.newPage();
      await page.goto(origin + "/negative", { waitUntil: "load", timeout: 10000 });
      await page.addScriptTag({ content: axe.source });
      const negativeResult = await page.evaluate(async () => window.axe.run(document));
      requireTrue(negativeResult.violations.some(item => item.id === "button-name"), "AXE_NEGATIVE_CONTROL_FAILED");
      report.negative_axe = payload(JSON.stringify(negativeResult));
    } finally { await negativeContext.close(); }
    requireTrue(!eventsOverflowed, "EVENT_LIMIT_EXCEEDED");
    requireTrue(!events.some(item => item.type === "pageerror"), "UNEXPECTED_PAGE_ERROR");
    report.events = payload(JSON.stringify(events));
    report.package_lock = payload(readFileSync(join(__dirname, "package-lock.json")));
    Object.assign(report.checks, { local_navigation: true, pointer_activation: true,
      keyboard_activation: true, external_request_blocked: true, axe_executed: true,
      axe_negative_control: true, two_viewports_captured: true });
    report.status = "PASSED";
    return report;
  } finally {
    try { if (browser) await browser.close(); }
    finally { await new Promise(resolve => server.close(resolve)); }
  }
}

if (require.main === module) {
  run().then(report => console.log(JSON.stringify(report))).catch(error => {
    // There are no credentials or user sources in this container.
    console.error(String(error.stack || error).slice(0, 16000));
    console.log(JSON.stringify({ status: "FAILED", probe_kind: "TRUSTED_BROWSER_INFRASTRUCTURE_FIXTURE" }));
    process.exitCode = 1;
  });
}
module.exports = { payload, requireTrue };
