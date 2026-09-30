"use strict";

const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const { pathToFileURL } = require("node:url");
const { after, before, describe, it } = require("node:test");
const fixtures = require("./fixtures");
const { readProject } = require("../src/project");

const EXTENSION_ROOT = path.resolve(__dirname, "..");
const SCRIPT = path.join(EXTENSION_ROOT, "scripts", "host-check.mjs");
const RUNNER = path.join(EXTENSION_ROOT, "test", "host", "runner.js");

function collector() {
  const written = [];
  return {
    stream: {
      write(value) {
        written.push(String(value));
        return true;
      },
    },
    text: () => written.join(""),
  };
}

function never(milliseconds, signal) {
  return new Promise((resolve, reject) => {
    if (signal !== undefined) {
      signal.addEventListener("abort", () => reject(new Error("aborted")), { once: true });
    }
  });
}

function onlyPauses(milliseconds, signal) {
  return signal === undefined ? Promise.resolve() : never(milliseconds, signal);
}

function resultOf(outcomes) {
  const names = ["activation", "panel", "terminal", "agents"];
  return {
    schema_version: 1,
    vscode_version: "1.139.1",
    language: "en",
    extension_version: "0.1.0",
    checks: outcomes.map((outcome, index) => ({
      name: names[index],
      outcome,
      detail: `detail ${index}`,
    })),
  };
}

