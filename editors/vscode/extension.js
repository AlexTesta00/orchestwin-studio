"use strict";

const crypto = require("node:crypto");
const fs = require("node:fs");
const path = require("node:path");
const { connectAgents } = require("./src/agents");
const { ARGUMENTS, commandLine } = require("./src/commands");
const { languageOf, text } = require("./src/messages");
const { KNOWLEDGE_FOLDER, readProject } = require("./src/project");
const { renderPanel } = require("./src/view");
const { readWhyAnswer, validSelector } = require("./src/why");

const VIEW_ID = "orchestwin.panel";
const TERMINAL_NAME = "OrchesTwin";
const SECTION = "orchestwin";
const PROGRAM_SETTING = "utCommand";
const DEFAULT_PROGRAM = "ut";
const REFRESH_DELAY = 300;
const LINK_PATH = Object.freeze([".orchestwin", "project.json"]);
const WATCHED_FILES = Object.freeze([
  ".orchestwin/project.json",
  ".orchestwin/tests/latest.json",
  ".orchestwin/code/latest.json",
  ".vscode/mcp.json",
]);
const TERMINAL_COMMANDS = Object.freeze({
  "orchestwin.status": "status",
  "orchestwin.test": "test",
  "orchestwin.align": "align",
  "orchestwin.recheck": "recheck",
  "orchestwin.code": "code",
  "orchestwin.tasks": "tasks",
  "orchestwin.twinsUpdate": "twinsUpdate",
});

