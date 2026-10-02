import { spawn, spawnSync } from "node:child_process";
import fs from "node:fs";
import os from "node:os";
import path from "node:path";
import process from "node:process";
import { setTimeout as sleep } from "node:timers/promises";
import { fileURLToPath } from "node:url";
import fixtures from "../test/fixtures.js";

export const EXTENSION_ROOT = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");
export const RUNNER_FILE = path.join(EXTENSION_ROOT, "test", "host", "runner.js");
export const EXECUTABLE_VARIABLE = "ORCHESTWIN_VSCODE";
export const RESULT_VARIABLE = "ORCHESTWIN_HOST_CHECK_RESULT";
export const DEFAULT_TIMEOUT_SECONDS = 120;
export const PLACE_PREFIX = "orchestwin-host-check-";
export const RESULT_NAME = "result.json";
export const PROJECT_NAME = "Tip calculator";
export const STUDIO_ADDRESS = "http://127.0.0.1:9";
export const TERMINAL_PROFILE = "OrchesTwin check";
export const POSIX_SHELL = "/bin/sh";
export const OUTCOMES = Object.freeze(["PASSED", "FAILED"]);
export const FOLDERS = Object.freeze({
  userData: "user-data",
  extensions: "extensions",
  workspace: "workspace",
  sharedData: "shared-data",
  agentPlugins: "agent-plugins",
});
export const WINDOWS_PLACES = Object.freeze([
  Object.freeze(["LOCALAPPDATA", "Programs", "Microsoft VS Code", "Code.exe"]),
  Object.freeze(["ProgramFiles", "Microsoft VS Code", "Code.exe"]),
]);
export const MACOS_EXECUTABLES = Object.freeze([
  "/Applications/Visual Studio Code.app/Contents/MacOS/Electron",
  "/Applications/Visual Studio Code.app/Contents/MacOS/Code",
]);
export const LINUX_EXECUTABLES = Object.freeze([
  "/usr/share/code/code",
  "/snap/code/current/usr/share/code/code",
]);
export const ARGV_FILE = Object.freeze([".vscode", "argv.json"]);
export const CRASH_REPORTER_KEY = "enable-crash-reporter";
export const SETTINGS = Object.freeze({
  "orchestwin.utCommand": "echo",
  "workbench.startupEditor": "none",
  "update.mode": "none",
  "extensions.autoCheckUpdates": false,
  "extensions.autoUpdate": false,
  "extensions.ignoreRecommendations": true,
  "workbench.enableExperiments": false,
  "chat.disableAIFeatures": true,
  "chat.mcp.access": "none",
  "git.enabled": false,
  "terminal.integrated.enablePersistentSessions": false,
});
export const LAUNCH_SWITCHES = Object.freeze([
  "--disable-workspace-trust",
  "--skip-welcome",
  "--skip-release-notes",
  "--disable-telemetry",
  "--disable-updates",
  "--disable-experiments",
  "--disable-crash-reporter",
  "--use-inmemory-secretstorage",
  "--new-window",
]);

