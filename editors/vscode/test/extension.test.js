"use strict";

const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const { after, afterEach, before, describe, it } = require("node:test");
const fixtures = require("./fixtures");
const validationData = require("./validation-fixtures");
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
    execFile: options.execFile,
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
    session.view.send({ command: "verify" });
    session.view.send({ command: "recheck" });
    assert.equal(session.created.length, 1);
    assert.deepEqual(session.created[0].sent, [
      ["ut verify", true],
      ["ut verify --recheck", true],
    ]);
    session.created[0].close();
    session.view.send({ command: "align" });
    session.view.send({ command: "tasksFromTest" });
    assert.equal(session.created.length, 2);
    assert.deepEqual(session.created[1].sent, [
      ["ut align", true],
      ["ut tasks from-test", true],
    ]);
    assert.equal(session.created[1].options.cwd, root);
  });

  it("starts the commands of the palette in the same terminal", async () => {
    session = start({ folders: [root] });
    const expected = {
      "orchestwin.status": "ut status",
      "orchestwin.test": "ut test",
      "orchestwin.verify": "ut verify",
      "orchestwin.recheck": "ut verify --recheck",
      "orchestwin.align": "ut align",
      "orchestwin.push": "ut push",
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
      ".orchestwin/align/latest.json",
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

  it("shows the latest run of ut align once its file appears and drops a broken one", () => {
    const project = fixtures.writeCompleteProject(path.join(base, "aligned"), "old");
    session = start({ folders: [project] });
    assert.ok(!session.view.webview.html.includes(text("en", "knowledge.run")));
    assert.ok(session.view.webview.html.includes('data-step="CODE"'));
    fixtures.writeJson(project, ".orchestwin/align/latest.json", {
      schema_version: 1,
      run_id: "0c1d2e3f-4a5b-4c6d-8e7f-9a0b1c2d3e4f",
      finished_at: "2026-10-06T10:20:00+00:00",
      from_commit: fixtures.ALIGNED_COMMIT,
      to_commit: fixtures.DRIFT_COMMIT,
      proposals: 5,
      waiting: 2,
      applied: 2,
      skipped: 1,
    });
    session.watchers[0].fire("change");
    session.timers.run();
    assert.equal(session.view.htmls.length, 2);
    const html = session.view.webview.html;
    assert.ok(html.includes(text("en", "knowledge.run")));
    assert.ok(html.includes('data-step="ALIGN"'));
    assert.ok(plain(html).includes("ut align --pending"));
    assert.equal(session.created.length, 0);
    fixtures.writeText(project, ".orchestwin/align/latest.json", "{ broken");
    session.watchers[0].fire("change");
    session.timers.run();
    assert.equal(session.view.htmls.length, 3);
    assert.ok(!session.view.webview.html.includes(text("en", "knowledge.run")));
    assert.ok(session.view.webview.html.includes('data-step="CODE"'));
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

  function whyAnswer(title = "Exact requirement") {
    return {
      kind: "orchestwin.why-answer",
      schema_version: 1,
      project_id: fixtures.PROJECT_ID,
      target: {
        key: "REQUIREMENT:req:3:hash:context",
        code: "REQ-001",
        kind: "REQUIREMENT",
        title,
        display_status: "UNKNOWN",
        current: true,
        reference: {
          artifact_id: "req",
          version_number: 3,
          content_hash: "hash",
        },
        rationale: null,
        citations: [],
        gaps: [],
        declared_context: { perspectives: [] },
      },
      summary: {
        upstream_count: 0,
        downstream_count: 0,
        complete_to_twin: false,
        complete_to_evidence: false,
        all_paths_complete: false,
      },
      upstream: [],
      downstream: [],
      links: [],
      gaps: [],
      human_validation: [],
      declared_context: { perspectives: [] },
      limits: [],
    };
  }

  it("opens why through the command and renders a verified offline answer without a terminal", async () => {
    const calls = [];
    session = start({
      folders: [root],
      execFile: (program, args, options, finish) => {
        calls.push({ program, args, options });
        finish(null, JSON.stringify(whyAnswer()), "");
      },
    });
    const focused = [];
    session.vscode.commands.executeCommand = async (command) => {
      focused.push(command);
    };
    await session.commands.get("orchestwin.why")("REQ-001");
    assert.deepEqual(focused, ["orchestwin.panel.focus"]);
    assert.deepEqual(calls[0].args, ["why", "REQ-001", "--offline", "--json"]);
    assert.equal(calls[0].options.shell, false);
    assert.equal(calls[0].options.cwd, root);
    assert.equal(session.created.length, 0);
    assert.equal(session.opened.length, 0);
    assert.ok(session.view.webview.html.includes("Exact requirement"));
    assert.ok(session.view.webview.html.includes(text("en", "why.offline")));
    await session.extension.receive({ command: "why", code: "REQ-001;calc" });
    assert.equal(calls.length, 1);
  });

  it("asks for a selector in a legacy folder and presents ambiguity candidates explicitly", async () => {
    const key = "ELEMENT:elm:1:hash:alternative-one";
    const calls = [];
    session = start({
      folders: [root],
      language: "it",
      execFile: (_program, args, _options, finish) => {
        calls.push(args);
        if (args[1] === "ELM-001") {
          finish(
            { code: 2 },
            "",
            JSON.stringify({
              error: { code: "WHY_CODE_AMBIGUOUS", candidates: [key] },
            }),
          );
        } else {
          finish(
            null,
            JSON.stringify(whyAnswer("Element of selected alternative")),
            "",
          );
        }
      },
    });
    session.vscode.window.showInputBox = async (options) => {
      assert.equal(options.prompt, text("it", "why.code"));
      assert.equal(options.validateInput("ELM-001"), undefined);
      assert.equal(options.validateInput("$(bad)"), text("it", "why.invalid"));
      return "ELM-001";
    };
    await session.commands.get("orchestwin.why")();
    assert.ok(plain(session.view.webview.html).includes(text("it", "why.ambiguous")));
    assert.ok(session.view.webview.html.includes(`data-code="${key}"`));
    await session.extension.receive({ command: "why", code: key });
    assert.equal(calls[1][1], key);
    assert.ok(
      session.view.webview.html.includes("Element of selected alternative"),
    );
  });

  it("discards an earlier why response after refresh and after disposal", async () => {
    const callbacks = [];
    session = start({
      folders: [root],
      execFile: (_program, _args, _options, finish) => {
        callbacks.push(finish);
      },
    });
    const pending = session.extension.receive({
      command: "why",
      code: "REQ-001",
    });
    session.commands.get("orchestwin.refresh")();
    callbacks[0](null, JSON.stringify(whyAnswer("Stale response")), "");
    await pending;
    assert.ok(!session.view.webview.html.includes("Stale response"));
    const disposed = session.extension.receive({
      command: "why",
      code: "REQ-001",
    });
    session.extension.dispose();
    callbacks[1](null, JSON.stringify(whyAnswer("Disposed response")), "");
    await disposed;
    assert.ok(!session.view.webview.html.includes("Disposed response"));
  });

  it("reads validation only after a gesture, offline by default and explicitly from Studio", async () => {
    const calls = [];
    session = start({ folders: [root], execFile: (program, args, options, finish) => {
      calls.push({ program, args, options });
      finish(null, JSON.stringify(validationData.overview()), "");
    } });
    assert.equal(calls.length, 0);
    await session.commands.get("orchestwin.validation")();
    assert.deepEqual(calls[0].args, ["validation", "--offline", "--json"]);
    assert.equal(calls[0].options.shell, false);
    assert.ok(session.view.webview.html.includes(text("en", "validation.offline")));
    await session.extension.receive({ command: "validation", mode: "studio" });
    assert.deepEqual(calls[1].args, ["validation", "--json"]);
    assert.ok(session.view.webview.html.includes(text("en", "validation.studio")));
    await session.extension.receive({ command: "validation", mode: "write" });
    await session.extension.receive({ command: "saveHypothesis" });
    await session.extension.receive({ command: "recordOutcome" });
    assert.equal(calls.length, 2);
    assert.equal(session.created.length, 0);
    assert.equal(session.opened.length, 0);
  });

  it("reads the requested walkthrough filters without changing the design or opening a terminal", async () => {
    const calls = [];
    session = start({ folders: [root], language: "it", execFile: (_program, args, _options, finish) => {
      calls.push(args);
      finish(null, JSON.stringify(validationData.walkthrough()), "");
    } });
    await session.extension.receive({ command: "validationWalkthrough", code: "SCN-001", alternative: "alternative-id", documentHash: validationData.HASH, mode: "studio" });
    assert.deepEqual(calls[0], ["validation", "walkthrough", "SCN-001", "--alternative", "alternative-id", "--document-hash", validationData.HASH, "--json"]);
    assert.ok(session.view.webview.html.includes("Original expected outcome"));
    assert.ok(session.view.webview.html.includes(text("it", "validation.linkToComplete")));
    await session.extension.receive({ command: "validationWalkthrough", code: "SCN-001;calc" });
    assert.equal(calls.length, 1);
    assert.ok(plain(session.view.webview.html).includes(text("it", "validation.invalid")));
    assert.equal(session.created.length, 0);
  });

  it("selects an exact scenario for the palette command and cancels cleanly", async () => {
    const calls = [];
    session = start({ folders: [root], execFile: (_program, args, _options, finish) => {
      calls.push(args);
      finish(null, JSON.stringify(validationData.walkthrough()), "");
    } });
    session.vscode.window.showInputBox = async (options) => {
      assert.equal(options.prompt, text("en", "validation.scenarioKey"));
      assert.equal(options.validateInput("SCN-001"), undefined);
      assert.equal(options.validateInput("--help"), text("en", "validation.invalid"));
      return "SCN-001";
    };
    await session.commands.get("orchestwin.scenarioWalkthrough")();
    assert.deepEqual(calls[0], ["validation", "walkthrough", "SCN-001", "--offline", "--json"]);
    session.vscode.window.showInputBox = async () => undefined;
    await session.commands.get("orchestwin.scenarioWalkthrough")();
    assert.equal(calls.length, 1);
  });

  it("discards validation reads superseded by a newer request or by a folder refresh", async () => {
    const callbacks = [];
    session = start({ folders: [root], execFile: (_program, _args, _options, finish) => callbacks.push(finish) });
    const old = session.extension.receive({ command: "validation" });
    const newer = session.extension.receive({ command: "validation", mode: "studio" });
    const latestAnswer = validationData.overview({ hypotheses: [validationData.hypothesis({ question: "Latest response" })] });
    callbacks[1](null, JSON.stringify(latestAnswer), "");
    await newer;
    callbacks[0](null, JSON.stringify(validationData.overview({ hypotheses: [validationData.hypothesis({ question: "Stale response" })] })), "");
    await old;
    assert.ok(session.view.webview.html.includes("Latest response"));
    assert.ok(!session.view.webview.html.includes("Stale response"));
    const refreshed = session.extension.receive({ command: "validation" });
    session.watchers[0].fire("change");
    session.timers.run();
    callbacks[2](null, JSON.stringify(latestAnswer), "");
    await refreshed;
    assert.ok(!session.view.webview.html.includes("Latest response"));
  });

  it("discards a walkthrough from an earlier project or after disposal", async () => {
    const callbacks = [];
    session = start({ folders: [root], execFile: (_program, _args, _options, finish) => callbacks.push(finish) });
    const pending = session.extension.receive({ command: "validationWalkthrough", code: "SCN-001" });
    const other = freshProject();
    session.vscode.workspace.workspaceFolders = [{ uri: session.vscode.Uri.file(other), name: "other", index: 0 }];
    session.folderEvents.fire();
    session.timers.run();
    callbacks[0](null, JSON.stringify(validationData.walkthrough({ expected_outcome: "Earlier project response" })), "");
    await pending;
    assert.ok(!session.view.webview.html.includes("Earlier project response"));
    const disposed = session.extension.receive({ command: "validationWalkthrough", code: "SCN-001" });
    session.extension.dispose();
    callbacks[1](null, JSON.stringify(validationData.walkthrough({ expected_outcome: "Disposed walkthrough" })), "");
    await disposed;
    assert.ok(!session.view.webview.html.includes("Disposed walkthrough"));
  });

  it("clears cached validation before a read in another project, even before a watcher refresh", async () => {
    session = start({ folders: [root], execFile: (_program, args, _options, finish) => {
      finish(null, JSON.stringify(args[0] === "why" ? whyAnswer("Other project requirement") : validationData.overview({ hypotheses: [validationData.hypothesis({ question: "Earlier cached validation" })] })), "");
    } });
    await session.extension.receive({ command: "validation" });
    assert.ok(session.view.webview.html.includes("Earlier cached validation"));
    const other = freshProject();
    session.vscode.workspace.workspaceFolders = [{ uri: session.vscode.Uri.file(other), name: "other", index: 0 }];
    await session.extension.receive({ command: "why", code: "REQ-001" });
    assert.ok(session.view.webview.html.includes("Other project requirement"));
    assert.ok(!session.view.webview.html.includes("Earlier cached validation"));
  });
});
