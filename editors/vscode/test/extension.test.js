"use strict";

const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const { after, afterEach, before, describe, it } = require("node:test");
const fixtures = require("./fixtures");
const extensionModule = require("../extension");
const { posixPath } = require("../src/agents");
const { text } = require("../src/messages");

const MANIFEST = JSON.parse(fs.readFileSync(path.join(__dirname, "..", "package.json"), "utf8"));
const CSP_SOURCE = "https://file+.vscode-resource.vscode-cdn.net";

function disposable(onDispose = () => {}) {
  let done = false;
  return {
    dispose() {
      if (!done) {
        done = true;
        onDispose();
      }
    },
  };
}

function emitter() {
  const listeners = [];
  return {
    listeners,
    event(listener) {
      listeners.push(listener);
      return disposable(() => listeners.splice(listeners.indexOf(listener), 1));
    },
    fire(value) {
      return [...listeners].map((listener) => listener(value));
    },
  };
}

function fakeTerminal(options, open) {
  const terminal = {
    options,
    exitStatus: undefined,
    shown: 0,
    sent: [],
    show() {
      terminal.shown += 1;
    },
    sendText(line, addNewLine) {
      terminal.sent.push([line, addNewLine]);
    },
    close() {
      terminal.exitStatus = { code: undefined };
      open.splice(open.indexOf(terminal), 1);
    },
  };
  return terminal;
}

function fakeWatcher(pattern) {
  const events = { create: emitter(), change: emitter(), delete: emitter() };
  const watcher = {
    pattern,
    disposed: false,
    onDidCreate: (listener) => events.create.event(listener),
    onDidChange: (listener) => events.change.event(listener),
    onDidDelete: (listener) => events.delete.event(listener),
    fire(kind) {
      events[kind].fire({ scheme: "file", fsPath: pattern.pattern });
    },
    dispose() {
      watcher.disposed = true;
    },
  };
  return watcher;
}

function fakeVscode({ folders = [], language = "en", settings = {}, shell } = {}) {
  const commands = new Map();
  const providers = new Map();
  const created = [];
  const open = [];
  const watchers = [];
  const opened = [];
  const folderEvents = emitter();
  const Uri = { file: (fsPath) => ({ scheme: "file", fsPath }) };
  class RelativePattern {
    constructor(base, pattern) {
      this.base = base;
      this.pattern = pattern;
    }
  }
  const vscode = {
    Uri,
    RelativePattern,
    env: {
      language,
      shell,
      openExternal: async (uri) => {
        opened.push(uri);
        return true;
      },
    },
    workspace: {
      workspaceFolders: folders.map((folder, index) => ({
        uri: Uri.file(folder),
        name: path.basename(folder),
        index,
      })),
      getConfiguration: (section) => ({
        get: (key, fallback) =>
          Object.hasOwn(settings, `${section}.${key}`) ? settings[`${section}.${key}`] : fallback,
      }),
      createFileSystemWatcher(pattern) {
        const watcher = fakeWatcher(pattern);
        watchers.push(watcher);
        return watcher;
      },
      onDidChangeWorkspaceFolders: (listener) => folderEvents.event(listener),
    },
    window: {
      terminals: open,
      createTerminal(options) {
        const terminal = fakeTerminal(options, open);
        created.push(terminal);
        open.push(terminal);
        return terminal;
      },
      registerWebviewViewProvider(id, provider) {
        providers.set(id, provider);
        return disposable(() => providers.delete(id));
      },
    },
    commands: {
      registerCommand(id, handler) {
        assert.ok(!commands.has(id), `${id} registered twice`);
        commands.set(id, handler);
        return disposable(() => commands.delete(id));
      },
    },
  };
  return { vscode, commands, providers, created, open, watchers, opened, folderEvents };
}

function fakeView() {
  const received = emitter();
  const disposed = emitter();
  const htmls = [];
  const posted = [];
  return {
    htmls,
    posted,
    webview: {
      options: undefined,
      cspSource: CSP_SOURCE,
      onDidReceiveMessage: (listener) => received.event(listener),
      postMessage(message) {
        posted.push(message);
        return Promise.resolve(true);
      },
      get html() {
        return htmls.length === 0 ? "" : htmls[htmls.length - 1];
      },
      set html(value) {
        htmls.push(value);
      },
    },
    onDidDispose: (listener) => disposed.event(listener),
    send(message) {
      return received.fire(message);
    },
    close() {
      disposed.fire();
    },
    listening() {
      return received.listeners.length;
    },
  };
}

