"use strict";

const fs = require("node:fs");
const path = require("node:path");
const vscode = require("vscode");
const { languageOf, text } = require("../../src/messages");
const { readProject } = require("../../src/project");
const { escapeHtml, nextStep } = require("../../src/view");

const EXTENSION_ID = "orchestwin.orchestwin-studio";
const EXTENSION_ROOT = path.resolve(__dirname, "..", "..");
const RESULT_VARIABLE = "ORCHESTWIN_HOST_CHECK_RESULT";
const SCHEMA_VERSION = 1;
const TERMINAL_NAME = "OrchesTwin";
const PROGRAM = "echo";
const DEFAULT_PROGRAM = "ut";
const SERVER_NAME = "orchestwin-twins";
const MCP_FILE = Object.freeze([".vscode", "mcp.json"]);
const STATE_FILE = Object.freeze(["orchestwin", "state", "state.json"]);
const MANIFEST_FILE = Object.freeze(["orchestwin", "orchestwin.json"]);
const FOCUS_COMMAND = "orchestwin.panel.focus";
const CONTAINER_COMMAND = "workbench.view.extension.orchestwin";
const PROBE_TYPE = "orchestwin.hostCheck";
const PANEL_MARK = '<main class="panel">';
const HOST_TASK_CODE = "TSK-099";
const HOST_TASK_TEXT = "A task written by the host check while the panel was open.";
const DEFAULT_NLS = "package.nls.json";
const PLACEHOLDER = /^%([^%]+)%$/;
const WAIT_LIMIT = 20000;
const CLOSE_LIMIT = 5000;
const POLL_INTERVAL = 50;

function fail(message) {
  throw new Error(message);
}

function expect(condition, message) {
  if (!condition) {
    fail(message);
  }
}

function reasonOf(error) {
  return error instanceof Error ? error.message : String(error);
}

function listOf(value) {
  return Array.isArray(value) ? value : [];
}

function readJson(file) {
  return JSON.parse(fs.readFileSync(file, "utf8").replace(/^﻿/, ""));
}

function samePath(left, right) {
  return path.relative(path.resolve(left), path.resolve(right)) === "";
}

function posixPath(value) {
  return process.platform === "win32" ? value.replace(/\\/g, "/") : value;
}

function pause(milliseconds) {
  return new Promise((resolve) => {
    setTimeout(resolve, milliseconds);
  });
}

function seconds(milliseconds) {
  return `${milliseconds / 1000} seconds`;
}

async function waitFor(probe, failure, limit = WAIT_LIMIT) {
  const deadline = Date.now() + limit;
  for (;;) {
    const found = probe();
    if (found) {
      return found;
    }
    if (Date.now() >= deadline) {
      fail(`${failure} within ${seconds(limit)}`);
    }
    await pause(POLL_INTERVAL);
  }
}

function withLimit(promise, failure, limit = WAIT_LIMIT) {
  let timer;
  const expired = new Promise((resolve, reject) => {
    timer = setTimeout(() => reject(new Error(`${failure} within ${seconds(limit)}`)), limit);
  });
  return Promise.race([Promise.resolve(promise), expired]).finally(() => clearTimeout(timer));
}

function nextEvent(event, accept, failure, limit = WAIT_LIMIT) {
  let subscription;
  const happened = new Promise((resolve) => {
    subscription = event((value) => {
      if (accept(value)) {
        resolve(value);
      }
    });
  });
  return withLimit(happened, failure, limit).finally(() => subscription.dispose());
}

function execute(command) {
  return withLimit(vscode.commands.executeCommand(command), `${command} did not resolve`);
}

function firstFolder() {
  const folders = vscode.workspace.workspaceFolders;
  return Array.isArray(folders) && folders.length > 0 ? folders[0].uri.fsPath : null;
}

function requireExtension(session) {
  expect(session.extension !== null, `${EXTENSION_ID} was not found`);
  return session.extension;
}

function requireRoot(session) {
  expect(session.root !== null, "the window has no workspace folder");
  return session.root;
}

function requirePanel(session) {
  expect(session.panel !== null, "the page of the panel was not observed");
  return session.panel;
}

function creationName(terminal) {
  const options = terminal.creationOptions;
  return options !== null && typeof options === "object" && typeof options.name === "string"
    ? options.name
    : undefined;
}

function ownTerminals() {
  return vscode.window.terminals.filter((terminal) => creationName(terminal) === TERMINAL_NAME);
}