describe("the check of the panel in the installed editor", () => {
  let base;
  let host;
  let counter = 0;

  before(async () => {
    base = fixtures.makeTemporaryFolder();
    host = await import(pathToFileURL(SCRIPT).href);
  });

  after(() => {
    fixtures.removeFolder(base);
  });

  function folder(name) {
    counter += 1;
    const created = path.join(base, `${name} ${counter}`);
    fs.mkdirSync(created, { recursive: true });
    return created;
  }

  function session({ finish, writes, output = "", env = {} } = {}) {
    const out = collector();
    const errors = collector();
    const tmpdir = folder("tmp");
    const editor = fixtures.writeText(folder("editor"), "Code", "not an editor\n");
    const launches = [];
    const stopped = [];
    let release = null;
    const io = {
      env: { [host.EXECUTABLE_VARIABLE]: editor, ...env },
      platform: process.platform,
      tmpdir,
      home: folder("home"),
      stdout: out.stream,
      stderr: errors.stream,
      wait: never,
      now: () => 0,
      stopTree(pid) {
        stopped.push(pid);
        if (release !== null) {
          release({ code: null, signal: "SIGKILL", error: null });
        }
        return true;
      },
      launch(executable, args, childEnv, platform) {
        const file = childEnv[host.RESULT_VARIABLE];
        const workspace = args[args.length - 1];
        launches.push({
          executable,
          args,
          env: childEnv,
          platform,
          linked: fs.existsSync(path.join(workspace, ".orchestwin", "project.json")),
        });
        if (writes !== undefined) {
          fixtures.writeText(
            path.dirname(file),
            path.basename(file),
            typeof writes === "string" ? writes : `${JSON.stringify(writes, null, 2)}\n`,
          );
        }
        const exited =
          finish === undefined
            ? new Promise((resolve) => {
                release = resolve;
              })
            : Promise.resolve(finish);
        return { pid: 4242, exited, output: () => output };
      },
    };
    return { io, out, errors, tmpdir, editor, launches, stopped };
  }

  it("looks for the editor in the usual places of Windows, macOS and Linux", () => {
    const local = path.join(base, "Local");
    const programs = path.join(base, "Program Files");
    assert.deepEqual(
      host.candidateExecutables({
        platform: "win32",
        env: { LOCALAPPDATA: local, ProgramFiles: programs },
      }),
      [
        path.win32.join(local, "Programs", "Microsoft VS Code", "Code.exe"),
        path.win32.join(programs, "Microsoft VS Code", "Code.exe"),
      ],
    );
    assert.deepEqual(
      host.candidateExecutables({
        platform: "win32",
        env: { localappdata: local, PROGRAMFILES: programs },
      }),
      [
        path.win32.join(local, "Programs", "Microsoft VS Code", "Code.exe"),
        path.win32.join(programs, "Microsoft VS Code", "Code.exe"),
      ],
    );
    assert.deepEqual(host.candidateExecutables({ platform: "win32", env: {} }), []);
    const mac = host.candidateExecutables({ platform: "darwin", env: {} });
    assert.deepEqual(mac, [...host.MACOS_EXECUTABLES]);
    assert.ok(
      mac.every((file) => file.includes(path.posix.join("Visual Studio Code.app", "Contents"))),
    );
    assert.deepEqual(
      host.candidateExecutables({ platform: "linux", env: {}, exists: () => false }),
      [...host.LINUX_EXECUTABLES],
    );
  });

  it("follows the code of the PATH on Linux to the real executable", () => {
    const first = path.posix.join("home", "person", "bin");
    const second = path.posix.join("usr", "local", "bin");
    const env = { PATH: ["", first, second].join(":") };
    const launcher = path.posix.join(second, "code");
    const installed = path.posix.join("opt", "visual studio code");
    const scripted = host.candidateExecutables({
      platform: "linux",
      env,
      exists: (file) => file === launcher,
      realpath: (file) => (file === launcher ? path.posix.join(installed, "bin", "code") : null),
    });
    assert.deepEqual(scripted, [path.posix.join(installed, "code"), ...host.LINUX_EXECUTABLES]);
    const direct = host.candidateExecutables({
      platform: "linux",
      env,
      exists: (file) => file === launcher,
      realpath: () => path.posix.join(installed, "code"),
    });
    assert.deepEqual(direct, [path.posix.join(installed, "code"), ...host.LINUX_EXECUTABLES]);
    const packaged = host.candidateExecutables({
      platform: "linux",
      env,
      exists: (file) => file === launcher,
      realpath: () => host.LINUX_EXECUTABLES[0],
    });
    assert.deepEqual(packaged, [...host.LINUX_EXECUTABLES]);
    const wrapped = host.candidateExecutables({
      platform: "linux",
      env,
      exists: (file) => file === launcher,
      realpath: () => path.posix.join("usr", "bin", "snap"),
    });
    assert.deepEqual(wrapped, [...host.LINUX_EXECUTABLES]);
  });

  it("prefers the executable named by ORCHESTWIN_VSCODE when it exists", () => {
    const chosen = fixtures.writeText(folder("chosen"), "Code.exe", "editor\n");
    const local = folder("Local");
    const usual = fixtures.writeText(
      local,
      "Programs/Microsoft VS Code/Code.exe",
      "usual editor\n",
    );
    assert.equal(usual, path.join(local, "Programs", "Microsoft VS Code", "Code.exe"));
    const platform = process.platform === "win32" ? "win32" : "linux";
    const env = { LOCALAPPDATA: local, PATH: "" };
    const preferred = host.findExecutable({
      platform,
      env: { ...env, [host.EXECUTABLE_VARIABLE]: chosen },
    });
    assert.deepEqual(preferred, { file: chosen, source: "VARIABLE", rejected: null });
    const missing = path.join(base, "no such editor");
    const fallback = host.findExecutable({
      platform: "win32",
      env: { ...env, [host.EXECUTABLE_VARIABLE]: missing },
      exists: (file) => file === usual || file === path.win32.normalize(usual),
    });
    assert.equal(fallback.source, "PLACE");
    assert.equal(fallback.rejected, missing);
    assert.equal(path.win32.normalize(fallback.file), path.win32.normalize(usual));
    assert.deepEqual(host.findExecutable({ platform: "linux", env: {}, exists: () => false }), {
      file: null,
      source: null,
      rejected: null,
    });
  });

  it("reads the options of the command line", () => {
    const defaults = { require: false, keep: false, timeout: 120, lang: "en" };
    assert.deepEqual(host.parseArguments([]), defaults);
    assert.equal(host.DEFAULT_TIMEOUT_SECONDS, 120);
    assert.deepEqual(host.parseArguments(["--require", "--keep", "--timeout", "30"]), {
      ...defaults,
      require: true,
      keep: true,
      timeout: 30,
    });
    assert.deepEqual(host.parseArguments(["--timeout=45", "--lang=it"]), {
      ...defaults,
      timeout: 45,
      lang: "it",
    });
    for (const argv of [
      ["--timeout"],
      ["--timeout", "0"],
      ["--timeout", "-5"],
      ["--timeout", "1.5"],
      ["--timeout=abc"],
      ["--lang", "fr"],
      ["--wait"],
      ["workspace"],
    ]) {
      assert.equal(host.parseArguments(argv), null, argv.join(" "));
    }
  });

  it("starts the editor with the extension, the runner and throwaway folders only", () => {
    const place = folder("place");
    const paths = host.placePaths(place);
    assert.deepEqual(host.launchArguments(paths), [
      `--extensionDevelopmentPath=${EXTENSION_ROOT}`,
      `--extensionTestsPath=${RUNNER}`,
      `--user-data-dir=${path.join(place, "user-data")}`,
      `--extensions-dir=${path.join(place, "extensions")}`,
      `--shared-data-dir=${path.join(place, "shared-data")}`,
      `--agent-plugins-dir=${path.join(place, "agent-plugins")}`,
      "--disable-workspace-trust",
      "--skip-welcome",
      "--skip-release-notes",
      "--disable-telemetry",
      "--disable-updates",
      "--disable-experiments",
      "--disable-crash-reporter",
      "--use-inmemory-secretstorage",
      "--new-window",
      path.join(place, "workspace"),
    ]);
    assert.equal(host.RUNNER_FILE, RUNNER);
    assert.ok(!/\.test\.js$/.test(RUNNER));
    assert.equal(paths.result, path.join(place, "result.json"));
  });

  it("gives the editor the environment without ELECTRON_RUN_AS_NODE and another editor", () => {
    const result = path.join(base, "result.json");
    const child = host.childEnvironment(
      {
        ELECTRON_RUN_AS_NODE: "1",
        Electron_Run_As_Node: "1",
        VSCODE_PID: "1234",
        vscode_ipc_hook_cli: "pipe",
        VSCODE_APPDATA: "elsewhere",
        ORCHESTWIN_HOST_CHECK_RESULT: "old",
        orchestwin_host_check_result: "older",
        ELECTRON_ENABLE_LOGGING: "1",
        PATH: "bin",
        LANG: "C",
        NOT_A_STRING: undefined,
      },
      result,
    );
    assert.deepEqual(child, {
      ELECTRON_ENABLE_LOGGING: "1",
      PATH: "bin",
      LANG: "C",
      ORCHESTWIN_HOST_CHECK_RESULT: result,
    });
  });

  it("writes a linked workspace, harmless settings and an empty extensions folder", () => {
    const place = folder("place");
    const env = { SystemRoot: path.join(base, "Windows") };
    const paths = host.preparePlace(place, { platform: "win32", env, crashReporter: true });
    for (const name of Object.values(host.FOLDERS)) {
      assert.ok(fs.statSync(path.join(place, name)).isDirectory(), name);
    }
    assert.deepEqual(fs.readdirSync(paths.extensions), []);
    const settings = fixtures.readJson(paths.userData, "User/settings.json");
    assert.equal(settings["orchestwin.utCommand"], "echo");
    assert.equal(settings["workbench.startupEditor"], "none");
    assert.equal(settings["update.mode"], "none");
    assert.equal(settings["telemetry.telemetryLevel"], "crash");
    assert.equal(settings["terminal.integrated.defaultProfile.windows"], host.TERMINAL_PROFILE);
    assert.deepEqual(settings["terminal.integrated.profiles.windows"], {
      [host.TERMINAL_PROFILE]: {
        path: path.win32.join(env.SystemRoot, "System32", "cmd.exe"),
        args: ["/D"],
      },
    });
    const link = fixtures.readJson(paths.workspace, ".orchestwin/project.json");
    assert.equal(link.studio, "http://127.0.0.1:9");
    assert.equal(link.studio, host.STUDIO_ADDRESS);
    assert.equal(link.project_name, host.PROJECT_NAME);
    assert.equal(fs.existsSync(path.join(paths.workspace, ".orchestwin", "tests")), false);
    const state = readProject(paths.workspace);
    assert.equal(state.linked, true);
    assert.equal(state.folder.name, "Tip calculator for waiters");
    assert.equal(state.folder.complete, true);
    assert.equal(state.tasks.open.length, 3);
    assert.equal(state.twins.items.length, 2);
    assert.equal(state.development.stale, 1);
    assert.notEqual(state.tests.latest, null);
    assert.equal(state.tests.report, null);
    assert.notEqual(state.code, null);
    assert.equal(state.agents.status, "MISSING");
    assert.deepEqual(state.notices, []);
  });

  it("gives the terminal of the check a shell that runs no startup file of the person", () => {
    assert.deepEqual(host.terminalShell("linux", {}), { path: host.POSIX_SHELL, args: [] });
    assert.deepEqual(host.terminalShell("darwin", {}), { path: host.POSIX_SHELL, args: [] });
    const windir = path.join(base, "WINDOWS");
    assert.deepEqual(host.terminalShell("win32", { windir }), {
      path: path.win32.join(windir, "System32", "cmd.exe"),
      args: ["/D"],
    });
    assert.deepEqual(host.terminalShell("win32", {}), { path: "cmd.exe", args: ["/D"] });
    const mac = host.settingsFor("darwin", {});
    assert.equal(mac["terminal.integrated.defaultProfile.osx"], host.TERMINAL_PROFILE);
    const linux = host.settingsFor("linux", {});
    assert.deepEqual(linux["terminal.integrated.profiles.linux"], {
      [host.TERMINAL_PROFILE]: { path: host.POSIX_SHELL, args: [] },
    });
    for (const [key, value] of Object.entries(host.SETTINGS)) {
      assert.deepEqual(linux[key], value, key);
    }
  });

  it("keeps the crash reporter flag of the person's argv.json as it is", () => {
    const argv = [
      "// This configuration file allows you to pass permanent command line arguments.",
      "{",
      '\t// "enable-crash-reporter": false,',
      "\t/* the id */",
      '\t"enable-crash-reporter": true,',
      '\t"crash-reporter-id": "not-a-real-id",',
      '\t"locale": "en",',
      "}",
      "",
    ].join("\n");
    assert.equal(host.crashReporterOf(argv), true);
    assert.equal(host.crashReporterOf(argv.replace(": true,", ": false,")), false);
    assert.equal(host.crashReporterOf(`﻿${argv}`), true);
    assert.equal(host.crashReporterOf('{ "locale": "en" }'), null);
    assert.equal(host.crashReporterOf('{ // "enable-crash-reporter": true\n}'), null);
    assert.equal(host.crashReporterOf('{ "enable-crash-reporter": "true" }'), null);
    assert.equal(host.crashReporterOf("{ not json"), null);
    assert.equal(host.crashReporterOf(undefined), null);
    const home = folder("home");
    assert.equal(host.readCrashReporter(home), null);
    fixtures.writeText(home, ".vscode/argv.json", argv);
    assert.equal(host.readCrashReporter(home), true);
    assert.equal(host.readCrashReporter(""), null);
    assert.equal(host.telemetryLevel(true), "crash");
    assert.equal(host.telemetryLevel(false), "off");
    assert.equal(host.telemetryLevel(null), "off");
    assert.equal(host.settingsFor("linux", {}, true)["telemetry.telemetryLevel"], "crash");
    assert.equal(host.settingsFor("linux", {}, false)["telemetry.telemetryLevel"], "off");
  });

  it("reads a good, a failing, a missing and a broken result file", () => {
    const place = folder("results");
    const good = fixtures.writeJson(place, "good.json", resultOf(["PASSED", "PASSED"]));
    const reading = host.readResult(good);
    assert.equal(reading.status, "OK");
    assert.deepEqual(reading.result, {
      vscodeVersion: "1.139.1",
      language: "en",
      extensionVersion: "0.1.0",
      checks: [
        { name: "activation", outcome: "PASSED", detail: "detail 0" },
        { name: "panel", outcome: "PASSED", detail: "detail 1" },
      ],
    });
    assert.deepEqual(host.summaryOf(reading.result), { total: 2, passed: 2, failed: 0 });
    const failing = host.readResult(
      fixtures.writeJson(place, "failing.json", resultOf(["PASSED", "FAILED", "FAILED"])),
    );
    assert.equal(failing.status, "OK");
    assert.deepEqual(host.summaryOf(failing.result), { total: 3, passed: 1, failed: 2 });
    assert.deepEqual(host.readResult(path.join(place, "missing.json")), {
      status: "MISSING",
      result: null,
    });
    for (const [name, content] of [
      ["broken.json", '{ "checks": ['],
      ["empty.json", JSON.stringify({ checks: [] })],
      ["list.json", "[]"],
      ["outcome.json", JSON.stringify({ checks: [{ name: "panel", outcome: "MAYBE" }] })],
      ["name.json", JSON.stringify({ checks: [{ name: "", outcome: "PASSED" }] })],
    ]) {
      assert.deepEqual(
        host.readResult(fixtures.writeText(place, name, content)),
        { status: "UNREADABLE", result: null },
        name,
      );
    }
    assert.deepEqual(host.readResult(place), { status: "UNREADABLE", result: null });
  });

  it("writes one line per check in English and in Italian", () => {
    const passed = { name: "panel", outcome: "PASSED", detail: "page written" };
    assert.equal(
      host.checkLine(passed),
      "passed  The panel opens and shows the linked project (page written)",
    );
    assert.equal(
      host.checkLine({ name: "panel", outcome: "FAILED", detail: "" }, "it"),
      "fallito   Il pannello si apre e mostra il progetto collegato",
    );
    assert.equal(
      host.checkLine({ name: "extra", outcome: "PASSED", detail: "why" }, "it"),
      "superato  extra (why)",
    );
  });

  it("passes when every check passed, and removes the throwaway folder", async () => {
    const run = session({
      writes: resultOf(["PASSED", "PASSED"]),
      finish: { code: 0, signal: null, error: null },
      env: { ELECTRON_RUN_AS_NODE: "1", VSCODE_PID: "1234", KEEP_ME: "yes" },
    });
    assert.equal(await host.main([], run.io), 0);
    assert.equal(run.launches.length, 1);
    const [launched] = run.launches;
    assert.equal(launched.executable, run.editor);
    assert.equal(launched.linked, true);
    assert.equal(launched.args[0], `--extensionDevelopmentPath=${EXTENSION_ROOT}`);
    assert.equal(launched.env.ELECTRON_RUN_AS_NODE, undefined);
    assert.equal(launched.env.VSCODE_PID, undefined);
    assert.equal(launched.env.KEEP_ME, "yes");
    assert.equal(path.basename(launched.env[host.RESULT_VARIABLE]), "result.json");
    assert.ok(
      path.basename(path.dirname(launched.env[host.RESULT_VARIABLE])).startsWith(host.PLACE_PREFIX),
    );
    const output = run.out.text();
    assert.ok(output.includes(`Checking the panel in ${run.editor} (at most 120 seconds).`));
    assert.ok(output.includes("Visual Studio Code 1.139.1, language en, extension 0.1.0\n"));
    assert.ok(
      output.includes("passed  The extension of this folder is loaded and active (detail 0)\n"),
    );
    assert.ok(output.includes("Checks: 2; passed: 2; failed: 0; time: 0.0 s.\n"));
    assert.deepEqual(fs.readdirSync(run.tmpdir), []);
    assert.equal(run.errors.text(), "");
  });

  it("fails when a check failed or the editor ended badly, and still cleans up", async () => {
    const failing = session({
      writes: resultOf(["PASSED", "FAILED"]),
      finish: { code: 1, signal: null, error: null },
    });
    assert.equal(await host.main(["--lang", "it"], failing.io), 1);
    const italian = failing.out.text();
    assert.ok(italian.includes("fallito   Il pannello si apre e mostra il progetto collegato"));
    assert.ok(italian.includes("Controlli: 2; superati: 1; falliti: 1; tempo: 0.0 s."));
    assert.ok(!italian.includes("stato 1"));
    assert.deepEqual(fs.readdirSync(failing.tmpdir), []);
    const status = session({
      writes: resultOf(["PASSED"]),
      finish: { code: 3, signal: null, error: null },
    });
    assert.equal(await host.main([], status.io), 1);
    assert.ok(status.out.text().includes("Visual Studio Code ended with status 3"));
    assert.deepEqual(fs.readdirSync(status.tmpdir), []);
    const refused = session({ finish: { code: null, signal: null, error: new Error("EACCES") } });
    assert.equal(await host.main([], refused.io), 1);
    assert.ok(refused.out.text().includes("could not be started (EACCES)"));
    assert.deepEqual(fs.readdirSync(refused.tmpdir), []);
  });

  it("fails with its own sentence when the result is missing or broken", async () => {
    const missing = session({
      finish: { code: 1, signal: null, error: null },
      output: "first line\r\n\r\nError: cannot load the runner\n",
    });
    assert.equal(await host.main([], missing.io), 1);
    const text = missing.out.text();
    assert.ok(text.includes("ended without writing the result of the checks"));
    assert.ok(
      text.includes(
        "The last lines written by Visual Studio Code:\n  first line\n  Error: cannot load the runner\n",
      ),
    );
    assert.deepEqual(fs.readdirSync(missing.tmpdir), []);
    const broken = session({
      writes: "{ not json",
      finish: { code: 0, signal: null, error: null },
    });
    assert.equal(await host.main([], broken.io), 1);
    assert.ok(broken.out.text().includes("The result of the checks cannot be read ("));
    assert.deepEqual(fs.readdirSync(broken.tmpdir), []);
  });

  it("stops the whole process tree past the limit and fails", async () => {
    const run = session({ writes: resultOf(["PASSED"]) });
    run.io.wait = () => Promise.resolve();
    assert.equal(await host.main(["--timeout", "5"], run.io), 1);
    assert.deepEqual(run.stopped, [4242]);
    const output = run.out.text();
    assert.ok(output.includes("did not finish within 5 seconds: it was stopped"));
    assert.ok(output.includes("Checks: 1; passed: 1; failed: 0"));
    assert.deepEqual(fs.readdirSync(run.tmpdir), []);
  });

  it("says that nothing was checked when the editor is missing", async () => {
    for (const [argv, expected] of [
      [[], 0],
      [["--require"], 1],
    ]) {
      const run = session();
      run.io.env = { PATH: "" };
      run.io.platform = "linux";
      run.io.exists = () => false;
      assert.equal(await host.main(argv, run.io), expected);
      assert.equal(
        run.out.text(),
        "Visual Studio Code was not found on this computer, so nothing was checked (ORCHESTWIN_VSCODE can name its executable).\n",
      );
      assert.deepEqual(run.launches, []);
      assert.deepEqual(fs.readdirSync(run.tmpdir), []);
    }
    const named = session();
    const missing = path.join(base, "missing editor");
    named.io.env = { [host.EXECUTABLE_VARIABLE]: missing };
    named.io.platform = "linux";
    named.io.exists = () => false;
    assert.equal(await host.main(["--lang", "it"], named.io), 0);
    const italian = named.out.text();
    assert.ok(italian.startsWith(`ORCHESTWIN_VSCODE indica ${missing}, che non esiste`));
    assert.ok(italian.includes("non è stato controllato niente"));
  });

  it("keeps the throwaway folder when asked and says where it is", async () => {
    const run = session({
      writes: resultOf(["PASSED"]),
      finish: { code: 0, signal: null, error: null },
    });
    assert.equal(await host.main(["--keep"], run.io), 0);
    const [kept] = fs.readdirSync(run.tmpdir);
    assert.ok(kept.startsWith(host.PLACE_PREFIX));
    const place = fs.realpathSync.native(path.join(run.tmpdir, kept));
    assert.ok(run.out.text().includes(`The throwaway folder is kept: ${place}\n`));
    assert.ok(fs.existsSync(path.join(place, "workspace", ".orchestwin", "project.json")));
    assert.ok(fs.existsSync(path.join(place, "result.json")));
  });

  it("tries the removal several times and says when it could not remove the folder", async () => {
    const pauses = [];
    let calls = 0;
    const removed = await host.removePlace("place", {
      remove() {
        calls += 1;
        if (calls < 3) {
          throw new Error("EBUSY");
        }
      },
      wait: async (milliseconds) => {
        pauses.push(milliseconds);
      },
    });
    assert.equal(removed, true);
    assert.equal(calls, 3);
    assert.deepEqual(pauses, [500, 500]);
    let attempts = 0;
    const refused = await host.removePlace("place", {
      remove() {
        attempts += 1;
        throw new Error("EPERM");
      },
      wait: async () => {},
      attempts: 4,
    });
    assert.equal(refused, false);
    assert.equal(attempts, 4);
    const run = session({
      writes: resultOf(["PASSED"]),
      finish: { code: 0, signal: null, error: null },
    });
    run.io.wait = onlyPauses;
    run.io.remove = () => {
      throw new Error("EBUSY");
    };
    assert.equal(await host.main([], run.io), 0);
    assert.ok(run.out.text().includes("The throwaway folder could not be removed: "));
    const [left] = fs.readdirSync(run.tmpdir);
    fixtures.removeFolder(path.join(run.tmpdir, left));
  });

  it("stops the tree with taskkill on Windows and the process group elsewhere", () => {
    const commands = [];
    assert.equal(
      host.stopTree(4242, "win32", {
        runCommand: (program, args, options) => {
          commands.push({ program, args, options });
          return { status: 0 };
        },
      }),
      true,
    );
    assert.deepEqual(commands, [
      {
        program: "taskkill",
        args: ["/PID", "4242", "/T", "/F"],
        options: { stdio: "ignore", windowsHide: true },
      },
    ]);
    const signals = [];
    assert.equal(
      host.stopTree(4242, "linux", { kill: (target, signal) => signals.push([target, signal]) }),
      true,
    );
    assert.deepEqual(signals, [[-4242, "SIGKILL"]]);
    const fallback = [];
    host.stopTree(4242, "darwin", {
      kill(target, signal) {
        fallback.push([target, signal]);
        if (target < 0) {
          throw new Error("ESRCH");
        }
      },
    });
    assert.deepEqual(fallback, [
      [-4242, "SIGKILL"],
      [4242, "SIGKILL"],
    ]);
    assert.equal(
      host.stopTree(undefined, "win32", { runCommand: () => assert.fail("nothing to stop") }),
      false,
    );
  });

  it("waits for the end of the editor and reports its status", async () => {
    const ended = await host.waitForEnd(
      { pid: 7, exited: Promise.resolve({ code: 0, signal: null, error: null }) },
      1000,
      { wait: never, stopTree: () => assert.fail("nothing to stop"), platform: "linux" },
    );
    assert.deepEqual(ended, { code: 0, signal: null, error: null, timedOut: false });
    let release;
    const stopped = [];
    const late = await host.waitForEnd(
      {
        pid: 8,
        exited: new Promise((resolve) => {
          release = resolve;
        }),
      },
      1000,
      {
        wait: () => Promise.resolve(),
        stopTree(pid, platform) {
          stopped.push([pid, platform]);
          release({ code: null, signal: "SIGKILL", error: null });
        },
        platform: "linux",
      },
    );
    assert.deepEqual(stopped, [[8, "linux"]]);
    assert.equal(late.timedOut, true);
    assert.equal(late.error, null);
    assert.equal(late.code, null);
  });

  it("launches a real program, collects what it writes and waits for its end", async () => {
    const launched = host.launch(
      process.execPath,
      [
        "-e",
        "process.stdout.write('out line\\n'); process.stderr.write('err line\\n'); process.exit(3)",
      ],
      { ...process.env },
    );
    assert.ok(Number.isInteger(launched.pid));
    const end = await launched.exited;
    assert.deepEqual(end, { code: 3, signal: null, error: null });
    assert.ok(launched.output().includes("out line"));
    assert.ok(launched.output().includes("err line"));
    const missing = host.launch(path.join(base, "no such program"), [], { ...process.env });
    const failure = await missing.exited;
    assert.equal(failure.code, null);
    assert.ok(failure.error instanceof Error);
  });

  it("refuses unknown options with the usage in both languages", async () => {
    const run = session();
    assert.equal(await host.main(["--bogus"], run.io), 2);
    assert.ok(run.errors.text().includes("Usage: node editors/vscode/scripts/host-check.mjs"));
    assert.ok(run.errors.text().includes("Uso: node editors/vscode/scripts/host-check.mjs"));
    assert.equal(run.out.text(), "");
    assert.deepEqual(run.launches, []);
  });
});