function fakeTimers() {
  const pending = new Map();
  let last = 0;
  return {
    delays: [],
    setTimeout(callback, delay) {
      last += 1;
      pending.set(last, callback);
      this.delays.push(delay);
      return last;
    },
    clearTimeout(id) {
      pending.delete(id);
    },
    pending() {
      return pending.size;
    },
    run() {
      const due = [...pending.values()];
      pending.clear();
      for (const callback of due) {
        callback();
      }
      return due.length;
    },
  };
}

function start(options = {}) {
  const fake = fakeVscode(options);
  const timers = fakeTimers();
  const extension = extensionModule.createExtension(fake.vscode, {
    delay: 250,
    setTimeout: timers.setTimeout.bind(timers),
    clearTimeout: timers.clearTimeout.bind(timers),
    nonce: () => "fixednonce",
  });
  const context = { subscriptions: [] };
  extension.activate(context);
  const view = fakeView();
  fake.providers.get("orchestwin.panel").resolveWebviewView(view, {}, {});
  return {
    ...fake,
    timers,
    extension,
    context,
    view,
    stop() {
      for (const subscription of context.subscriptions) {
        subscription.dispose();
      }
    },
  };
}

function plain(html) {
  return html
    .replace(/<script[\s\S]*?<\/script>/g, " ")
    .replace(/<style[\s\S]*?<\/style>/g, " ")
    .replace(/<\/?code>/g, "")
    .replace(/<[^>]+>/g, " ")
    .replace(/&#39;/g, "'")
    .replace(/\s+/g, " ");
}

describe("the extension", () => {
  let base;
  let root;
  let unlinked;
  let counter = 0;
  let session = null;

  before(() => {
    base = fixtures.makeTemporaryFolder();
    root = fixtures.writeCompleteProject(path.join(base, "tip calculator"), "new");
    unlinked = fixtures.writeUnlinkedFolder(path.join(base, "notes"));
  });

  after(() => {
    fixtures.removeFolder(base);
  });

  afterEach(() => {
    if (session !== null) {
      session.stop();
      session = null;
    }
  });

  function freshProject(shape = "new") {
    counter += 1;
    return fixtures.writeCompleteProject(path.join(base, `project ${counter}`), shape);
  }

  it("registers every command of package.json and no other", () => {
    session = start({ folders: [root] });
    const contributed = MANIFEST.contributes.commands.map((command) => command.command).sort();
    assert.deepEqual([...session.commands.keys()].sort(), contributed);
    assert.deepEqual([...session.providers.keys()], ["orchestwin.panel"]);
  });

  it("shows the panel of the project in its view", () => {
    session = start({ folders: [root] });
    const html = session.view.webview.html;
    assert.deepEqual(session.view.webview.options, { enableScripts: true, localResourceRoots: [] });
    assert.ok(html.includes("<h1>Tip calculator for waiters</h1>"));
    assert.ok(html.includes("style-src 'nonce-fixednonce'; script-src 'nonce-fixednonce';"));
    assert.ok(!html.includes(CSP_SOURCE));
    assert.equal(session.view.htmls.length, 1);
  });

  it("writes ut test in a terminal opened in the root of the project", () => {
    session = start({ folders: [root] });
    session.view.send({ command: "test" });
    assert.equal(session.created.length, 1);
    const [terminal] = session.created;
    assert.deepEqual(terminal.options, { name: "OrchesTwin", cwd: root });
    assert.equal(terminal.shown, 1);
    assert.deepEqual(terminal.sent, [["ut test", true]]);
    assert.deepEqual(session.view.posted, [
      { type: "status", text: text("en", "status.sent", { command: "ut test" }) },
    ]);
    assert.equal(session.view.htmls.length, 1);
  });

  it("reuses the terminal while it is open and opens another one after it closed", () => {
    session = start({ folders: [root] });
    session.view.send({ command: "align" });
    session.view.send({ command: "recheck" });
    assert.equal(session.created.length, 1);
    assert.deepEqual(session.created[0].sent, [
      ["ut align", true],
      ["ut align --recheck", true],
    ]);
    session.created[0].close();
    session.view.send({ command: "tasksFromTest" });
    assert.equal(session.created.length, 2);
    assert.deepEqual(session.created[1].sent, [["ut tasks from-test", true]]);
    assert.equal(session.created[1].options.cwd, root);
  });

  it("starts the commands of the palette in the same terminal", async () => {
    session = start({ folders: [root] });
    const expected = {
      "orchestwin.status": "ut status",
      "orchestwin.test": "ut test",
      "orchestwin.align": "ut align",
      "orchestwin.recheck": "ut align --recheck",
      "orchestwin.code": "ut code",
      "orchestwin.tasks": "ut tasks",
      "orchestwin.twinsUpdate": "ut twins update",
    };
    for (const command of Object.keys(expected)) {
      await session.commands.get(command)();
    }
    assert.equal(session.created.length, 1);
    assert.deepEqual(
      session.created[0].sent.map(([line]) => line),
      Object.values(expected),
    );
  });

  it("uses the program configured for the buttons", () => {
    const program = path.join(base, "tools dir", "ut");
    session = start({
      folders: [root],
      settings: { "orchestwin.utCommand": program },
      shell: "pwsh",
    });
    session.view.send({ command: "test" });
    assert.deepEqual(session.created[0].sent, [[`& "${program}" test`, true]]);
    session.stop();
    session = start({ folders: [root], settings: { "orchestwin.utCommand": program } });
    session.view.send({ command: "code" });
    assert.deepEqual(session.created[0].sent, [[`"${program}" code`, true]]);
  });

  it("watches the files it reads", () => {
    session = start({ folders: [root] });
    assert.equal(session.watchers.length, 1);
    const [watcher] = session.watchers;
    assert.equal(watcher.pattern.base, session.vscode.workspace.workspaceFolders[0]);
    for (const file of [
      ".orchestwin/project.json",
      ".orchestwin/tests/latest.json",
      ".orchestwin/code/latest.json",
      ".vscode/mcp.json",
      "orchestwin/**",
    ]) {
      assert.ok(watcher.pattern.pattern.includes(file), file);
    }
  });

  it("renders again once after a burst of changes to a watched file", () => {
    const project = freshProject();
    session = start({ folders: [project] });
    const state = fixtures.readJson(project, "orchestwin/state/state.json");
    state.tasks.push({
      code: "TSK-006",
      text: "A task written after the panel opened.",
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
      created_at: "2026-09-30T10:00:00+00:00",
      status: "OPEN",
      closed_at: null,
      note: null,
    });
    fixtures.writeJson(project, "orchestwin/state/state.json", state);
    const [watcher] = session.watchers;
    watcher.fire("change");
    watcher.fire("create");
    watcher.fire("delete");
    assert.equal(session.timers.pending(), 1);
    assert.deepEqual(session.timers.delays, [250, 250, 250]);
    assert.equal(session.view.htmls.length, 1);
    assert.equal(session.timers.run(), 1);
    assert.equal(session.view.htmls.length, 2);
    assert.ok(session.view.webview.html.includes("A task written after the panel opened."));
  });

  it("does not render again when nothing it shows has changed", () => {
    session = start({ folders: [root] });
    session.watchers[0].fire("change");
    session.timers.run();
    assert.equal(session.view.htmls.length, 1);
  });

  it("renders again on the refresh command and when the folders of the workspace change", () => {
    session = start({ folders: [root] });
    session.commands.get("orchestwin.refresh")();
    assert.equal(session.view.htmls.length, 2);
    session.folderEvents.fire({ added: [], removed: [] });
    assert.equal(session.timers.pending(), 1);
    session.timers.run();
    assert.equal(session.view.htmls.length, 2);
  });

  it("opens the report named by latest.json in the default browser", async () => {
    session = start({ folders: [root] });
    await session.commands.get("orchestwin.openReport")();
    const report = path.join(root, ".orchestwin", "tests", fixtures.RUN_FOLDER, "report.html");
    assert.deepEqual(session.opened, [{ scheme: "file", fsPath: report }]);
    await session.view.send({ command: "openReport" })[0];
    assert.equal(session.opened.length, 2);
    assert.deepEqual(session.view.posted.at(-1), {
      type: "status",
      text: text("en", "status.reportOpened"),
    });
  });

  it("says that there is no report yet", async () => {
    const project = fixtures.writePartialProject(path.join(base, "partial"));
    session = start({ folders: [project] });
    await session.commands.get("orchestwin.openReport")();
    assert.deepEqual(session.opened, []);
    assert.deepEqual(session.view.posted, [
      { type: "status", text: text("en", "status.noReport") },
    ]);
  });

  it("connects the twins to the agents of the editor with the configured program", () => {
    const project = freshProject();
    const program = path.join(base, "tools dir", "ut");
    session = start({ folders: [project], settings: { "orchestwin.utCommand": program } });
    assert.ok(session.view.webview.html.includes(text("en", "agents.MISSING")));
    session.view.send({ command: "connectAgents" });
    const written = JSON.parse(fs.readFileSync(path.join(project, ".vscode", "mcp.json"), "utf8"));
    assert.deepEqual(written.servers["orchestwin-twins"], {
      type: "stdio",
      command: program,
      args: ["--project-dir", posixPath(project), "mcp"],
      cwd: posixPath(project),
    });
    assert.equal(session.view.htmls.length, 2);
    assert.ok(session.view.webview.html.includes(text("en", "agents.CONNECTED")));
    const created = text("en", "status.connect.CREATED");
    assert.ok(plain(session.view.webview.html).includes(created));
    assert.deepEqual(session.view.posted, [{ type: "status", text: created }]);
    session.view.send({ command: "connectAgents" });
    assert.deepEqual(session.view.posted.at(-1), {
      type: "status",
      text: text("en", "status.connect.UNCHANGED"),
    });
  });

  it("shows the first folder of the workspace that is linked to a project", () => {
    session = start({ folders: [unlinked, root] });
    assert.equal(session.extension.projectRoot(), root);
    assert.ok(session.view.webview.html.includes("<h1>Tip calculator for waiters</h1>"));
    assert.equal(session.watchers.length, 2);
    session.view.send({ command: "code" });
    assert.equal(session.created[0].options.cwd, root);
  });

  it("works in a workspace without folders", () => {
    session = start({ folders: [] });
    assert.ok(
      plain(session.view.webview.html).includes(text("en", "next.noFolder").replace(/`/g, "")),
    );
    session.view.send({ command: "test" });
    session.view.send({ command: "connectAgents" });
    assert.equal(session.created.length, 0);
    assert.deepEqual(session.view.posted, [
      { type: "status", text: text("en", "status.noFolder") },
      { type: "status", text: text("en", "status.noFolder") },
    ]);
    assert.equal(session.watchers.length, 0);
  });

  it("speaks Italian when the editor does", () => {
    session = start({ folders: [root], language: "it-IT" });
    assert.ok(session.view.webview.html.includes('<html lang="it">'));
    assert.ok(session.view.webview.html.includes(text("it", "next.title")));
    session.view.send({ command: "tasks" });
    assert.deepEqual(session.view.posted, [
      { type: "status", text: text("it", "status.sent", { command: "ut tasks" }) },
    ]);
  });

  it("ignores the messages it does not know", () => {
    session = start({ folders: [root] });
    for (const message of [
      null,
      "test",
      3,
      {},
      { command: 3 },
      { command: "rm" },
      { command: "toString" },
    ]) {
      session.view.send(message);
    }
    assert.equal(session.created.length, 0);
    assert.deepEqual(session.view.posted, []);
    assert.deepEqual(session.opened, []);
  });

  it("forgets the view when it is closed", () => {
    session = start({ folders: [root] });
    session.view.close();
    assert.equal(session.view.listening(), 0);
    session.commands.get("orchestwin.refresh")();
    session.commands.get("orchestwin.test")();
    assert.equal(session.view.htmls.length, 1);
    assert.deepEqual(session.view.posted, []);
    assert.equal(session.created.length, 1);
  });

  it("stops its timers and its watchers when it is disposed", () => {
    session = start({ folders: [root] });
    session.watchers[0].fire("change");
    assert.equal(session.timers.pending(), 1);
    session.stop();
    assert.equal(session.timers.pending(), 0);
    assert.ok(session.watchers.every((watcher) => watcher.disposed));
    assert.equal(session.commands.size, 0);
    assert.equal(session.providers.size, 0);
    session = null;
  });

  it("exports activate, deactivate and createExtension", () => {
    assert.equal(typeof extensionModule.activate, "function");
    assert.equal(typeof extensionModule.createExtension, "function");
    assert.doesNotThrow(() => extensionModule.deactivate());
  });
});