const REMOVED_VARIABLE = /^(?:ELECTRON_RUN_AS_NODE$|VSCODE_)/i;
const TIMEOUT_PATTERN = /^[1-9]\d{0,5}$/;
const OUTPUT_LIMIT = 65536;
const OUTPUT_LINES = 20;
const STOP_GRACE = 10000;
const REMOVE_ATTEMPTS = 10;
const REMOVE_PAUSE = 500;
const TIMED_OUT = Symbol("timedOut");
const MESSAGES = Object.freeze({
  en: Object.freeze({
    usage:
      "Usage: node editors/vscode/scripts/host-check.mjs [--require] [--keep] [--timeout SECONDS] [--lang en|it]",
    notFound:
      "Visual Studio Code was not found on this computer, so nothing was checked (ORCHESTWIN_VSCODE can name its executable).",
    rejected:
      "ORCHESTWIN_VSCODE names {file}, which does not exist: the usual places are searched.",
    starting: "Checking the panel in {file} (at most {seconds} seconds).",
    header: "Visual Studio Code {version}, language {language}, extension {extension}",
    passed: "passed",
    failed: "failed",
    counts: "Checks: {total}; passed: {passed}; failed: {failed}; time: {seconds} s.",
    timeout:
      "Visual Studio Code did not finish within {seconds} seconds: it was stopped, and the check failed.",
    notStarted: "Visual Studio Code could not be started ({reason}), so the check failed.",
    missing:
      "Visual Studio Code ended without writing the result of the checks, so the check failed.",
    unreadable: "The result of the checks cannot be read ({file}), so the check failed.",
    exitStatus: "Visual Studio Code ended with status {status}, so the check failed.",
    output: "The last lines written by Visual Studio Code:",
    kept: "The throwaway folder is kept: {place}",
    notRemoved: "The throwaway folder could not be removed: {place}",
    notPrepared: "The throwaway folder could not be prepared ({reason}), so the check failed.",
    unknown: "unknown",
    checks: Object.freeze({
      activation: "The extension of this folder is loaded and active",
      commands: "Every command of the manifest is registered",
      manifest: "The texts of the manifest come from its language file",
      setting: "The program of the buttons comes from the user settings",
      panel: "The panel opens and shows the linked project",
      watcher: "The panel updates itself when a file of the project changes",
      report: "Without a report, the panel says so and opens nothing",
      terminal: "The buttons write in one terminal named OrchesTwin",
      terminalReopen: "After the terminal is closed, the next button opens a new one",
      agents: "The twins are connected to the agents of the editor, once",
    }),
  }),
  it: Object.freeze({
    usage:
      "Uso: node editors/vscode/scripts/host-check.mjs [--require] [--keep] [--timeout SECONDI] [--lang en|it]",
    notFound:
      "Visual Studio Code non è stato trovato su questo computer, quindi non è stato controllato niente (ORCHESTWIN_VSCODE può indicare il suo eseguibile).",
    rejected: "ORCHESTWIN_VSCODE indica {file}, che non esiste: si cerca nei posti consueti.",
    starting: "Controllo del pannello in {file} (al massimo {seconds} secondi).",
    header: "Visual Studio Code {version}, lingua {language}, estensione {extension}",
    passed: "superato",
    failed: "fallito",
    counts: "Controlli: {total}; superati: {passed}; falliti: {failed}; tempo: {seconds} s.",
    timeout:
      "Visual Studio Code non ha finito entro {seconds} secondi: è stato fermato, e il controllo è fallito.",
    notStarted:
      "Non è stato possibile avviare Visual Studio Code ({reason}), quindi il controllo è fallito.",
    missing:
      "Visual Studio Code ha finito senza scrivere il risultato dei controlli, quindi il controllo è fallito.",
    unreadable: "Il risultato dei controlli non si legge ({file}), quindi il controllo è fallito.",
    exitStatus:
      "Visual Studio Code ha finito con lo stato {status}, quindi il controllo è fallito.",
    output: "Le ultime righe scritte da Visual Studio Code:",
    kept: "La cartella usa e getta resta qui: {place}",
    notRemoved: "Non è stato possibile rimuovere la cartella usa e getta: {place}",
    notPrepared:
      "Non è stato possibile preparare la cartella usa e getta ({reason}), quindi il controllo è fallito.",
    unknown: "sconosciuta",
    checks: Object.freeze({
      activation: "L'estensione di questa cartella è caricata e attiva",
      commands: "Ogni comando del manifest è registrato",
      manifest: "I testi del manifest vengono dal suo file della lingua",
      setting: "Il programma dei pulsanti viene dalle impostazioni dell'utente",
      panel: "Il pannello si apre e mostra il progetto collegato",
      watcher: "Il pannello si aggiorna da solo quando cambia un file del progetto",
      report: "Senza rapporto, il pannello lo dice e non apre niente",
      terminal: "I pulsanti scrivono in un solo terminale di nome OrchesTwin",
      terminalReopen: "Chiuso il terminale, il pulsante successivo ne apre uno nuovo",
      agents: "I twin sono collegati agli agenti dell'editor, una volta sola",
    }),
  }),
});

function isObject(value) {
  return value !== null && typeof value === "object" && !Array.isArray(value);
}

function textOf(value) {
  return typeof value === "string" && value.trim() !== "" ? value : null;
}

function fill(pattern, values) {
  return pattern.replace(/\{(\w+)\}/g, (match, name) =>
    Object.hasOwn(values, name) ? String(values[name]) : match,
  );
}

function reasonOf(error) {
  return error instanceof Error ? error.message : String(error);
}

function isFile(file) {
  try {
    return fs.statSync(file).isFile();
  } catch {
    return false;
  }
}

function realFile(file) {
  try {
    return fs.realpathSync(file);
  } catch {
    return null;
  }
}