function describeTerminals() {
  const items = vscode.window.terminals.map((terminal) => {
    const exit = terminal.exitStatus === undefined ? "open" : `exit ${terminal.exitStatus.code}`;
    return `"${terminal.name}" created as "${creationName(terminal)}", ${exit}`;
  });
  return items.length === 0 ? "no terminal" : items.join("; ");
}

function hostName(terminal) {
  return terminal.name === TERMINAL_NAME ? "" : ` (the host now calls it "${terminal.name}")`;
}

function tabCount() {
  return vscode.window.tabGroups.all.reduce((sum, group) => sum + group.tabs.length, 0);
}

function pageWrites(session) {
  return session.pages === null
    ? []
    : session.pages.writes.filter((write) => write.webview === session.panel);
}

function statusesSince(session, index) {
  if (session.pages === null || session.panel === null) {
    return [];
  }
  return session.pages.messages
    .slice(index)
    .filter(
      (item) =>
        item.webview === session.panel &&
        item.message !== null &&
        typeof item.message === "object" &&
        item.message.type === "status",
    )
    .map((item) => item.message.text);
}

function messageCount(session) {
  return session.pages === null ? 0 : session.pages.messages.length;
}

async function panelSays(session, index, expected, times = 1) {
  if (session.panel === null) {
    return "";
  }
  await waitFor(
    () => statusesSince(session, index).filter((line) => line === expected).length >= times,
    `the panel did not say "${expected}"`,
  );
  return times === 1
    ? `the panel said "${expected}"`
    : `the panel said "${expected}" ${times} times`;
}

function observeWebviews() {
  const probe = vscode.window.createWebviewPanel(
    PROBE_TYPE,
    "OrchesTwin host check",
    { viewColumn: vscode.ViewColumn.Active, preserveFocus: true },
    {},
  );
  const prototype = Object.getPrototypeOf(probe.webview);
  probe.dispose();
  const originals = {
    html: Object.getOwnPropertyDescriptor(prototype, "html"),
    options: Object.getOwnPropertyDescriptor(prototype, "options"),
    postMessage: Object.getOwnPropertyDescriptor(prototype, "postMessage"),
  };
  const usable =
    originals.html !== undefined &&
    typeof originals.html.set === "function" &&
    originals.html.configurable &&
    originals.options !== undefined &&
    typeof originals.options.set === "function" &&
    originals.options.configurable &&
    originals.postMessage !== undefined &&
    typeof originals.postMessage.value === "function" &&
    originals.postMessage.configurable;
  expect(usable, "the webviews of this host cannot be observed");
  const pages = { writes: [], settings: [], messages: [] };
  Object.defineProperty(prototype, "html", {
    ...originals.html,
    set(value) {
      originals.html.set.call(this, value);
      pages.writes.push({ webview: this, html: String(value), at: Date.now() });
    },
  });
  Object.defineProperty(prototype, "options", {
    ...originals.options,
    set(value) {
      originals.options.set.call(this, value);
      pages.settings.push({ webview: this, value });
    },
  });
  Object.defineProperty(prototype, "postMessage", {
    ...originals.postMessage,
    value(message) {
      pages.messages.push({ webview: this, message });
      return originals.postMessage.value.call(this, message);
    },
  });
  pages.restore = () => {
    for (const [name, descriptor] of Object.entries(originals)) {
      Object.defineProperty(prototype, name, descriptor);
    }
  };
  return pages;
}

function guardOpenExternal() {
  const env = vscode.env;
  const original = env.openExternal;
  const calls = [];
  try {
    env.openExternal = (target) => {
      calls.push(String(target));
      return Promise.resolve(false);
    };
  } catch {
    return { calls, active: false, restore() {} };
  }
  const active = env.openExternal !== original;
  return {
    calls,
    active,
    restore() {
      if (active) {
        env.openExternal = original;
      }
    },
  };
}

function languageFile(language) {
  const lowered = String(language ?? "").toLowerCase();
  if (lowered === "" || lowered === "en" || lowered.startsWith("en-")) {
    return DEFAULT_NLS;
  }
  for (const candidate of [lowered, lowered.split("-")[0]]) {
    const name = `package.nls.${candidate}.json`;
    if (fs.existsSync(path.join(EXTENSION_ROOT, name))) {
      return name;
    }
  }
  return DEFAULT_NLS;
}

function placeholders(raw, loaded, trail = [], found = []) {
  if (typeof raw === "string") {
    const match = PLACEHOLDER.exec(raw);
    if (match !== null) {
      found.push({ key: match[1], where: trail.join("/"), value: loaded });
    }
    return found;
  }
  if (raw !== null && typeof raw === "object") {
    for (const [key, value] of Object.entries(raw)) {
      const inner = loaded !== null && typeof loaded === "object" ? loaded[key] : undefined;
      placeholders(value, inner, [...trail, key], found);
    }
  }
  return found;
}