function watchPattern(knowledge) {
  return `{${[...WATCHED_FILES, knowledge, `${knowledge}/**`].join(",")}}`;
}

function isFile(file) {
  try {
    return fs.statSync(file).isFile();
  } catch {
    return false;
  }
}

function createExtension(vscode, options = {}) {
  const delay =
    Number.isInteger(options.delay) && options.delay >= 0 ? options.delay : REFRESH_DELAY;
  const setTimer = typeof options.setTimeout === "function" ? options.setTimeout : setTimeout;
  const clearTimer =
    typeof options.clearTimeout === "function" ? options.clearTimeout : clearTimeout;
  const newNonce =
    typeof options.nonce === "function"
      ? options.nonce
      : () => crypto.randomBytes(16).toString("hex");
  const terminals = new Map();
  let view = null;
  let watchers = [];
  let watchedKey = null;
  let timer = null;
  let shown = null;
  let rendered = null;
  let status = "";
  let disposed = false;
  let why = {};
  let whyRoot = null;
  let whyRequest = 0;

  function language() {
    return languageOf(vscode.env.language);
  }

  function program() {
    const value = vscode.workspace.getConfiguration(SECTION).get(PROGRAM_SETTING, DEFAULT_PROGRAM);
    return typeof value === "string" && value.trim() !== "" ? value.trim() : DEFAULT_PROGRAM;
  }

  function folders() {
    const found = vscode.workspace.workspaceFolders;
    if (!Array.isArray(found)) {
      return [];
    }
    return found.filter((folder) => folder && folder.uri && typeof folder.uri.fsPath === "string");
  }

  function projectRoot() {
    const roots = folders().map((folder) => folder.uri.fsPath);
    return (
      roots.find((root) => isFile(path.join(root, ...LINK_PATH))) ??
      roots[0] ??
      null
    );
  }

  function disposeWatchers() {
    for (const item of watchers) {
      item.dispose();
    }
    watchers = [];
  }

  function watch(current) {
    const knowledge = current.project !== null ? current.project.knowledgeFolder : KNOWLEDGE_FOLDER;
    const list = folders();
    const key = JSON.stringify([list.map((folder) => folder.uri.fsPath), knowledge]);
    if (key === watchedKey) {
      return;
    }
    disposeWatchers();
    watchedKey = key;
    for (const folder of list) {
      const pattern = new vscode.RelativePattern(folder, watchPattern(knowledge));
      const watcher = vscode.workspace.createFileSystemWatcher(pattern);
      watchers.push(
        watcher,
        watcher.onDidCreate(schedule),
        watcher.onDidChange(schedule),
        watcher.onDidDelete(schedule),
      );
    }
  }

  function keyOf(current) {
    return JSON.stringify([current, language(), status, why]);
  }

  function render(force = false) {
    if (disposed) {
      return;
    }
    const current = readProject(projectRoot());
    if (whyRoot !== current.root) {
      why = {};
      whyRoot = current.root;
      whyRequest += 1;
    }
    watch(current);
    if (view === null) {
      return;
    }
    const key = keyOf(current);
    if (!force && key === rendered) {
      return;
    }
    shown = current;
    rendered = key;
    view.webview.html = renderPanel(current, {
      language: language(),
      nonce: newNonce(),
      cspSource: view.webview.cspSource,
      status,
      why,
    });
  }

  function schedule() {
    if (disposed) {
      return;
    }
    why = {};
    whyRequest += 1;
    if (timer !== null) {
      clearTimer(timer);
    }
    timer = setTimer(() => {
      timer = null;
      render();
    }, delay);
  }

  function say(message) {
    status = message;
    if (view === null) {
      return;
    }
    if (shown !== null) {
      rendered = keyOf(shown);
    }
    view.webview.postMessage({ type: "status", text: message });
  }

  function isOpen(terminal) {
    if (terminal.exitStatus !== undefined) {
      return false;
    }
    const open = vscode.window.terminals;
    return !Array.isArray(open) || open.includes(terminal);
  }

  function terminalFor(root) {
    const known = terminals.get(root);
    if (known !== undefined && isOpen(known)) {
      return known;
    }
    const terminal = vscode.window.createTerminal({ name: TERMINAL_NAME, cwd: root });
    terminals.set(root, terminal);
    return terminal;
  }

  function runInTerminal(id) {
    const root = projectRoot();
    const line = commandLine(id, program(), vscode.env.shell);
    if (root === null || line === null) {
      say(text(language(), "status.noFolder"));
      return;
    }
    const terminal = terminalFor(root);
    terminal.show();
    terminal.sendText(line, true);
    say(text(language(), "status.sent", { command: line }));
  }

  async function openReport() {
    const report = readProject(projectRoot()).tests.report;
    if (report === null) {
      say(text(language(), "status.noReport"));
      return;
    }
    try {
      await vscode.env.openExternal(vscode.Uri.file(report));
    } catch {
      say(text(language(), "status.reportFailed"));
      return;
    }
    say(text(language(), "status.reportOpened"));
  }

  function connect() {
    const root = projectRoot();
    if (root === null) {
      say(text(language(), "status.noFolder"));
      return;
    }
    const result = connectAgents(root, program());
    say(text(language(), `status.connect.${result.status}`));
    render();
  }

  function refresh() {
    why = {};
    whyRequest += 1;
    render(true);
  }

  async function openWhy(code) {
    const root = projectRoot();
    const current = readProject(root);
    if (
      root === null ||
      current.project === null ||
      current.project.id === null
    ) {
      say(text(language(), "status.noFolder"));
      return;
    }
    let selected = code;
    if (selected === undefined) {
      if (
        current.why.items.length > 0 &&
        typeof vscode.window.showQuickPick === "function"
      ) {
        const choice = await vscode.window.showQuickPick(
          current.why.items.map((node) => ({
            label: node.title || node.code,
            description: `${node.code} · v${node.reference.version_number ?? "—"}`,
            detail: node.key,
            key: node.key,
          })),
          {
            placeHolder: text(language(), "why.select"),
            matchOnDescription: true,
            matchOnDetail: true,
          },
        );
        selected = choice && choice.key;
      } else if (typeof vscode.window.showInputBox === "function") {
        selected = await vscode.window.showInputBox({
          prompt: text(language(), "why.code"),
          validateInput: (value) =>
            validSelector(value) ? undefined : text(language(), "why.invalid"),
        });
      }
      if (selected === undefined) {
        return;
      }
    }
    if (!validSelector(selected)) {
      say(text(language(), "why.invalid"));
      return;
    }
    if (disposed || root !== projectRoot()) {
      return;
    }
    whyRoot = root;
    const request = ++whyRequest;
    why = { code: selected };
    status = text(language(), "why.loading");
    render(true);
    const result = await readWhyAnswer(
      root,
      program(),
      selected,
      current.project.id,
      options.execFile,
    );
    if (disposed || request !== whyRequest || root !== projectRoot()) {
      return;
    }
    why = { ...result, code: selected };
    const message =
      result.status === "OK"
        ? "why.offline"
        : result.status === "UNAVAILABLE"
          ? "why.unavailable"
          : result.status === "WHY_CODE_AMBIGUOUS"
            ? "why.ambiguous"
            : ["INVALID", "WHY_CODE_INVALID", "WHY_CODE_NOT_FOUND"].includes(
                  result.status,
                )
              ? "why.invalid"
              : "why.failed";
    status = text(language(), message);
    render(true);
  }

  async function focusWhy(code) {
    if (typeof vscode.commands.executeCommand === "function") {
      await vscode.commands.executeCommand(`${VIEW_ID}.focus`);
    }
    return openWhy(code);
  }

  function receive(message) {
    if (message === null || typeof message !== "object" || typeof message.command !== "string") {
      return undefined;
    }
    const id = message.command;
    if (id === "why") {
      return openWhy(message.code);
    }
    if (Object.hasOwn(ARGUMENTS, id)) {
      return runInTerminal(id);
    }
    if (id === "openReport") {
      return openReport();
    }
    if (id === "connectAgents") {
      return connect();
    }
    if (id === "refresh") {
      return refresh();
    }
    return undefined;
  }

  function resolveWebviewView(webviewView) {
    view = webviewView;
    shown = null;
    rendered = null;
    webviewView.webview.options = { enableScripts: true, localResourceRoots: [] };
    const listeners = [webviewView.webview.onDidReceiveMessage(receive)];
    listeners.push(
      webviewView.onDidDispose(() => {
        if (view === webviewView) {
          view = null;
          shown = null;
          rendered = null;
        }
        for (const listener of listeners) {
          listener.dispose();
        }
      }),
    );
    render(true);
  }

  function dispose() {
    disposed = true;
    whyRequest += 1;
    why = {};
    if (timer !== null) {
      clearTimer(timer);
      timer = null;
    }
    disposeWatchers();
    watchedKey = null;
    terminals.clear();
    view = null;
  }

  function activate(context) {
    const subscriptions = context.subscriptions;
    const handlers = {
      "orchestwin.refresh": refresh,
      "orchestwin.openReport": openReport,
      "orchestwin.connectAgents": connect,
      "orchestwin.why": focusWhy,
    };
    for (const [command, id] of Object.entries(TERMINAL_COMMANDS)) {
      handlers[command] = () => runInTerminal(id);
    }
    subscriptions.push(vscode.window.registerWebviewViewProvider(VIEW_ID, { resolveWebviewView }));
    for (const [command, handler] of Object.entries(handlers)) {
      subscriptions.push(vscode.commands.registerCommand(command, handler));
    }
    subscriptions.push(vscode.workspace.onDidChangeWorkspaceFolders(schedule));
    subscriptions.push({ dispose });
    watch(readProject(projectRoot()));
  }

  return { activate, dispose, projectRoot, receive, refresh };
}

let active = null;

function activate(context) {
  active = createExtension(require("vscode"));
  active.activate(context);
}

function deactivate() {
  if (active !== null) {
    active.dispose();
    active = null;
  }
}

module.exports = { activate, createExtension, deactivate };