function wait(milliseconds, signal) {
  return sleep(milliseconds, undefined, signal === undefined ? undefined : { signal });
}

function removeFolder(place) {
  fs.rmSync(place, { recursive: true, force: true });
}

export function variable(env, name, platform = process.platform) {
  if (!isObject(env)) {
    return undefined;
  }
  if (Object.hasOwn(env, name)) {
    return env[name];
  }
  if (platform !== "win32") {
    return undefined;
  }
  const key = Object.keys(env).find((item) => item.toUpperCase() === name.toUpperCase());
  return key === undefined ? undefined : env[key];
}

function findOnPath(name, env, exists) {
  const value = textOf(variable(env, "PATH", "linux"));
  if (value === null) {
    return null;
  }
  for (const folder of value.split(":")) {
    if (folder === "") {
      continue;
    }
    const candidate = path.posix.join(folder, name);
    if (exists(candidate)) {
      return candidate;
    }
  }
  return null;
}

export function candidateExecutables({
  platform = process.platform,
  env = process.env,
  exists = isFile,
  realpath = realFile,
} = {}) {
  if (platform === "win32") {
    return WINDOWS_PLACES.map(([name, ...parts]) => {
      const base = textOf(variable(env, name, platform));
      return base === null ? null : path.win32.join(base, ...parts);
    }).filter((candidate) => candidate !== null);
  }
  if (platform === "darwin") {
    return [...MACOS_EXECUTABLES];
  }
  const candidates = [];
  const found = findOnPath("code", env, exists);
  const real = found === null ? null : realpath(found);
  if (typeof real === "string" && path.posix.basename(real) === "code") {
    const folder = path.posix.dirname(real);
    candidates.push(
      path.posix.basename(folder) === "bin"
        ? path.posix.join(path.posix.dirname(folder), "code")
        : real,
    );
  }
  return [...candidates, ...LINUX_EXECUTABLES.filter((item) => !candidates.includes(item))];
}

export function findExecutable({
  platform = process.platform,
  env = process.env,
  exists = isFile,
  realpath = realFile,
} = {}) {
  const chosen = textOf(variable(env, EXECUTABLE_VARIABLE, platform));
  if (chosen !== null && exists(chosen)) {
    return { file: chosen, source: "VARIABLE", rejected: null };
  }
  const file =
    candidateExecutables({ platform, env, exists, realpath }).find((candidate) =>
      exists(candidate),
    ) ?? null;
  return { file, source: file === null ? null : "PLACE", rejected: chosen };
}

export function parseArguments(argv) {
  const options = {
    require: false,
    keep: false,
    timeout: String(DEFAULT_TIMEOUT_SECONDS),
    lang: "en",
  };
  for (let index = 0; index < argv.length; index += 1) {
    const argument = argv[index];
    if (argument === "--require" || argument === "--keep") {
      options[argument.slice(2)] = true;
    } else if ((argument === "--timeout" || argument === "--lang") && index + 1 < argv.length) {
      options[argument.slice(2)] = argv[index + 1];
      index += 1;
    } else if (argument.startsWith("--timeout=")) {
      options.timeout = argument.slice("--timeout=".length);
    } else if (argument.startsWith("--lang=")) {
      options.lang = argument.slice("--lang=".length);
    } else {
      return null;
    }
  }
  if (!TIMEOUT_PATTERN.test(options.timeout) || !Object.hasOwn(MESSAGES, options.lang)) {
    return null;
  }
  return { ...options, timeout: Number(options.timeout) };
}

function settingsKey(platform) {
  if (platform === "win32") {
    return "windows";
  }
  return platform === "darwin" ? "osx" : "linux";
}

export function terminalShell(platform = process.platform, env = process.env) {
  if (platform !== "win32") {
    return { path: POSIX_SHELL, args: [] };
  }
  const root =
    textOf(variable(env, "SystemRoot", platform)) ?? textOf(variable(env, "windir", platform));
  return {
    path: root === null ? "cmd.exe" : path.win32.join(root, "System32", "cmd.exe"),
    args: ["/D"],
  };
}