function hostTask() {
  return {
    code: HOST_TASK_CODE,
    text: HOST_TASK_TEXT,
    about: { requirements: [], screens: [], criteria: [] },
    origin: {
      kind: "OWNER",
      commit: null,
      test_run_id: null,
      twin_id: null,
      twin_name: null,
      finding: null,
    },
    from_commit: null,
    created_at: new Date().toISOString(),
    status: "OPEN",
    closed_at: null,
    note: null,
  };
}

function expectedMcp(root) {
  const folder = posixPath(root);
  const document = {
    servers: {
      [SERVER_NAME]: {
        type: "stdio",
        command: PROGRAM,
        args: ["--project-dir", folder, "mcp"],
        cwd: folder,
      },
    },
  };
  return { folder, content: `${JSON.stringify(document, null, 2)}\n` };
}

async function activation(session) {
  const extension = vscode.extensions.getExtension(EXTENSION_ID);
  expect(extension !== undefined, `${EXTENSION_ID} is not among the extensions of the host`);
  session.extension = extension;
  expect(
    samePath(extension.extensionPath, EXTENSION_ROOT),
    `the host loaded ${extension.extensionPath}, not ${EXTENSION_ROOT}`,
  );
  const activeAtStart = extension.isActive;
  await withLimit(extension.activate(), "activate() did not resolve");
  expect(extension.isActive, "the extension is not active after activate()");
  expect(
    activeAtStart,
    "the extension was not active when the checks started: workspaceContains:.orchestwin/project.json did not start it",
  );
  return "loaded from this working tree, started by workspaceContains:.orchestwin/project.json before the checks, activate() resolved";
}

async function commands(session) {
  const extension = requireExtension(session);
  const contributed = listOf(extension.packageJSON.contributes?.commands).map(
    (item) => item.command,
  );
  expect(contributed.length > 0, "the manifest loaded by the host has no commands");
  const registered = new Set(await vscode.commands.getCommands(true));
  const missing = contributed.filter((id) => !registered.has(id));
  expect(missing.length === 0, `not registered: ${missing.join(", ")}`);
  return `${contributed.length} of ${contributed.length} registered`;
}

async function manifestTexts(session) {
  const extension = requireExtension(session);
  const raw = readJson(path.join(EXTENSION_ROOT, "package.json"));
  const file = languageFile(vscode.env.language);
  const messages = readJson(path.join(EXTENSION_ROOT, file));
  const found = placeholders(raw, extension.packageJSON);
  expect(found.length > 0, "the manifest has no text to translate");
  const wrong = found.filter(
    ({ key, value }) =>
      typeof value !== "string" || value.startsWith("%") || value !== messages[key],
  );
  expect(
    wrong.length === 0,
    `not taken from ${file}: ${wrong.map((item) => `${item.where} = ${JSON.stringify(item.value)}`).join("; ")}`,
  );
  return `${found.length} texts of the manifest, all taken from ${file}`;
}

async function setting() {
  const configuration = vscode.workspace.getConfiguration("orchestwin");
  const inspected = configuration.inspect("utCommand");
  expect(inspected !== undefined, "the host does not know the setting orchestwin.utCommand");
  expect(
    inspected.defaultValue === DEFAULT_PROGRAM,
    `the default is ${JSON.stringify(inspected.defaultValue)}, not "${DEFAULT_PROGRAM}"`,
  );
  expect(
    inspected.globalValue === PROGRAM,
    `the user settings give ${JSON.stringify(inspected.globalValue)}, not "${PROGRAM}"`,
  );
  const value = configuration.get("utCommand");
  expect(value === PROGRAM, `the value in use is ${JSON.stringify(value)}`);
  return `default "${DEFAULT_PROGRAM}" from the manifest, "${PROGRAM}" from the user settings (scope machine)`;
}