function withoutComments(value) {
  let result = "";
  let index = 0;
  let quoted = false;
  while (index < value.length) {
    const character = value[index];
    const next = value[index + 1];
    if (quoted) {
      result += character;
      if (character === "\\" && next !== undefined) {
        result += next;
        index += 2;
        continue;
      }
      quoted = character !== '"';
      index += 1;
    } else if (character === '"') {
      quoted = true;
      result += character;
      index += 1;
    } else if (character === "/" && next === "/") {
      const end = value.indexOf("\n", index);
      index = end === -1 ? value.length : end;
    } else if (character === "/" && next === "*") {
      const end = value.indexOf("*/", index + 2);
      index = end === -1 ? value.length : end + 2;
    } else {
      result += character;
      index += 1;
    }
  }
  return result.replace(/,(\s*[}\]])/g, "$1");
}

export function crashReporterOf(content) {
  if (typeof content !== "string") {
    return null;
  }
  try {
    const value = JSON.parse(withoutComments(content.replace(/^﻿/, "")));
    return isObject(value) && typeof value[CRASH_REPORTER_KEY] === "boolean"
      ? value[CRASH_REPORTER_KEY]
      : null;
  } catch {
    return null;
  }
}

export function readCrashReporter(home = os.homedir()) {
  if (typeof home !== "string" || home === "") {
    return null;
  }
  try {
    return crashReporterOf(fs.readFileSync(path.join(home, ...ARGV_FILE), "utf8"));
  } catch {
    return null;
  }
}

export function telemetryLevel(crashReporter) {
  return crashReporter === true ? "crash" : "off";
}

export function settingsFor(platform = process.platform, env = process.env, crashReporter = null) {
  const key = settingsKey(platform);
  return {
    ...SETTINGS,
    "telemetry.telemetryLevel": telemetryLevel(crashReporter),
    [`terminal.integrated.profiles.${key}`]: { [TERMINAL_PROFILE]: terminalShell(platform, env) },
    [`terminal.integrated.defaultProfile.${key}`]: TERMINAL_PROFILE,
  };
}

export function placePaths(place) {
  return {
    place,
    userData: path.join(place, FOLDERS.userData),
    extensions: path.join(place, FOLDERS.extensions),
    workspace: path.join(place, FOLDERS.workspace),
    sharedData: path.join(place, FOLDERS.sharedData),
    agentPlugins: path.join(place, FOLDERS.agentPlugins),
    result: path.join(place, RESULT_NAME),
  };
}

export function createPlace(tmpdir = os.tmpdir()) {
  return fs.realpathSync.native(fs.mkdtempSync(path.join(tmpdir, PLACE_PREFIX)));
}

export function preparePlace(
  place,
  { platform = process.platform, env = process.env, crashReporter = null } = {},
) {
  const paths = placePaths(place);
  for (const key of Object.keys(FOLDERS)) {
    fs.mkdirSync(paths[key], { recursive: true });
  }
  fixtures.writeJson(
    paths.userData,
    "User/settings.json",
    settingsFor(platform, env, crashReporter),
  );
  fixtures.writeCompleteProject(paths.workspace, "new");
  fixtures.writeJson(paths.workspace, ".orchestwin/project.json", {
    ...fixtures.link(PROJECT_NAME),
    studio: STUDIO_ADDRESS,
  });
  fs.rmSync(path.join(paths.workspace, ".orchestwin", "tests"), { recursive: true, force: true });
  return paths;
}

export function launchArguments(
  paths,
  { extensionRoot = EXTENSION_ROOT, runner = RUNNER_FILE } = {},
) {
  return [
    `--extensionDevelopmentPath=${extensionRoot}`,
    `--extensionTestsPath=${runner}`,
    `--user-data-dir=${paths.userData}`,
    `--extensions-dir=${paths.extensions}`,
    `--shared-data-dir=${paths.sharedData}`,
    `--agent-plugins-dir=${paths.agentPlugins}`,
    ...LAUNCH_SWITCHES,
    paths.workspace,
  ];
}

export function childEnvironment(env, resultFile) {
  const child = {};
  for (const [name, value] of Object.entries(env)) {
    if (
      typeof value === "string" &&
      !REMOVED_VARIABLE.test(name) &&
      name.toUpperCase() !== RESULT_VARIABLE
    ) {
      child[name] = value;
    }
  }
  child[RESULT_VARIABLE] = resultFile;
  return child;
}

function resultOf(value) {
  if (!isObject(value) || !Array.isArray(value.checks) || value.checks.length === 0) {
    return null;
  }
  const checks = [];
  for (const check of value.checks) {
    if (!isObject(check) || textOf(check.name) === null || !OUTCOMES.includes(check.outcome)) {
      return null;
    }
    checks.push({
      name: check.name,
      outcome: check.outcome,
      detail: typeof check.detail === "string" ? check.detail : "",
    });
  }
  return {
    vscodeVersion: textOf(value.vscode_version),
    language: textOf(value.language),
    extensionVersion: textOf(value.extension_version),
    checks,
  };
}