async function panel(session) {
  const root = requireRoot(session);
  const registered = new Set(await vscode.commands.getCommands(true));
  for (const id of [CONTAINER_COMMAND, FOCUS_COMMAND]) {
    expect(
      registered.has(id),
      `the host has no command ${id}: the container or the view is missing`,
    );
  }
  session.pages = observeWebviews();
  const started = Date.now();
  await execute(FOCUS_COMMAND);
  const first = await waitFor(
    () => session.pages.writes.find((write) => write.html.includes(PANEL_MARK)),
    "the view wrote no page",
  );
  const elapsed = first.at - started;
  session.panel = first.webview;
  const setup = session.pages.settings.find((item) => item.webview === first.webview);
  expect(
    setup !== undefined &&
      setup.value.enableScripts === true &&
      Array.isArray(setup.value.localResourceRoots) &&
      setup.value.localResourceRoots.length === 0,
    "the webview of the view was not given scripts without local resources",
  );
  const name = readJson(path.join(root, ...MANIFEST_FILE)).project.name;
  expect(first.html.includes(`<h1>${escapeHtml(name)}</h1>`), `the page does not show ${name}`);
  expect(
    first.html.includes(`<html lang="${session.language}">`),
    `the page is not in the language of the editor (${session.language})`,
  );
  const step = nextStep(readProject(root)).kind;
  expect(
    first.html.includes(`data-step="${step}"`),
    `the page does not show the next step ${step}`,
  );
  const written = pageWrites(session).length;
  await execute("orchestwin.refresh");
  await waitFor(() => pageWrites(session).length > written, "orchestwin.refresh wrote no page");
  return `the view wrote its page ${elapsed} ms after ${FOCUS_COMMAND} (${first.html.length} characters, "${name}", next step ${step}); orchestwin.refresh wrote it again`;
}

async function watcher(session) {
  const root = requireRoot(session);
  requirePanel(session);
  const file = path.join(root, ...STATE_FILE);
  const state = readJson(file);
  state.tasks.push(hostTask());
  const written = pageWrites(session).length;
  const started = Date.now();
  fs.writeFileSync(file, `${JSON.stringify(state, null, 2)}\n`, "utf8");
  const write = await waitFor(
    () =>
      pageWrites(session)
        .slice(written)
        .find((item) => item.html.includes(escapeHtml(HOST_TASK_TEXT))),
    `the page did not show the task added to ${STATE_FILE.join("/")}`,
  );
  return `the page showed the task added to ${STATE_FILE.join("/")} ${write.at - started} ms after the change`;
}

async function report(session) {
  requirePanel(session);
  const tabs = tabCount();
  const index = messageCount(session);
  await execute("orchestwin.openReport");
  const said = await panelSays(session, index, text(session.language, "status.noReport"));
  expect(
    session.guard.calls.length === 0,
    `the extension asked to open ${session.guard.calls.join(", ")}`,
  );
  expect(tabCount() === tabs, "an editor was opened");
  const opened = session.guard.active
    ? "nothing was opened"
    : "no editor was opened (the calls to the browser could not be watched)";
  return `${said}; ${opened}`;
}

async function terminal(session) {
  const root = requireRoot(session);
  const before = new Set(vscode.window.terminals);
  expect(
    ownTerminals().length === 0,
    `a terminal named ${TERMINAL_NAME} was already open (${describeTerminals()})`,
  );
  const index = messageCount(session);
  await execute("orchestwin.status");
  const opened = vscode.window.terminals.filter((item) => !before.has(item));
  expect(
    opened.length === 1 && creationName(opened[0]) === TERMINAL_NAME,
    `the first command did not open one terminal named ${TERMINAL_NAME} (${describeTerminals()})`,
  );
  const [first] = opened;
  const processId = await withLimit(first.processId, "the shell of the terminal did not start");
  expect(Number.isInteger(processId), "the terminal has no shell process");
  const cwd = first.creationOptions.cwd;
  expect(
    typeof cwd === "string" && samePath(cwd, root),
    `the terminal starts in ${String(cwd)}, not in the project`,
  );
  await execute("orchestwin.status");
  const again = vscode.window.terminals.filter((item) => !before.has(item));
  expect(
    again.length === 1 && again[0] === first && first.exitStatus === undefined,
    `the second command did not write in the same terminal (${describeTerminals()})`,
  );
  const line = `${PROGRAM} status`;
  const said = await panelSays(
    session,
    index,
    text(session.language, "status.sent", { command: line }),
    2,
  );
  const words = said === "" ? "" : `; ${said}`;
  return `one terminal named ${TERMINAL_NAME}${hostName(first)}, shell process ${processId}, started in the project folder and used again by the second command${words}`;
}

async function terminalReopen(session) {
  const [previous] = ownTerminals();
  expect(
    previous !== undefined,
    `no terminal named ${TERMINAL_NAME} to close (${describeTerminals()})`,
  );
  const closed = nextEvent(
    vscode.window.onDidCloseTerminal,
    (item) => item === previous,
    "the terminal did not close",
  );
  previous.dispose();
  await closed;
  await execute("orchestwin.status");
  const opened = ownTerminals();
  expect(
    opened.length === 1 && opened[0] !== previous,
    `the command after the close did not open a new terminal (${describeTerminals()})`,
  );
  const processId = await withLimit(
    opened[0].processId,
    "the shell of the new terminal did not start",
  );
  return `after the terminal closed, orchestwin.status opened a new one (shell process ${processId})`;
}