export function readResult(file) {
  let content;
  try {
    content = fs.readFileSync(file, "utf8");
  } catch (error) {
    const missing = error && (error.code === "ENOENT" || error.code === "ENOTDIR");
    return { status: missing ? "MISSING" : "UNREADABLE", result: null };
  }
  let value;
  try {
    value = JSON.parse(content.replace(/^﻿/, ""));
  } catch {
    return { status: "UNREADABLE", result: null };
  }
  const result = resultOf(value);
  return result === null ? { status: "UNREADABLE", result: null } : { status: "OK", result };
}

export function summaryOf(result) {
  const passed = result.checks.filter((check) => check.outcome === "PASSED").length;
  return { total: result.checks.length, passed, failed: result.checks.length - passed };
}

export function checkLine(check, lang = "en") {
  const texts = MESSAGES[lang] ?? MESSAGES.en;
  const width = Math.max(texts.passed.length, texts.failed.length);
  const word = check.outcome === "PASSED" ? texts.passed : texts.failed;
  const title = Object.hasOwn(texts.checks, check.name) ? texts.checks[check.name] : check.name;
  return `${word.padEnd(width)}  ${title}${check.detail === "" ? "" : ` (${check.detail})`}`;
}

export function launch(executable, args, env, platform = process.platform) {
  let child;
  try {
    child = spawn(executable, args, {
      env,
      stdio: ["ignore", "pipe", "pipe"],
      detached: platform !== "win32",
    });
  } catch (error) {
    return {
      pid: undefined,
      exited: Promise.resolve({ code: null, signal: null, error }),
      output: () => "",
    };
  }
  let output = "";
  const collect = (chunk) => {
    output = `${output}${chunk}`.slice(-OUTPUT_LIMIT);
  };
  for (const stream of [child.stdout, child.stderr]) {
    stream.setEncoding("utf8");
    stream.on("data", collect);
  }
  const exited = new Promise((resolve) => {
    let settled = false;
    const settle = (value) => {
      if (settled) {
        return;
      }
      settled = true;
      child.stdout.destroy();
      child.stderr.destroy();
      resolve(value);
    };
    child.once("error", (error) => settle({ code: null, signal: null, error }));
    child.once("exit", (code, signal) => settle({ code, signal, error: null }));
  });
  return { pid: child.pid, exited, output: () => output };
}

export function stopTree(
  pid,
  platform = process.platform,
  { runCommand = spawnSync, kill = (target, signal) => process.kill(target, signal) } = {},
) {
  if (!Number.isInteger(pid) || pid <= 0) {
    return false;
  }
  if (platform === "win32") {
    const outcome = runCommand("taskkill", ["/PID", String(pid), "/T", "/F"], {
      stdio: "ignore",
      windowsHide: true,
    });
    return Boolean(outcome) && outcome.status === 0;
  }
  for (const target of [-pid, pid]) {
    try {
      kill(target, "SIGKILL");
      return true;
    } catch {
      continue;
    }
  }
  return false;
}

export async function waitForEnd(
  launched,
  milliseconds,
  { wait: pause = wait, stopTree: stop = stopTree, platform = process.platform } = {},
) {
  const limit = new AbortController();
  const expired = pause(milliseconds, limit.signal).then(
    () => TIMED_OUT,
    () => new Promise(() => {}),
  );
  const first = await Promise.race([launched.exited, expired]);
  if (first !== TIMED_OUT) {
    limit.abort();
    return { ...first, timedOut: false };
  }
  stop(launched.pid, platform);
  const grace = new AbortController();
  const stopped = await Promise.race([
    launched.exited,
    pause(STOP_GRACE, grace.signal).then(
      () => null,
      () => null,
    ),
  ]);
  grace.abort();
  return {
    code: stopped === null ? null : stopped.code,
    signal: stopped === null ? null : stopped.signal,
    error: null,
    timedOut: true,
  };
}

export async function removePlace(
  place,
  {
    remove = removeFolder,
    wait: pause = wait,
    attempts = REMOVE_ATTEMPTS,
    delay = REMOVE_PAUSE,
  } = {},
) {
  for (let attempt = 1; attempt <= attempts; attempt += 1) {
    try {
      remove(place);
      return true;
    } catch {
      if (attempt < attempts) {
        await pause(delay);
      }
    }
  }
  return false;
}