async function agents(session) {
  const root = requireRoot(session);
  const file = path.join(root, ...MCP_FILE);
  expect(!fs.existsSync(file), `${MCP_FILE.join("/")} existed before the command`);
  const expected = expectedMcp(root);
  const index = messageCount(session);
  const written = pageWrites(session).length;
  await execute("orchestwin.connectAgents");
  expect(fs.existsSync(file), `${MCP_FILE.join("/")} was not written`);
  const content = fs.readFileSync(file, "utf8");
  expect(
    content === expected.content,
    `${MCP_FILE.join("/")} holds ${JSON.stringify(content)}, not ${JSON.stringify(expected.content)}`,
  );
  const created = await panelSays(session, index, text(session.language, "status.connect.CREATED"));
  if (session.panel !== null) {
    const connected = escapeHtml(text(session.language, "agents.CONNECTED"));
    await waitFor(
      () =>
        pageWrites(session)
          .slice(written)
          .some((item) => item.html.includes(connected)),
      "the page did not show the twins as connected",
    );
  }
  const before = fs.statSync(file).mtimeMs;
  const again = messageCount(session);
  await execute("orchestwin.connectAgents");
  expect(fs.readFileSync(file, "utf8") === expected.content, "the second command changed the file");
  expect(fs.statSync(file).mtimeMs === before, "the second command wrote the file again");
  const unchanged = await panelSays(
    session,
    again,
    text(session.language, "status.connect.UNCHANGED"),
  );
  const words = [created, unchanged].filter((item) => item !== "").join("; ");
  return `${MCP_FILE.join("/")} starts ${SERVER_NAME} with "${PROGRAM} --project-dir ${expected.folder} mcp"; the second command left it as it was${words === "" ? "" : `; ${words}`}`;
}

const CHECKS = Object.freeze([
  ["activation", activation],
  ["commands", commands],
  ["manifest", manifestTexts],
  ["setting", setting],
  ["panel", panel],
  ["watcher", watcher],
  ["report", report],
  ["terminal", terminal],
  ["terminalReopen", terminalReopen],
  ["agents", agents],
]);

function versionOf(extension) {
  if (extension === null) {
    return null;
  }
  const version = extension.packageJSON.version;
  return typeof version === "string" ? version : null;
}

function save(file, result) {
  if (typeof file !== "string" || file === "") {
    return;
  }
  fs.mkdirSync(path.dirname(file), { recursive: true });
  fs.writeFileSync(file, `${JSON.stringify(result, null, 2)}\n`, "utf8");
}

async function closeTerminals() {
  const open = [...vscode.window.terminals];
  const closing = open.map((item) =>
    nextEvent(
      vscode.window.onDidCloseTerminal,
      (closed) => closed === item,
      "a terminal did not close",
      CLOSE_LIMIT,
    ).catch(() => undefined),
  );
  for (const item of open) {
    item.dispose();
  }
  await Promise.all(closing);
}

async function run() {
  const file = process.env[RESULT_VARIABLE];
  const session = {
    extension: null,
    root: firstFolder(),
    language: languageOf(vscode.env.language),
    pages: null,
    panel: null,
    guard: guardOpenExternal(),
  };
  const result = {
    schema_version: SCHEMA_VERSION,
    vscode_version: vscode.version,
    language: vscode.env.language,
    extension_version: null,
    checks: [],
  };
  try {
    for (const [name, step] of CHECKS) {
      let outcome = "PASSED";
      let detail;
      try {
        detail = await step(session);
      } catch (error) {
        outcome = "FAILED";
        detail = reasonOf(error);
      }
      result.extension_version = versionOf(session.extension);
      result.checks.push({ name, outcome, detail });
      save(file, result);
    }
  } finally {
    await closeTerminals().catch(() => undefined);
    session.guard.restore();
    if (session.pages !== null) {
      session.pages.restore();
    }
    save(file, result);
  }
  expect(
    typeof file === "string" && file !== "",
    `${RESULT_VARIABLE} is not set, so the result was not written`,
  );
  const failed = result.checks.filter((item) => item.outcome !== "PASSED").map((item) => item.name);
  expect(failed.length === 0, `checks failed: ${failed.join(", ")}`);
}

module.exports = { run };