function lastLines(output) {
  return output
    .split(/\r?\n/)
    .map((line) => line.trimEnd())
    .filter((line) => line !== "")
    .slice(-OUTPUT_LINES);
}

function defaultIo() {
  return {
    env: process.env,
    platform: process.platform,
    tmpdir: os.tmpdir(),
    home: os.homedir(),
    stdout: process.stdout,
    stderr: process.stderr,
    exists: isFile,
    realpath: realFile,
    launch,
    stopTree,
    wait,
    remove: removeFolder,
    now: () => performance.now(),
  };
}

async function checkIn(place, executable, options, io) {
  const texts = MESSAGES[options.lang];
  const say = (key, values = {}) => io.stdout.write(`${fill(texts[key], values)}\n`);
  const showOutput = (launched) => {
    const lines = lastLines(launched.output());
    if (lines.length > 0) {
      io.stdout.write(`${texts.output}\n${lines.map((line) => `  ${line}`).join("\n")}\n`);
    }
  };
  let paths;
  try {
    paths = preparePlace(place, {
      platform: io.platform,
      env: io.env,
      crashReporter: readCrashReporter(io.home),
    });
  } catch (error) {
    say("notPrepared", { reason: reasonOf(error) });
    return 1;
  }
  say("starting", { file: executable, seconds: options.timeout });
  const started = io.now();
  const launched = io.launch(
    executable,
    launchArguments(paths),
    childEnvironment(io.env, paths.result),
    io.platform,
  );
  const end = await waitForEnd(launched, options.timeout * 1000, io);
  const seconds = ((io.now() - started) / 1000).toFixed(1);
  const reading = readResult(paths.result);
  let summary = null;
  if (reading.status === "OK") {
    const result = reading.result;
    say("header", {
      version: result.vscodeVersion ?? texts.unknown,
      language: result.language ?? texts.unknown,
      extension: result.extensionVersion ?? texts.unknown,
    });
    for (const check of result.checks) {
      io.stdout.write(`${checkLine(check, options.lang)}\n`);
    }
    summary = summaryOf(result);
    say("counts", { ...summary, seconds });
  }
  if (end.timedOut) {
    say("timeout", { seconds: options.timeout });
    showOutput(launched);
    return 1;
  }
  if (end.error) {
    say("notStarted", { reason: reasonOf(end.error) });
    return 1;
  }
  if (reading.status !== "OK") {
    if (reading.status === "MISSING") {
      say("missing");
    } else {
      say("unreadable", { file: paths.result });
    }
    showOutput(launched);
    return 1;
  }
  if (summary.failed > 0) {
    return 1;
  }
  if (end.code !== 0) {
    say("exitStatus", { status: end.code ?? end.signal ?? texts.unknown });
    return 1;
  }
  return 0;
}

export async function main(argv = process.argv.slice(2), overrides = {}) {
  const io = { ...defaultIo(), ...overrides };
  const options = parseArguments(argv);
  if (options === null) {
    io.stderr.write(`${MESSAGES.en.usage}\n${MESSAGES.it.usage}\n`);
    return 2;
  }
  const texts = MESSAGES[options.lang];
  const say = (key, values = {}) => io.stdout.write(`${fill(texts[key], values)}\n`);
  const found = findExecutable({
    platform: io.platform,
    env: io.env,
    exists: io.exists,
    realpath: io.realpath,
  });
  if (found.rejected !== null) {
    say("rejected", { file: found.rejected });
  }
  if (found.file === null) {
    say("notFound");
    return options.require ? 1 : 0;
  }
  let place;
  try {
    place = createPlace(io.tmpdir);
  } catch (error) {
    say("notPrepared", { reason: reasonOf(error) });
    return 1;
  }
  try {
    return await checkIn(place, found.file, options, io);
  } finally {
    if (options.keep) {
      say("kept", { place });
    } else if (!(await removePlace(place, { remove: io.remove, wait: io.wait }))) {
      say("notRemoved", { place });
    }
  }
}

function launchedDirectly() {
  if (typeof process.argv[1] !== "string") {
    return false;
  }
  try {
    return (
      fs.realpathSync(path.resolve(process.argv[1])) ===
      fs.realpathSync(fileURLToPath(import.meta.url))
    );
  } catch {
    return false;
  }
}

if (launchedDirectly()) {
  process.exitCode = await main();
}
